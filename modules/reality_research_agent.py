"""Reality-First Research Agent orchestration.

This module turns the existing Bloodhound search, web research, grounding, and
memory pieces into one coherent source-grounded research workflow.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable

from core.reality_grounding.claim_validator import extract_claims
from core.reality_grounding.prompt_firewall import defuse_untrusted_text, fence_untrusted, removed_note, untrusted_rule
from modules.data_stores import DATA_ROOT
from modules.file_lock import append_line
from modules.file_utils import atomic_write_text
from modules.retellings import Embed, fold_retellings
from modules.web_research import clean_text, get_domain, slugify_query
from search.bloodhound_search import (
    default_bloodhound_config,
    detect_bloodhound_query,
    run_bloodhound_search,
)


logger = logging.getLogger(__name__)

REPORT_DIR = DATA_ROOT / "research_reports"
MEMORY_INDEX_FILE = REPORT_DIR / "memory_index.jsonl"

RESEARCH_COMMAND_PATTERNS = [
    r"^research this deeply\s*:?\s*(.+)$",
    r"^deeply research\s+(.+)$",
    r"^research\s+(.+)$",
    r"^verify\s+(.+)$",
    r"^fact[- ]?check\s+(.+)$",
    r"^find contradictions(?: in| about)?\s+(.+)$",
    r"^trace sources(?: for| on)?\s+(.+)$",
    r"^source[- ]?ground\s+(.+)$",
    r"^reality[- ]?first research\s+(.+)$",
]

TRUSTED_DOMAIN_HINTS = {
    ".gov": 0.16,
    ".edu": 0.14,
    "nih.gov": 0.16,
    "ncbi.nlm.nih.gov": 0.18,
    "who.int": 0.14,
    "cdc.gov": 0.14,
    "nasa.gov": 0.14,
    "arxiv.org": 0.08,
    "wikipedia.org": 0.04,
    "github.com": 0.04,
}

VERDICT_OPTIONS = [
    "LIKELY TRUE",
    "WEAKLY SUPPORTED",
    "LIKELY FALSE",
    "WEAKLY CONTRADICTED",
    "MIXED / CONFLICTING",
    "UNSUPPORTED",
    # Older saved reports may contain these. The checker no longer produces them: keyword-level
    # passage matching cannot prove a claim, rule one out, or judge what is physically possible.
    "TRUE",
    "FALSE",
    "SPECULATIVE",
    "FICTIONAL / IMPOSSIBLE UNDER CURRENT EVIDENCE",
]

# --- Claim checking ------------------------------------------------------------------------------
# A verdict depends on whether retrieved passages address the claim, never on how many trusted
# sites came back. Matching is keyword-level (no language understanding), so the report quotes the
# passages it relied on and the strongest labels are "LIKELY ...".

_VERIFICATION_RE = re.compile(
    r"\b(?:verify|verified|fact[- ]?check(?:ed|ing)?|debunk(?:ed)?|true or false)\b"
    r"|\bis (?:it|this|that) (?:true|real|correct|accurate)\b"
    r"|^\s*(?:did|was|were|is|are|does|has|have|had)\b"
    # "do vaccines cause autism" is a question; "do a deep dive on X" is an instruction.
    r"|^\s*do\s+(?!a\b|an\b|the\b|some\b|my\b|me\b|this\b|that\b|it\b)",
    re.IGNORECASE,
)
_CLAIM_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can|could|would) you\s+)?"
    r"(?:(?:verify|fact[- ]?check|confirm|check|debunk)[\s:,-]+(?:(?:(?:this|the|that)\s+)?claim[\s:,-]+)?(?:(?:whether|if|that)\s+)?"
    r"|is\s+(?:it|this|that)\s+(?:true|real|correct|accurate)\s*(?:that\s+|[:,-]\s*)?"
    r"|true or false\s*[:,-]?\s*)",
    re.IGNORECASE,
)
_CLAIM_STOPWORDS = frozenset(
    """a about after all also an and any are as at be because been before being but by can could did do does
    doing during each for from had has have having he her here hers him his how i if in into is it its itself
    just may me might more most my of on only or other our out over own really same she should so some such
    than that the their them then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your""".split()
)
_NEGATOR_RE = re.compile(r"\b\w+n't\b|\b(?:no|not|never|none|neither|nor|cannot|without)\b", re.IGNORECASE)
_REFUTATION_CUES = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in [
        ("false", r"\b(?:false|falsely|untrue|incorrect|inaccurate|wrong)\b"),
        ("myth", r"\bmyths?\b"),
        ("hoax", r"\bhoax\w*\b"),
        ("debunk", r"\b(?:debunk\w*|disprov\w*|refut\w*|discredit\w*)\b"),
        ("fake", r"\b(?:fak(?:e|ed|es|ing)|fabricat\w*|bogus)\b"),
        ("baseless", r"\b(?:baseless|unfounded|no evidence)\b"),
        ("misinformation", r"\b(?:mis|dis)information\b"),
        ("conspiracy", r"\bconspirac\w+\b"),
        ("pseudoscience", r"\bpseudoscien\w+\b"),
        ("misconception", r"\bmisconceptions?\b"),
        ("legend", r"\burban legends?\b|\bold wives'? tales?\b"),
    ]
]
# Sentences that report what others say ("some people believe ...") don't count as support.
_ATTRIBUTION_RE = re.compile(
    r"\b(?:believ\w+|claims?|claimed|claiming|alleg\w+|suppos\w+|rumou?r\w*|purported\w*|so-called|proponents?|said to)\b",
    re.IGNORECASE,
)
# Nor do sentences that present the claim as a belief, a saying or something imagined: debunking
# pages open that way ("it is a common belief that ...", "the phrase '...' means", "it's fun to
# imagine that ...") before saying it is not so.
_FRAMING_RE = re.compile(
    r"\b(?:beliefs?|notions?|idea that|imagin\w*|trivia|idioms?|proverb\w*|adages?|the phrase|the saying|"
    r"legend has it|the story goes|you may have heard)\b",
    re.IGNORECASE,
)
# A short sentence that rejects the one before it: "But that's just not true.", "That is a myth."
_REJECTS_PREVIOUS = re.compile(
    r"^\W*(?:(?:but|however|yet|actually|in fact|in reality|sadly|unfortunately|no)\b\W*)*"
    r"(?:this|that|it|these|those|such claims?|the (?:claim|story|idea|rumou?r|theory|notion|report|assertion|myth|saying))\b",
    re.IGNORECASE,
)
_CONTRARY_TO_BELIEF = re.compile(r"\bcontrary to (?:(?:the )?(?:popular|common|widespread) )?beliefs?\b", re.IGNORECASE)
_NOT_SO = re.compile(r"(?:\bnot\b|n't\b|\bnever\b)\W+(?:\w+\W+){0,2}?(?:true|the case|correct|accurate|factual|happen(?:ed|s)?)\b", re.IGNORECASE)
# Page furniture that the sentence splitter returns as sentences: table rows and link lists.
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((?:https?://|/)[^)\s]*\)?")
_FOOTNOTE_MARK = re.compile(r"\s*\[(?:\d{1,3}|citation needed)\]", re.IGNORECASE)
_URL = re.compile(r"https?://\S+|\S+\.php\?\S+")
_INFLECTIONS = frozenset({"", "s", "es", "e", "ed", "d", "ing", "ies", "y", "n", "en"})
_PHYSICS_DEFYING_TOPICS = ("time machine", "perpetual motion", "telepathy", "faster than light")
MAX_PASSAGE_CHARS = 320
CLAIM_CHECK_CAVEAT = (
    "Passages are matched to the claim by rules about wording (key terms, negation, opposite words, differing "
    "numbers and years, hedging, open questions, beliefs and sayings, a next sentence that rejects it), not by understanding them. A passage that says the same thing "
    "in other words is missed. Read the quoted passages before relying on this."
)


def is_verification_request(text: str) -> bool:
    """True when the text asks to check a claim ("verify ...", "is it true that ...", "did ...?").

    Whole words only: the old substring test fired on "did" inside "candidate" and "was" in "wasp".
    """

    return bool(_VERIFICATION_RE.search(text or ""))


def extract_claim_text(query: str) -> str:
    """Strip "verify that ..." / "is it true that ..." scaffolding and return the claim itself."""

    text = clean_text(query)
    previous = None
    while previous != text:
        previous = text
        text = _CLAIM_PREFIX_RE.sub("", text, count=1).strip()
    return text.strip(" \t\"'?.!:")


def _words(text: str) -> list[str]:
    # "54,000" is one word, not "54" and "000".
    return re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|[a-z0-9]+(?:[.'-][a-z0-9]+)*", (text or "").lower().replace("’", "'"))


def _same_word(first: str, second: str) -> bool:
    """Equal words, or the same word with different endings (land / landed / landing)."""

    if first == second:
        return True
    shared = 0
    for a, b in zip(first, second):
        if a != b:
            break
        shared += 1
    rest = {first[shared:], second[shared:]}
    if shared < 4 and not (shared >= 3 and rest <= {"", "s"}):
        return False
    return rest <= _INFLECTIONS


def _claim_terms(claim: str) -> list[str]:
    terms = [word for word in _words(claim) if word not in _CLAIM_STOPWORDS and not _NEGATOR_RE.fullmatch(word)]
    return list(dict.fromkeys(term for term in terms if len(term) > 1))


def _polarity_cues(text: str) -> set[str]:
    """Negation and refutation signals in a text ("not", "debunked", "myth", ...)."""

    normalized = (text or "").replace("’", "'")
    cues = {label for label, pattern in _REFUTATION_CUES if pattern.search(normalized)}
    if _NEGATOR_RE.search(re.sub(r"\bno evidence\b", " ", normalized, flags=re.IGNORECASE)):
        cues.add("negation")
    return cues


def _is_page_furniture(sentence: str) -> bool:
    """A table row or a run of links rather than a sentence: what it seems to say is not stated."""

    return sentence.count("|") >= 3 or sum(len(found) for found in _URL.findall(sentence)) > 0.4 * len(sentence)


def _sentences(text: str) -> list[str]:
    """The sentences of a page's text, with link targets and footnote marks ("[1][2]") taken out and
    table rows and link lists left out."""

    prose = _FOOTNOTE_MARK.sub("", _MARKDOWN_LINK.sub(r"\1", text or ""))
    parts = (part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", clean_text(prose)))
    return [part for part in parts if part and not _is_page_furniture(part)]


@dataclass
class ClaimEvidence:
    """One source's best passage about the claim being checked, and what it says about it."""

    stance: str  # "supports", "contradicts" or "mentions"
    passage: str
    url: str
    title: str
    source: str
    trust_label: str = "Low"
    coverage: float = 0.0
    reason: str = ""  # why the passage was classed this way, in plain words
    retrieved_at: str = ""  # when the page was fetched
    published: str = ""  # the date the page gives for itself, when it gives one
    # What a model said when asked to read the passage too: "agrees", "disagrees", "unavailable",
    # "not asked" (over the limit), or "" when no model was asked.
    second_opinion: str = ""
    rule_stance: str = ""  # what the wording rules said, where the second reading overruled them

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# A passage that hedges does not state the claim; it only raises it.
_HEDGE_RE = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|maybe|suggests?|suggested|thought to|appears? to|seems? to|"
    r"likely|unlikely|probably|potentially|reportedly|allegedly|unconfirmed|preliminary|is said to|are said to)\b",
    re.IGNORECASE,
)
# Nor does one that says the matter is open ("it is unclear whether ...", "... has long been debated").
_UNSETTLED_RE = re.compile(
    r"\bwhether\b|\bopen question\b|\bremains to be seen\b|\bno consensus\b|\bjury is still out\b"
    r"|\bnot (?:yet )?(?:known|clear|certain|settled|established)\b"
    r"|\b(?:is|are|was|were|remains?|remained|still|been|long)\s+(?:(?:hotly|widely|much|still|long|largely)\s+)?"
    r"(?:unclear|uncertain|unknown|unresolved|unproven|unverified|inconclusive|disputed|debated|contested)\b",
    re.IGNORECASE,
)
# Words that say the opposite of each other, as families of forms: regular endings are matched by
# _same_word, irregular ones ("rose", "fell") have to be listed. A passage using the opposite word
# about the same things contradicts the claim even though nothing in it is negated. Words with
# several everyday meanings ("first"/"last", "up"/"down", "more"/"less") are left out on purpose.
_OPPOSITES = [
    ("rise rose risen rising", "fall fell fallen falling"),
    ("increase increasing", "decrease decreasing"),
    ("grow grew grown growing growth expand expanded", "shrink shrank shrunk shrinking decline declining contract contracted"),
    ("win won winning victory", "lose lost losing defeat"),
    ("upheld uphold", "overturned overturn"),
    ("approved accepted", "rejected"),
    ("allowed permitted legal", "banned prohibited forbidden illegal"),
    ("safe", "unsafe dangerous"),
    ("alive", "dead"),
    ("open opened", "closed shut"),
    ("higher highest", "lower lowest"),
    ("gain gained profit", "loss"),
    ("success succeeded passed", "failure failed"),
    ("guilty convicted", "innocent acquitted"),
    ("largest biggest", "smallest"),
    ("best", "worst"),
    ("oldest", "youngest newest"),
    ("hot", "cold"),
    ("present included", "absent excluded"),
    ("improved strengthened", "worsened weakened"),
    ("faster", "slower"),
    ("longer", "shorter"),
    ("north", "south"),
    ("east", "west"),
    ("majority", "minority"),
    ("supported supports", "opposed opposes"),
    ("confirmed", "denied"),
]
_OPPOSITE_OF: dict[str, set[str]] = {}
for _first, _second in _OPPOSITES:
    for _word in _first.split():
        _OPPOSITE_OF.setdefault(_word, set()).update(_second.split())
    for _word in _second.split():
        _OPPOSITE_OF.setdefault(_word, set()).update(_first.split())
_NEGATING_PREFIXES = ("un", "in", "im", "il", "ir", "dis", "non")
# Things that happen once: a different year for one of these is a contradiction, while a
# different year for something that recurs ("won the cup in 2019") is just another occasion.
_ONE_TIME_EVENTS = re.compile(
    r"\b(?:born|died|founded|established|opened|invented|discovered|launched|released|built|constructed|completed|"
    r"published|signed|created|incorporated|inaugurated|introduced|assassinated|abolished|patented)\b",
    re.IGNORECASE,
)
# Independent clauses. "Berlin is the capital of Germany, while Paris is the capital of France"
# contains every word of "Paris is the capital of Germany" without saying it.
_CLAUSE_SPLIT = re.compile(r";|,\s+(?:while|whereas|but|although|though|and|yet)\s+|\s+(?:whereas|while)\s+", re.IGNORECASE)
# What a sentence sets aside as the wrong alternative: "Canberra, not Sydney, is the capital".
_CONTRAST_RE = re.compile(
    r",\s*(?:and\s+|but\s+)?not\s+(?P<aside>[^,;]+?)\s*(?:,|$)"
    r"|\bnot\s+(?P<first>[^,;]+?),?\s+but\s+(?:rather\s+)?"
    r"|,?\s*\b(?:rather than|instead of|as opposed to|unlike)\s+(?P<other>[^,;]+?)\s*(?:,|$)",
    re.IGNORECASE,
)
# A later clause that refers back to the one before it: "..., but that has been debunked".
_REFERS_BACK = re.compile(
    r"\s*(?:this|that|it|which|these|those|such|both|the (?:claim|story|idea|rumou?r|theory|notion|report|assertion|myth))\b",
    re.IGNORECASE,
)
_UNIT_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_MULTIPLIER_WORDS = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000, "trillion": 1_000_000_000_000}
# "one" is often not a count: "no one", "one of the", "the one that".
_NOT_A_COUNT_BEFORE_ONE = frozenset("no any some every each which this that another the".split())
_NOT_A_COUNT_AFTER_ONE = frozenset("of who that which another".split())
# A four-digit number followed by one of these is an amount, not a year ("2000 metres").
_MEASURE_WORDS = frozenset(
    """metres meters metre meter km kilometres kilometers miles feet people employees workers staff spectators seats
    students members residents inhabitants dollars euros pounds percent kg kilograms tonnes tons hours days weeks
    months years copies votes words pages units items times species cases deaths homes houses vehicles cars""".split()
)
_QUANTITY_TOKEN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?|[a-z]+(?:-[a-z]+)*")
QUANTITY_TOLERANCE = 0.01  # figures within 1% of each other are the same figure, rounded differently


def _small_number(token: str) -> int | None:
    """The value of "five", "twenty" or "twenty-five"."""

    if token in _UNIT_WORDS:
        return _UNIT_WORDS[token]
    if token in _TENS_WORDS:
        return _TENS_WORDS[token]
    head, _, tail = token.partition("-")
    if head in _TENS_WORDS and 0 < _UNIT_WORDS.get(tail, 0) < 10:
        return _TENS_WORDS[head] + _UNIT_WORDS[tail]
    return None


def _is_number_term(term: str) -> bool:
    return bool(re.fullmatch(r"[\d.,]+", term)) or term in _MULTIPLIER_WORDS or _small_number(term) is not None


def _numbers(text: str) -> tuple[set[float], set[str]]:
    """(amounts, years) stated in a text.

    "five", "5" and "5.0" are the same amount, and so are "9.5 million" and "9,500,000". A
    four-digit number from 1000 to 2199 without a thousands separator is a year, unless a unit
    or "million" follows it.
    """

    amounts: set[float] = set()
    years: set[str] = set()
    tokens = [token.rstrip(",") for token in _QUANTITY_TOKEN.findall((text or "").lower())]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        value: float | None = None
        if token[:1].isdigit():
            plain = token.replace(",", "")
            if (
                "," not in token
                and re.fullmatch(r"(?:1[0-9]|20|21)\d{2}", plain)
                and following not in _MULTIPLIER_WORDS
                and following not in _MEASURE_WORDS
            ):
                years.add(plain)
                index += 1
                continue
            value = float(plain)
        elif (small := _small_number(token)) is not None:
            previous = tokens[index - 1] if index else ""
            if (
                token == "one"
                and following not in _MULTIPLIER_WORDS
                and (previous in _NOT_A_COUNT_BEFORE_ONE or following in _NOT_A_COUNT_AFTER_ONE)
            ):
                index += 1
                continue
            value = float(small)
            if token in _TENS_WORDS and 0 < _UNIT_WORDS.get(following, 0) < 10:  # "twenty five"
                value += _UNIT_WORDS[following]
                index += 1
        elif token in {"a", "an"} and following in _MULTIPLIER_WORDS:
            value = 1.0
        if value is None:
            index += 1
            continue
        index += 1
        while index < len(tokens) and tokens[index] in _MULTIPLIER_WORDS:
            value *= _MULTIPLIER_WORDS[tokens[index]]
            index += 1
        amounts.add(value)
    return amounts, years


_COMPOUND_NUMBER = re.compile(r"\b([a-z]+)-[a-z]+\b")


def _compound_amounts(text: str) -> set[float]:
    found = set()
    for head in _COMPOUND_NUMBER.findall((text or "").lower()):
        value = _small_number(head)
        if value is not None:
            found.add(float(value))
    return found


def _same_amount(first: float, second: float) -> bool:
    return abs(first - second) <= QUANTITY_TOLERANCE * max(abs(first), abs(second))


def _share_an_amount(first: set[float], second: set[float]) -> bool:
    return any(_same_amount(a, b) for a in first for b in second)


@lru_cache(maxsize=4096)
def _opposites_for(word: str) -> frozenset[str]:
    found: set[str] = set()
    for known, opposites in _OPPOSITE_OF.items():
        if _same_word(word, known):
            found |= opposites
    return frozenset(found)


def _is_opposite(claim_word: str, passage_word: str) -> bool:
    if any(_same_word(passage_word, opposite) for opposite in _opposites_for(claim_word)):
        return True
    longer, shorter = (claim_word, passage_word) if len(claim_word) > len(passage_word) else (passage_word, claim_word)
    return len(shorter) >= 4 and any(longer == prefix + shorter for prefix in _NEGATING_PREFIXES)


def _align(terms: list[str] | tuple[str, ...], clause: str) -> tuple[set[str], tuple[str, str] | None]:
    """The claim's key terms that a clause covers, and the first it covers by its opposite, as
    (claim word, passage word).

    A number in the claim is covered by any number in the clause, and a word by its opposite:
    such a clause is about the same thing even when it says something different.
    """

    words = _words(clause)
    amounts, years = _numbers(clause)
    covered: set[str] = set()
    opposite: tuple[str, str] | None = None
    for term in terms:
        if any(_same_word(term, word) for word in words):
            covered.add(term)
        elif _is_number_term(term) and (amounts or years):
            covered.add(term)
        else:
            match = next((word for word in words if _is_opposite(term, word)), None)
            if match is not None:
                covered.add(term)
                opposite = opposite or (term, match)
    return covered, opposite


@dataclass(frozen=True)
class _ClaimProfile:
    """What a passage has to cover to count as addressing a claim."""

    terms: tuple[str, ...]
    needed: int
    required: frozenset[str]


def _profile(claim: str) -> _ClaimProfile:
    """Every key term for claims of up to five; four in five for longer ones, which leaves room
    for one reworded modifier.

    Whatever the length, the first and last key terms (usually what the claim is about and what
    it says of it), names and numbers must be covered: a passage about someone or something else
    shares most of the claim's words without being about the claim.
    """

    terms = _claim_terms(claim)
    needed = len(terms) if len(terms) <= 5 else math.ceil(0.8 * len(terms))
    required = {terms[0], terms[-1]} if terms else set()
    tokens = re.findall(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*", (claim or "").replace("’", "'"))
    for position, token in enumerate(tokens):
        term = token.lower()
        if term in terms and ((position > 0 and token[0].isupper()) or _is_number_term(term)):
            required.add(term)
    return _ClaimProfile(tuple(terms), needed, frozenset(required))


def _set_aside(text: str, terms: list[str] | tuple[str, ...]) -> tuple[str, bool]:
    """Remove what a sentence sets aside as the wrong alternative ("Canberra, not Sydney, is ...").

    Returns the remaining text, and whether what was set aside is the claim's own version (then the
    sentence rejects the claim); otherwise its "not" is about something else and says nothing
    against the claim.
    """

    rejected = False
    asides: list[str] = []

    def drop(match: re.Match[str]) -> str:
        asides.append(match.group("aside") or match.group("first") or match.group("other") or "")
        return ", " if match.group("first") is None and match.group(0).rstrip().endswith(",") else " "

    remaining = re.sub(r"\s+", " ", _CONTRAST_RE.sub(drop, text)).strip()
    remaining_words = _words(remaining)
    for aside in asides:
        content = [word for word in _words(aside) if word not in _CLAIM_STOPWORDS]
        # Only the claim's terms that the rest of the sentence does not also use: in
        # "324 metres, not 300 metres" the unit is shared and only the figure is set aside.
        own = [
            word
            for word in content
            if any(_same_word(term, word) for term in terms) and not any(_same_word(word, other) for other in remaining_words)
        ]
        if own and len(own) * 2 >= len(content):
            rejected = True
    return remaining, rejected


_REFUTATION_WORDING = {
    "false": "calls it false",
    "myth": "calls it a myth",
    "hoax": "calls it a hoax",
    "debunk": "says it has been debunked",
    "fake": "calls it fake",
    "baseless": "says there is no evidence for it",
    "misinformation": "calls it misinformation",
    "conspiracy": "calls it a conspiracy theory",
    "pseudoscience": "calls it pseudoscience",
    "misconception": "calls it a misconception",
    "legend": "calls it an urban legend or an old wives' tale",
}


def _figures(values: set[float]) -> str:
    return ", ".join(f"{value:,.10g}" for value in sorted(values))


def _judge(sentence: str, claim_cues: set[str], claim_words: set[str], claim: str = "") -> tuple[str, str]:
    """(stance, why) for one passage that addresses the claim."""

    if sentence.rstrip().endswith("?"):
        return "mentions", "It asks the question; it does not answer it."
    terms = _claim_terms(claim) if claim else []
    text, rejected = _set_aside(sentence, terms) if terms else (sentence, False)
    lowered_claim = (claim or "").lower()
    unsettled = [found.strip() for found in _UNSETTLED_RE.findall(text) if found.lower() not in lowered_claim]
    if unsettled:
        return "mentions", f'It says the matter is open ("{unsettled[0]}").'
    sentence_cues = _polarity_cues(text) | ({"negation"} if rejected else set())
    # Signals the claim and the passage share cancel out: for the claim "the landing was a hoax",
    # "hoax" in a passage is the claim's own wording, while an extra "debunked" refutes it.
    extra_in_claim = claim_cues - sentence_cues
    extra_in_passage = sentence_cues - claim_cues
    negated = bool(extra_in_claim) != bool(extra_in_passage)
    # "is a myth", "has been debunked": said outright, whoever the passage attributes the claim to.
    refutations = sorted(extra_in_passage - {"negation"}) if negated else []
    attributions = [
        word for word in _ATTRIBUTION_RE.findall(text) if not any(_same_word(word.lower(), claim_word) for claim_word in claim_words)
    ]
    hedges = [hedge for hedge in _HEDGE_RE.findall(text) if hedge.lower() not in lowered_claim]
    framings = _framings(text, claim_words)
    second_hand = (
        f'it reports what others say ("{attributions[0]}") without confirming it.'
        if attributions
        else f'it presents the claim as a belief, a saying or something imagined ("{framings[0]}") without stating it.'
        if framings
        else f'it is tentative ("{hedges[0]}").'
        if hedges
        else ""
    )
    if terms:
        _covered, opposite = _align(terms, text)
        claim_amounts, claim_years = _numbers(claim)
        passage_amounts, passage_years = _numbers(text)
        other_amount = bool(
            claim_amounts and passage_amounts and not _share_an_amount(claim_amounts, passage_amounts | _compound_amounts(text))
        )
        other_year = bool(claim_years and passage_years and not (claim_years & passage_years))
        if opposite or other_amount or (other_year and _ONE_TIME_EVENTS.search(claim)):
            if second_hand:
                return "mentions", f"It says something different, but {second_hand}"
            if negated and opposite and not (other_amount or other_year):
                # "did not fall" about a claim that it rose says the same as the claim.
                return "supports", f'It denies the opposite ("{opposite[1]}"), which is what the claim says.'
            if other_amount:
                return "contradicts", f"It gives a different figure ({_figures(passage_amounts)}; the claim has {_figures(claim_amounts)})."
            if other_year:
                return "contradicts", f"It gives a different year ({', '.join(sorted(passage_years))}; the claim has {', '.join(sorted(claim_years))})."
            assert opposite is not None
            return "contradicts", f'It uses the opposite word ("{opposite[1]}" where the claim has "{opposite[0]}").'
        if other_year:
            # The same thing on another occasion settles nothing.
            return "mentions", f"It is about another year ({', '.join(sorted(passage_years))}), not {', '.join(sorted(claim_years))}."
    if refutations:
        return "contradicts", "It " + " and ".join(_REFUTATION_WORDING.get(cue, f"rejects it ({cue})") for cue in refutations) + "."
    if second_hand:
        # "Critics claim it never happened" and "it might not happen" settle nothing either way.
        return "mentions", second_hand[0].upper() + second_hand[1:]
    if negated:
        if rejected:
            return "contradicts", "It sets the claim's version aside as the wrong one."
        if extra_in_claim:
            return "contradicts", "The claim says it is not so; the passage states that it is."
        return "contradicts", "It negates what the claim says."
    if claim_cues:
        return "supports", "It makes the same negative statement as the claim."
    return "supports", "It states the claim: the key terms are there with no negation, hedge or attribution."


def _framings(text: str, claim_words: set[str]) -> list[str]:
    """Words that present the claim as a belief, a saying or something imagined, other than the claim's own."""

    found = []
    for frame in _FRAMING_RE.findall(_CONTRARY_TO_BELIEF.sub(" ", text or "")):
        content = [word for word in _words(frame) if word not in _CLAIM_STOPWORDS]
        if not any(_same_word(word, claim_word) for word in content for claim_word in claim_words):
            found.append(frame)
    return found


def _passage_stance(sentence: str, claim_cues: set[str], claim_words: set[str], claim: str = "") -> str:
    return _judge(sentence, claim_cues, claim_words, claim)[0]


def _rejects_previous(sentence: str, profile: "_ClaimProfile") -> bool:
    """Whether a sentence rejects the one before it without restating it ("But that's just not true.")."""

    normalized = (sentence or "").replace("’", "'")
    if len(_words(normalized)) > 12 or not _REJECTS_PREVIOUS.match(normalized) or _addressing_clause(profile, normalized) is not None:
        return False
    cues = _polarity_cues(normalized)
    return bool(cues - {"negation"}) or ("negation" in cues and bool(_NOT_SO.search(normalized)))


def _judge_in_place(
    profile: "_ClaimProfile", sentences: list[str], position: int, claim_cues: set[str], claim_words: set[str], claim: str
) -> tuple[str, str, str, int] | None:
    """(stance, why, passage, key terms covered) for the sentence at position, or None when it does not
    address the claim. A supporting sentence that the next one rejects contradicts the claim, and the
    passage then includes both."""

    sentence = sentences[position]
    found = _addressing_clause(profile, sentence)
    if found is None:
        return None
    clause, matched = found
    stance, why = _judge(_judged_text(clause, sentence), claim_cues, claim_words, claim)
    framings = _framings(sentence, claim_words) if stance == "supports" else []
    if framings:
        # The framing may sit in another clause: "Conversational and proverbial; used for ...".
        return "mentions", f'It presents the claim as a belief, a saying or something imagined ("{framings[0]}") without stating it.', sentence, matched
    following = sentences[position + 1] if position + 1 < len(sentences) else ""
    if stance == "supports" and following and _rejects_previous(following, profile):
        return "contradicts", f'The next sentence rejects it ("{following}").', f"{sentence} {following}", matched
    return stance, why, sentence, matched


def _addressing_clause(profile: _ClaimProfile, sentence: str) -> tuple[str, int] | None:
    """The clause of a sentence that addresses the claim, with how many key terms it covers.

    None when no single clause does. That includes the claim's words being spread over
    independent clauses, which means the sentence relates them differently from the claim.
    """

    clauses = [part.strip() for part in _CLAUSE_SPLIT.split(sentence) if part and part.strip()] or [sentence]
    aligned = [(clause, _align(profile.terms, clause)[0]) for clause in clauses]
    best: tuple[str, set[str]] | None = None
    for clause, covered in aligned:
        if len(covered) >= profile.needed and profile.required <= covered and (best is None or len(covered) > len(best[1])):
            best = (clause, covered)
    if best is None:
        return None
    missing = set(profile.terms) - best[1]
    if missing and any(missing & covered for clause, covered in aligned if clause is not best[0]):
        return None
    return best[0], len(best[1])


def _judged_text(clause: str, sentence: str) -> str:
    """The clause that addresses the claim, or the whole sentence when a later clause refers back
    to it with a refutation ("..., but that has been debunked")."""

    if clause == sentence:
        return sentence
    for part in _CLAUSE_SPLIT.split(sentence):
        part = (part or "").strip()
        if part and part != clause and _REFERS_BACK.match(part) and _polarity_cues(part) - _polarity_cues(clause) - {"negation"}:
            return sentence
    return clause


def stance_with_reason(claim: str, passage: str) -> tuple[str, str]:
    """What one passage says about a claim ("supports", "contradicts" or "mentions"), and why.

    "mentions" also covers a passage that does not address the claim at all.
    """

    profile = _profile(claim)
    if len(profile.terms) < 2:
        return "mentions", "The claim is too short to match passages against."
    claim_cues, claim_words = _polarity_cues(claim), set(_words(claim))
    first_mention: tuple[str, str] | None = None
    sentences = _sentences(passage)
    for position in range(len(sentences)):
        found = _judge_in_place(profile, sentences, position, claim_cues, claim_words, claim)
        if found is None:
            continue
        judged = (found[0], found[1])
        if judged[0] != "mentions":
            return judged
        first_mention = first_mention or judged
    return first_mention or ("mentions", "No sentence covers the claim's key terms.")


def stance_of(claim: str, passage: str) -> str:
    return stance_with_reason(claim, passage)[0]


def claim_evidence_breakdown(claim: str, sources: list[SourceRecord], embed: Embed | None = None) -> dict[str, Any]:
    """Per independent source, the passage that best addresses the claim, and what was left out.

    Returns {"evidence": [ClaimEvidence], "repeats": [{"url", "counted_as", "why"}], "unaddressed": [url],
    "compared_by_meaning": bool, "meaning_error": str}.

    A passage addresses the claim when one clause of a sentence covers its key terms (see
    _profile); a number in the claim is covered by a number, and a word by its opposite, so that a
    passage saying something different about the same thing is found and counted as contradicting.
    Sources on the same site count once, and the same passage copied across sites counts once:
    a rumour repeated on ten sites is one piece of evidence, not ten. With embed (see
    modules/retellings.py), a passage that tells an already counted one's story in other words,
    with nothing of its own, counts once too.
    """

    profile = _profile(claim)
    if len(profile.terms) < 2:
        return {"evidence": [], "repeats": [], "unaddressed": [source.url for source in sources], "compared_by_meaning": False, "meaning_error": ""}
    claim_cues = _polarity_cues(claim)
    claim_words = set(_words(claim))
    trust_rank = {"High": 2, "Medium": 1}

    def rank(item: ClaimEvidence) -> tuple[bool, float, int]:
        return (item.stance != "mentions", item.coverage, trust_rank.get(item.trust_label, 0))

    candidates: list[ClaimEvidence] = []
    unaddressed: list[str] = []
    for source in sources:
        best: ClaimEvidence | None = None
        sentences = _sentences(f"{source.excerpt} {source.snippet}")
        for position in range(len(sentences)):
            found = _judge_in_place(profile, sentences, position, claim_cues, claim_words, claim)
            if found is None:
                continue
            stance, reason, sentence, matched = found
            candidate = ClaimEvidence(
                stance=stance,
                passage=sentence if len(sentence) <= MAX_PASSAGE_CHARS else sentence[: MAX_PASSAGE_CHARS - 1].rstrip() + "…",
                url=source.url,
                title=source.title,
                source=source.source,
                trust_label=source.trust_label,
                coverage=round(matched / len(profile.terms), 2),
                reason=reason,
                retrieved_at=source.retrieved_at,
                published=source.published,
            )
            if best is None or rank(candidate) > rank(best):
                best = candidate
        if best is None:
            unaddressed.append(source.url)
        else:
            candidates.append(best)

    evidence: list[ClaimEvidence] = []
    repeats: list[dict[str, str]] = []
    counted_for_site: dict[str, ClaimEvidence] = {}
    seen_passages: list[tuple[set[str], ClaimEvidence]] = []
    for item in sorted(candidates, key=rank, reverse=True):
        site = (item.source or get_domain(item.url) or item.url).lower()
        if site in counted_for_site:
            repeats.append({"url": item.url, "counted_as": counted_for_site[site].url, "why": "same site"})
            continue
        # Near-copies count as the same passage: most of the words are the same.
        shingle = set(_words(item.passage))
        original = next((other for words, other in seen_passages if len(shingle & words) / max(len(shingle | words), 1) >= 0.8), None)
        if original is not None:
            counted_for_site[site] = original
            repeats.append({"url": item.url, "counted_as": original.url, "why": "same passage on another site"})
            continue
        counted_for_site[site] = item
        seen_passages.append((shingle, item))
        evidence.append(item)

    compared_by_meaning, meaning_error = False, ""
    if embed is not None:
        sites = [(item.source or get_domain(item.url) or item.url).lower() for item in evidence]
        try:
            folds = fold_retellings([item.passage for item in evidence], [item.stance for item in evidence], sites, embed)
            compared_by_meaning = True
        except Exception as exc:  # the embedding model is optional; say so rather than fail the check
            logger.info("Passages not compared by meaning: %s", exc)
            folds, meaning_error = [], "the embedding model did not answer"
        retold = {index for index, _original, _similarity in folds}
        for index, original, similarity in folds:
            repeats.append(
                {"url": evidence[index].url, "counted_as": evidence[original].url, "why": f"same story in other words, similarity {similarity:.2f},"}
            )
        evidence = [item for index, item in enumerate(evidence) if index not in retold]
    return {
        "evidence": evidence,
        "repeats": repeats,
        "unaddressed": unaddressed,
        "compared_by_meaning": compared_by_meaning,
        "meaning_error": meaning_error,
    }


def assess_claim_evidence(claim: str, sources: list[SourceRecord]) -> list[ClaimEvidence]:
    """The evidence part of claim_evidence_breakdown: one passage per independent source."""

    return claim_evidence_breakdown(claim, sources)["evidence"]


# A second reading by a model, for passages the rules count as supporting the claim. Counting a
# passage that does not support the claim is the worst mistake a claim check can make, and the
# rules make it with passages a reader would not be fooled by ("will close unless ...", "denied
# dumping ..."). Measured with the local 8B model (docs/benchmarks/stance.json): its second reading
# removes most of those. It is not asked about contradicting passages: there it overruled correct
# ones and caught nothing the rules had got wrong.
SECOND_OPINION_LIMIT = 6  # passages per claim check; each takes several seconds on a CPU


def second_opinion_prompt(claim: str, passage: str) -> str:
    """The question put to a model about one passage. The passage is web text, so lines aimed at a
    model are removed and the rest is fenced, as in every other research prompt."""

    cleaned, _removed = defuse_untrusted_text(passage)
    return (
        f"{untrusted_rule()}\n\n"
        f"Claim: {claim}\n"
        f"Passage:\n{fence_untrusted(cleaned, 'passage')}\n\n"
        "Does the passage state that the claim is true, state something that makes the claim false, or neither "
        "(it only reports what others say, asks, hedges, or is about another time or thing)?\n"
        "Answer with one word: SUPPORTS, CONTRADICTS or NEITHER.\nAnswer:"
    )


def read_opinion(answer: str) -> str:
    """"supports", "contradicts" or "mentions" from a model's one-word answer; "" when it is none of them."""

    word = re.sub(r"[^a-z]", " ", (answer or "").lower()).split()
    first = word[0] if word else ""
    if first.startswith("support"):
        return "supports"
    if first.startswith("contradict"):
        return "contradicts"
    if first.startswith("neither"):
        return "mentions"
    return ""


def apply_second_opinion(
    claim: str,
    evidence: list[ClaimEvidence],
    ask: Callable[[str], str],
    limit: int = SECOND_OPINION_LIMIT,
) -> dict[str, int]:
    """Ask a model to read each passage the rules counted as supporting the claim.

    The passage keeps counting only where the model also reads it as support; otherwise it is
    moved to "mentions" (and keeps what the rules said in rule_stance). The model can only take
    support away: it never turns a "mentions" into support, and it is not asked about passages
    that contradict the claim. Returns how many were asked, agreed, disagreed and could not be asked.
    """

    counts = {"asked": 0, "agreed": 0, "disagreed": 0, "unavailable": 0}
    model_down = False
    for item in evidence:
        if item.stance != "supports":
            continue
        if counts["asked"] >= limit:
            item.second_opinion = "not asked"
            continue
        opinion = ""
        if not model_down:
            counts["asked"] += 1
            try:
                opinion = read_opinion(ask(second_opinion_prompt(claim, item.passage)))
            except Exception as exc:
                logger.info("Second opinion unavailable: %s", exc)
                model_down = True  # do not wait for the same failure once per passage
        if not opinion:
            item.second_opinion = "unavailable"
            counts["unavailable"] += 1
        elif opinion == item.stance:
            item.second_opinion = "agrees"
            counts["agreed"] += 1
        else:
            read_as = "neither" if opinion == "mentions" else opinion
            item.second_opinion = "disagrees"
            item.rule_stance = item.stance
            item.reason = f"{item.reason} The model read it as {read_as.upper()}, so it is not counted."
            item.stance = "mentions"
            counts["disagreed"] += 1
    return counts


def _evidence_score(supporting: int, contradicting: int) -> float:
    """Rough 0-1 summary of how one-sided and how plentiful the evidence is. Not a probability."""

    total = supporting + contradicting
    if not total:
        return 0.0
    return round((max(supporting, contradicting) / total) * min(1.0, total / 4), 2)


def determine_verdict(
    query: str,
    sources: list[SourceRecord],
    claims: list[ClaimRecord],
    contradictions: list[ContradictionRecord],
    verify: bool | None = None,
    second_opinion: Callable[[str], str] | None = None,
    meaning: tuple[Embed | None, str] | None = None,
) -> dict[str, Any]:
    """Check the claim in a verification-style query against the retrieved passages.

    verify=None detects a verification request from the query text; pass True when the caller
    already stripped the "verify ..." command from it. second_opinion, when given, is asked to read
    each passage counted as supporting the claim (see apply_second_opinion). meaning is what
    modules.retellings.meaning_embedder returned: (embed, model name) to count a story retold in
    other words once, or (None, why it is not available); None leaves the comparison out unmentioned.
    """

    result: dict[str, Any] = {
        "verdict": "",
        "confidence": 0.0,
        "why": "",
        "supporting": [],
        "contradicting": [],
        "weak": [],
        "uncertainty": [],
        "claim": "",
        "evidence_strength": "",
        "evidence": [],
        "unaddressed": [],
        "repeats": [],
        "second_opinion": {},
    }
    if not (is_verification_request(query) if verify is None else verify):
        return result
    claim = extract_claim_text(query)
    if len(_claim_terms(claim)) < 2:
        return result  # nothing specific enough to match passages against

    embed, meaning_note = meaning if meaning is not None else (None, "")
    breakdown = claim_evidence_breakdown(claim, sources, embed=embed)
    evidence = breakdown["evidence"]
    opinions = apply_second_opinion(claim, evidence, second_opinion) if second_opinion is not None else {}
    supports = [item for item in evidence if item.stance == "supports"]
    contradicts = [item for item in evidence if item.stance == "contradicts"]
    mentions = [item for item in evidence if item.stance == "mentions"]
    solid_supports = [item for item in supports if item.trust_label in {"High", "Medium"}]
    solid_contradicts = [item for item in contradicts if item.trust_label in {"High", "Medium"}]

    if supports and contradicts:
        verdict, strength = "MIXED / CONFLICTING", "Conflicting"
        why = f"{len(supports)} source(s) contain a passage supporting the claim and {len(contradicts)} contain one contradicting it."
    elif supports:
        if len(solid_supports) >= 2:
            verdict, strength = "LIKELY TRUE", "Strong" if len(solid_supports) >= 3 else "Moderate"
            why = f"{len(supports)} independent sources contain a passage supporting the claim and none contradicts it."
        else:
            verdict, strength = "WEAKLY SUPPORTED", "Weak"
            why = (
                "Only one source contains a passage supporting the claim; it is not corroborated."
                if len(supports) == 1
                else "Passages support the claim, but fewer than two come from medium- or high-trust sources."
            )
    elif contradicts:
        if len(solid_contradicts) >= 2:
            verdict, strength = "LIKELY FALSE", "Strong" if len(solid_contradicts) >= 3 else "Moderate"
            why = f"{len(contradicts)} independent sources contain a passage contradicting the claim and none supports it."
        else:
            verdict, strength = "WEAKLY CONTRADICTED", "Weak"
            why = (
                "Only one source contains a passage contradicting the claim; it is not corroborated."
                if len(contradicts) == 1
                else "Passages contradict the claim, but fewer than two come from medium- or high-trust sources."
            )
    else:
        verdict, strength = "UNSUPPORTED", "None"
        if not sources:
            why = "No sources were retrieved, so the claim could not be checked."
        elif mentions:
            why = f"{len(mentions)} source(s) mention the claim, but none clearly affirms or denies it."
        else:
            why = f"None of the {len(sources)} retrieved source(s) contains a passage that addresses the claim."
        if sources:
            why += " That is missing evidence, not evidence that the claim is false."

    uncertainty: list[str] = []
    if len(sources) < 5:
        uncertainty.append(f"Only {len(sources)} source(s) were retrieved.")
    if mentions:
        uncertainty.append(f"{len(mentions)} source(s) mention the claim without clearly affirming or denying it.")
    if opinions.get("disagreed"):
        uncertainty.append(
            f"The model did not read {opinions['disagreed']} passage(s) as supporting the claim, although the wording rules did; those are not counted."
        )
    if opinions.get("unavailable"):
        uncertainty.append(
            f"The model could not be asked for a second reading of {opinions['unavailable']} passage(s); they are counted on the wording rules alone."
        )
    retold = [item for item in breakdown["repeats"] if item["why"].startswith("same story in other words")]
    copied = len(breakdown["repeats"]) - len(retold)
    if copied:
        uncertainty.append(f"{copied} source(s) repeat a site or passage already counted and were not counted again.")
    if retold:
        uncertainty.append(
            f"{len(retold)} source(s) say what a source already counted says, in other words and with nothing of their own, "
            "so each was counted once: one may be retelling the other. If they are independent reports after all, "
            "the evidence is stronger than shown."
        )
    same_side = max(len(supports), len(contradicts))
    if meaning is not None and not breakdown["compared_by_meaning"] and same_side >= 2:
        reason = breakdown["meaning_error"] or meaning_note
        uncertainty.append(
            f"Passages were not compared by meaning ({reason}), so a story retold in other words on several sites "
            "may have been counted more than once."
        )
    newest_for = max((item.published for item in supports if item.published), default="")
    newest_against = max((item.published for item in contradicts if item.published), default="")
    if newest_for and newest_against and newest_for[:10] != newest_against[:10]:
        newer, older = ("supporting", "contradicting") if newest_for > newest_against else ("contradicting", "supporting")
        uncertainty.append(
            f"The newest {newer} page is dated {max(newest_for, newest_against)[:10]}, later than the newest {older} page "
            f"({min(newest_for, newest_against)[:10]}); the facts may have changed in between."
        )
    undated = [item for item in supports + contradicts if not item.published]
    if undated and (supports or contradicts):
        uncertainty.append(f"{len(undated)} of the pages counted do not say when they were published.")
    if contradictions:
        uncertainty.append(f"{len(contradictions)} pair(s) of sources say opposite things about a related matter.")
    if any(topic in query.lower() for topic in _PHYSICS_DEFYING_TOPICS):
        uncertainty.append(
            "This topic conflicts with physics as currently understood; a supporting passage may describe fiction, speculation or theory."
        )

    result.update(
        {
            "verdict": verdict,
            "confidence": _evidence_score(len(supports), len(contradicts)),
            "why": why,
            "supporting": [item.url for item in supports[:3]],
            "contradicting": [item.url for item in contradicts[:3]],
            "weak": [source.url for source in sources if source.trust_label == "Low"][:3],
            "uncertainty": uncertainty,
            "claim": claim,
            "evidence_strength": strength,
            "evidence": evidence,
            "unaddressed": breakdown["unaddressed"],
            "repeats": breakdown["repeats"],
            "second_opinion": opinions,
            "compared_by_meaning": breakdown["compared_by_meaning"],
        }
    )
    return result


def classify_source_category(url: str, title: str, snippet: str) -> str:
    """Classify source into category based on URL and content."""
    domain = get_domain(url).lower()
    text = f"{title} {snippet}".lower()

    if any(gov in domain for gov in [".gov", ".gov.uk", ".gov.au"]):
        return "official/reference"
    if any(edu in domain for edu in [".edu", ".ac.uk", ".ac.au"]):
        return "academic/scientific"
    if any(org in domain for org in ["nih.gov", "who.int", "cdc.gov", "nasa.gov", "arxiv.org"]):
        return "official/reference"
    if "wikipedia.org" in domain:
        return "wiki/reference"
    if any(site in domain for site in ["github.com", "stackoverflow.com", "reddit.com", "quora.com"]):
        return "forum/community"
    if any(word in text for word in ["buy", "price", "shop", "advertisement", "sponsored"]):
        return "commercial/blog"
    if any(word in text for word in ["how to", "tutorial", "guide", "build", "make"]):
        return "forum/community"
    if len(snippet) < 50 or "lorem ipsum" in text:
        return "suspicious/SEO/spam"
    return "news"


NEGATION_RE = re.compile(r"\b(no|not|never|without|lacks|lack|unsupported|unverified|unknown|false)\b", re.I)
AFFIRMATION_RE = re.compile(r"\b(proven|confirmed|verified|established|shows|demonstrates|is|are|was|were)\b", re.I)


@dataclass
class ResearchRequest:
    """User-configurable knobs for one Reality-First research run."""

    query: str
    depth: str = "Standard"
    max_sources: int = 25
    follow_links: bool = True
    save_to_memory: bool = True
    show_weak_matches: bool = True
    use_ai_summary: bool = True
    save_report: bool = True
    # True/False forces the claim check on or off; None detects a "verify ..." style query.
    verify_claim: bool | None = None
    # Have the model read each passage counted as supporting the claim; it counts only if both agree.
    second_opinion: bool = True
    # Count a story told in other words on several sites once (modules/retellings.py).
    compare_meaning: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRecord:
    """Normalized source result with trust and relevance signals."""

    title: str
    url: str
    source: str
    source_type: str = "public_web"
    snippet: str = ""
    excerpt: str = ""
    match_strength: str = "Low"
    relevance_score: float = 0.0
    trust_score: float = 0.0
    trust_label: str = "Low"
    category: str = "unknown"
    trust_reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    fetched: bool = False
    timestamp: str = ""
    why_it_matters: str = ""
    matched_terms: list[str] = field(default_factory=list)
    retrieved_at: str = ""  # when the page was fetched
    published: str = ""  # the date the page gives for itself, when it gives one

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimRecord:
    """A factual-looking claim extracted from a source."""

    text: str
    source_url: str
    source_title: str
    claim_type: str = "general"
    requires_evidence: bool = False
    source_trust: float = 0.0
    evidence_strength: str = "Weak"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContradictionRecord:
    """A potential conflict between two extracted claims."""

    claim_a: str
    claim_b: str
    source_a: str
    source_b: str
    severity: str = "Weak"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchReport:
    """Complete source-grounded report produced by the agent."""

    query: str
    timestamp: str
    request: dict[str, Any]
    summary: str
    final_answer: str
    sources: list[SourceRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    contradictions: list[ContradictionRecord] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    saved_paths: dict[str, str] = field(default_factory=dict)
    memory_saved: bool = False
    verdict: str = ""
    # Rough 0-1 evidence score (how one-sided and plentiful the passages are), not a probability.
    verdict_confidence: float = 0.0
    verdict_why: str = ""
    strongest_supporting_sources: list[str] = field(default_factory=list)
    strongest_contradicting_sources: list[str] = field(default_factory=list)
    weak_irrelevant_sources: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)
    verdict_claim: str = ""
    verdict_evidence: str = ""  # Strong / Moderate / Weak / Conflicting / None
    claim_evidence: list[ClaimEvidence] = field(default_factory=list)
    unaddressed_sources: list[str] = field(default_factory=list)  # retrieved, but no passage addresses the claim
    repeated_sources: list[dict[str, str]] = field(default_factory=list)  # same site or same passage as one counted
    second_opinion: dict[str, int] = field(default_factory=dict)  # asked / agreed / disagreed / unavailable

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = [source.to_dict() for source in self.sources]
        payload["claims"] = [claim.to_dict() for claim in self.claims]
        payload["contradictions"] = [item.to_dict() for item in self.contradictions]
        return payload

    def to_markdown(self) -> str:
        lines = [
            f"# Reality-First Research Report: {self.query}",
            "",
            f"Timestamp: {self.timestamp}",
            "",
            "## Summary",
            "",
            self.summary or "No summary generated.",
            "",
            "## Final Answer",
            "",
            self.final_answer or self.summary or "No final answer generated.",
            "",
        ]
        if self.verdict:
            lines.extend(["## Claim Check", "", f"**{self.verdict}** (evidence: {self.verdict_evidence or 'not rated'})", ""])
            if self.verdict_claim:
                lines.extend([f'Claim checked: "{self.verdict_claim}"', ""])
            lines.extend([self.verdict_why, "", f"_{CLAIM_CHECK_CAVEAT}_", ""])
            for heading, stance in (
                ("Supporting passages", "supports"),
                ("Contradicting passages", "contradicts"),
                ("Mentions without a clear stance", "mentions"),
            ):
                items = [item for item in self.claim_evidence if item.stance == stance]
                if stance == "mentions" and not items:
                    continue
                lines.extend([f"### {heading}", ""])
                if not items:
                    lines.append("None found.")
                for item in items[:5]:
                    label = item.title or item.source or item.url
                    dates = "".join(
                        f"; {word} {value[:10]}" for word, value in (("retrieved", item.retrieved_at), ("published", item.published)) if value
                    )
                    lines.append(f'- "{item.passage}" - [{label}]({item.url}) (trust: {item.trust_label}{dates})')
                    if item.reason:
                        lines.append(f"  - Why: {item.reason}")
                    if item.second_opinion == "agrees":
                        lines.append("  - The model, asked to read the passage too, agreed.")
                lines.append("")
            if self.second_opinion.get("asked"):
                lines.extend(
                    [
                        f"The model was asked to read {self.second_opinion['asked']} supporting passage(s) as well: it agreed on "
                        f"{self.second_opinion.get('agreed', 0)} and disagreed on {self.second_opinion.get('disagreed', 0)}. "
                        "A passage counts as support only where both agree.",
                        "",
                    ]
                )
            if self.unaddressed_sources:
                lines.extend(["### Sources that did not address the claim", ""])
                lines.extend(f"- {url}" for url in self.unaddressed_sources[:10])
                if len(self.unaddressed_sources) > 10:
                    lines.append(f"- and {len(self.unaddressed_sources) - 10} more")
                lines.append("")
            if self.repeated_sources:
                lines.extend(["### Repeats counted once", ""])
                lines.extend(f"- {item['url']} ({item['why']} as {item['counted_as']})" for item in self.repeated_sources[:10])
                lines.append("")
            if self.uncertainty_notes:
                lines.extend(["### Uncertainty Notes", ""])
                for note in self.uncertainty_notes:
                    lines.append(f"- {note}")
                lines.append("")
        lines.extend([
            "## Best Sources",
            "",
        ])
        if not self.sources:
            lines.append("No sources were found.")
        for index, source in enumerate(self.sources[:20], 1):
            lines.extend(
                [
                    f"{index}. [{source.title or source.url}]({source.url})",
                    f"   - Source: {source.source}",
                    f"   - Category: {source.category}",
                    f"   - Type: {source.source_type}",
                    f"   - Match: {source.match_strength}",
                    f"   - Trust: {source.trust_label} ({source.trust_score})",
                    f"   - Trust reasons: {', '.join(source.trust_reasons) if source.trust_reasons else 'None'}",
                    f"   - Penalties: {', '.join(source.penalties) if source.penalties else 'None'}",
                    f"   - Why it matters: {source.why_it_matters}",
                    f"   - Snippet: {source.excerpt or source.snippet}",
                    "",
                ]
            )
        lines.extend(["## Extracted Claims", ""])
        if not self.claims:
            lines.append("No factual-looking claims were extracted.")
        for claim in self.claims[:30]:
            lines.append(f"- **{claim.evidence_strength}** [{claim.claim_type}] {claim.text}")
            lines.append(f"  Source: {claim.source_url}")
        lines.extend(["", "## Potential Contradictions", ""])
        if not self.contradictions:
            lines.append("No two sources were found saying opposite things about the same matter.")
        for item in self.contradictions[:20]:
            lines.append(f"- **{item.severity}:** {item.reason}")
            lines.append(f"  - A: {item.claim_a} ({item.source_a})")
            lines.append(f"  - B: {item.claim_b} ({item.source_b})")
        lines.extend(["", "## Search Coverage", "", "```json", json.dumps(self.coverage, indent=2, ensure_ascii=False), "```"])
        if self.errors:
            lines.extend(["", "## Errors / Limits", ""])
            lines.extend(f"- {error}" for error in self.errors)
        return "\n".join(lines).strip()


def ensure_report_dir() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def detect_reality_research_query(message: str) -> str:
    """Return the research query if a chat message asks for reality-first research."""

    bloodhound = detect_bloodhound_query(message)
    if bloodhound:
        return bloodhound
    text = clean_text(message)
    for pattern in RESEARCH_COMMAND_PATTERNS:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:")
    lowered = text.lower()
    if any(phrase in lowered for phrase in ("research this deeply", "verify this claim", "trace the sources", "find contradictions")):
        return text
    return ""


def _term_set(query: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[a-zA-Z0-9_@.-]{3,}", query or "")}


def _domain_trust_bonus(domain: str) -> float:
    lowered = (domain or "").lower()
    score = 0.0
    for hint, bonus in TRUSTED_DOMAIN_HINTS.items():
        if hint in lowered:
            score = max(score, bonus)
    return score


def _trust_label(score: float) -> str:
    if score >= 0.72:
        return "High"
    if score >= 0.48:
        return "Medium"
    return "Low"


def score_source_trust(source: dict[str, Any], query: str) -> SourceRecord:
    """Score one normalized Bloodhound result for research trust and relevance."""

    title = clean_text(source.get("title", ""))
    url = str(source.get("url", ""))
    domain = source.get("source") or get_domain(url)
    snippet = clean_text(source.get("snippet", ""))
    excerpt = clean_text(source.get("excerpt", ""))
    source_type = str(source.get("source_type") or "public_web")
    fetched = bool(source.get("fetched"))
    match_strength = str(source.get("match_strength") or "Low")
    raw_score = float(source.get("score") or 0.0)
    terms = _term_set(query)
    combined = f"{title} {snippet} {excerpt}".lower()
    matched = sorted(term for term in terms if term in combined)

    relevance = min(1.0, raw_score / 10.0)
    if match_strength == "High":
        relevance = max(relevance, 0.82)
    elif match_strength == "Medium":
        relevance = max(relevance, 0.58)
    elif matched:
        relevance = max(relevance, 0.34)

    trust = 0.22 + _domain_trust_bonus(domain)
    trust_reasons = []
    penalties = []

    if fetched:
        trust += 0.16
        trust_reasons.append("Page successfully fetched")
    if source_type == "public_web":
        trust += 0.08
        trust_reasons.append("Public web source")
    elif "onion" in source_type:
        trust -= 0.12
        penalties.append("Onion source (lower priority)")
    if match_strength == "High":
        trust += 0.16
        trust_reasons.append("High match strength")
    elif match_strength == "Medium":
        trust += 0.09
        trust_reasons.append("Medium match strength")
    if len(excerpt) > 300:
        trust += 0.08
        trust_reasons.append("Detailed excerpt available")
    if len(matched) >= 2:
        trust += 0.05
        trust_reasons.append("Multiple query terms matched")

    # Category-based adjustments
    category = classify_source_category(url, title, snippet)
    if category in {"official/reference", "academic/scientific"}:
        trust += 0.1
        trust_reasons.append(f"Trusted category: {category}")
    elif category == "commercial/blog":
        trust -= 0.05
        penalties.append("Commercial/blog source")
    elif category in {"suspicious/SEO/spam", "forum/community"}:
        trust -= 0.1
        penalties.append(f"Low-trust category: {category}")

    # Penalize SEO/spam indicators
    if len(snippet) < 50:
        trust -= 0.1
        penalties.append("Very short snippet")
    if "how to" in combined and "time machine" in query.lower():
        trust -= 0.2
        penalties.append("Speculative 'how to' content for impossible topic")

    trust = max(0.0, min(1.0, trust))

    return SourceRecord(
        title=title,
        url=url,
        source=domain,
        source_type=source_type,
        snippet=snippet,
        excerpt=excerpt,
        match_strength=match_strength,
        relevance_score=round(relevance, 3),
        trust_score=round(trust, 3),
        trust_label=_trust_label(trust),
        category=category,
        trust_reasons=trust_reasons,
        penalties=penalties,
        fetched=fetched,
        timestamp=str(source.get("timestamp") or ""),
        why_it_matters=clean_text(source.get("why_it_matters", "")),
        matched_terms=matched,
        retrieved_at=str(source.get("retrieved_at") or ""),
        published=str(source.get("published") or ""),
    )


def dedupe_sources(sources: list[SourceRecord]) -> list[SourceRecord]:
    """Collapse duplicate URLs while keeping the strongest record."""

    by_url: dict[str, SourceRecord] = {}
    for source in sources:
        key = re.sub(r"[#?].*$", "", source.url.rstrip("/").lower())
        if not key:
            key = f"{source.title.lower()}::{source.source.lower()}"
        current = by_url.get(key)
        if current is None or (source.trust_score + source.relevance_score) > (current.trust_score + current.relevance_score):
            by_url[key] = source
    return sorted(by_url.values(), key=lambda item: (item.match_strength == "High", item.trust_score, item.relevance_score), reverse=True)


def extract_claim_records(sources: list[SourceRecord], max_claims: int = 40) -> list[ClaimRecord]:
    """Extract factual-looking claims from source snippets/excerpts."""

    records: list[ClaimRecord] = []
    for source in sources:
        text = clean_text(f"{source.excerpt} {source.snippet}")
        if not text:
            continue
        for claim in extract_claims(text, max_claims=8):
            strength = source.trust_label if claim.requires_evidence else ("Medium" if source.trust_score >= 0.4 else "Weak")
            records.append(
                ClaimRecord(
                    text=claim.text,
                    source_url=source.url,
                    source_title=source.title,
                    claim_type=claim.claim_type,
                    requires_evidence=claim.requires_evidence,
                    source_trust=source.trust_score,
                    evidence_strength=strength,
                )
            )
            if len(records) >= max_claims:
                return records
    return records


def _is_firm(statement: str) -> bool:
    """A statement made outright: not a question, a report of what others say, a possibility or an open matter."""

    return not (
        statement.rstrip().endswith("?")
        or _HEDGE_RE.search(statement)
        or _ATTRIBUTION_RE.search(statement)
        or _UNSETTLED_RE.search(statement)
    )


def detect_claim_contradictions(claims: list[ClaimRecord]) -> list[ContradictionRecord]:
    """Pairs of statements from different sources where one says what the other denies.

    Uses the rules of the claim check, so both statements have to be about the same thing (one
    covers the other's key terms) and one has to negate it, use the opposite word, give a different
    figure or, for something that happens once, a different year. Sharing words is not enough, and
    the same event in two different years is two occasions, not a contradiction. Only statements
    made outright are compared: "it may have fallen" does not contradict "it rose". Statements
    that disagree in other words are missed.
    """

    contradictions: list[ContradictionRecord] = []
    term_sets = [set(_claim_terms(claim.text)) for claim in claims]
    firm = [_is_firm(claim.text) for claim in claims]
    for i, first in enumerate(claims):
        for j in range(i + 1, len(claims)):
            second = claims[j]
            if first.source_url == second.source_url or not (firm[i] and firm[j]) or len(term_sets[i] & term_sets[j]) < 2:
                continue
            stance, reason = stance_with_reason(first.text, second.text)
            if stance != "contradicts":
                stance, reason = stance_with_reason(second.text, first.text)
            if stance != "contradicts":
                continue
            severity = "Medium" if min(first.source_trust, second.source_trust) >= 0.48 else "Weak"
            contradictions.append(
                ContradictionRecord(
                    claim_a=first.text,
                    claim_b=second.text,
                    source_a=first.source_url,
                    source_b=second.source_url,
                    severity=severity,
                    reason=f"One source against the other: {reason[0].lower()}{reason[1:]}",
                )
            )
            if len(contradictions) >= 20:
                return contradictions
    return contradictions


def _local_summary(query: str, sources: list[SourceRecord], claims: list[ClaimRecord], contradictions: list[ContradictionRecord]) -> str:
    high = [source for source in sources if source.match_strength == "High"]
    medium = [source for source in sources if source.match_strength == "Medium"]
    high_trust = [source for source in sources if source.trust_label == "High"]
    parts = [
        f"Reality-first research found {len(sources)} ranked source(s) for {query!r}.",
        f"{len(high)} high-match and {len(medium)} medium-match source(s) were separated from weaker leads.",
        f"{len(claims)} factual-looking claim(s) were extracted; {len(contradictions)} potential contradiction(s) were detected.",
    ]
    if high_trust:
        parts.append(f"The strongest source lane includes {len(high_trust)} high-trust source(s).")
    if not sources:
        parts.append("No source-backed answer can be produced until search returns evidence.")
    return " ".join(parts)


def _build_ai_prompt(report: ResearchReport) -> str:
    source_blocks = []
    for index, source in enumerate(report.sources[:12], 1):
        source_blocks.append(
            f"[{index}] {source.title}\n"
            f"URL: {source.url}\n"
            f"Trust: {source.trust_label} ({source.trust_score})\n"
            f"Match: {source.match_strength}\n"
            f"Evidence: {source.excerpt or source.snippet}\n"
        )
    claim_blocks = "\n".join(f"- {claim.text} ({claim.source_url})" for claim in report.claims[:18])
    contradiction_blocks = "\n".join(f"- {item.reason}: {item.claim_a} / {item.claim_b}" for item in report.contradictions[:8])
    # Everything below the query was copied from web pages: take out lines aimed at the model
    # and fence the rest, so a page cannot give the model instructions.
    removed = 0
    fenced = []
    for label, body in (
        ("source evidence", chr(10).join(source_blocks)),
        ("extracted claims", claim_blocks or "No claims extracted."),
        ("potential contradictions", contradiction_blocks or "None detected."),
    ):
        pieces = []
        for piece in body.split(chr(10) * 2):
            text, count = defuse_untrusted_text(piece)
            removed += count
            pieces.append(text)
        fenced.append(fence_untrusted((chr(10) * 2).join(piece for piece in pieces if piece.strip()), label))
    return (
        "You are Cognitive Nexus Reality-First Research Agent. Use only the supplied sources and extracted claims. "
        "Do not invent sources, quotes, dates, or conclusions. Clearly separate confirmed findings from weak leads.\n\n"
        f"{untrusted_rule()}\n\n"
        f"Query: {report.query}\n\n"
        f"Source evidence:\n{fenced[0]}\n\n"
        f"Extracted claims:\n{fenced[1]}\n\n"
        f"Potential contradictions:\n{fenced[2]}\n"
        f"{removed_note(removed)}\n\n"
        "Write a concise report with: Direct answer, key findings, source trust notes, contradictions/uncertainty, and next steps."
    )


def save_report(report: ResearchReport) -> dict[str, str]:
    """Persist a report as JSON and Markdown."""

    ensure_report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify_query(report.query, 70)
    base = REPORT_DIR / f"{timestamp}_{slug}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    serializable = report.to_dict()
    serializable["saved_paths"] = {}
    atomic_write_text(json_path, json.dumps(serializable, indent=2, ensure_ascii=False))
    atomic_write_text(md_path, report.to_markdown())
    return {"json": str(json_path), "markdown": str(md_path)}


def add_report_to_memory(report: ResearchReport, research_module: Any | None = None) -> bool:
    """Store a compact report summary into the existing local knowledge base."""

    ensure_report_dir()
    try:
        append_line(
            MEMORY_INDEX_FILE,
            json.dumps(
                {
                    "timestamp": report.timestamp,
                    "query": report.query,
                    "summary": report.summary,
                    "sources": [source.url for source in report.sources[:12]],
                },
                ensure_ascii=False,
            ),
        )
        if research_module is not None:
            stored = research_module.add_document(
                f"reality_research:{report.query}:{report.timestamp}",
                f"Reality-First Research: {report.query}",
                report.to_markdown(),
                kind="research_report",
                meta={"query": report.query, "researched_at": report.timestamp},
            )
            return stored.get("status") == "success"
        return True
    except Exception as exc:
        logger.info("Could not add research report to memory: %s", exc)
        return False


def run_reality_research(
    request: ResearchRequest,
    settings: dict[str, Any] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    ai_callback: Callable[[str], str] | None = None,
    research_module: Any | None = None,
    search_runner: Callable[..., dict[str, Any]] | None = None,
    second_opinion_callback: Callable[[str], str] | None = None,
    meaning_embedder: Callable[[], tuple[Embed | None, str]] | None = None,
) -> ResearchReport:
    """Run the full Reality-First research workflow.

    second_opinion_callback answers one short prompt with a model; it is used to double-check the
    passages counted as supporting a claim (see apply_second_opinion). meaning_embedder is
    modules.retellings.meaning_embedder or a stand-in; it is only called for a claim check.
    """

    settings = settings or {}
    progress = progress_callback or (lambda _message: None)
    query = clean_text(request.query)
    errors: list[str] = []
    timestamp = datetime.now().isoformat()

    if not query:
        report = ResearchReport(
            query=query,
            timestamp=timestamp,
            request=request.to_dict(),
            summary="No research query was provided.",
            final_answer="No research query was provided.",
            errors=["Empty query."],
        )
        if request.save_report:
            report.saved_paths = save_report(report)
        return report

    progress("Planning research")
    config = default_bloodhound_config(
        {
            "enabled": True,
            "depth": request.depth,
            "max_results": int(request.max_sources),
            "follow_links": bool(request.follow_links),
            "enable_cache": bool(settings.get("bloodhound_enable_cache", settings.get("enable_search_cache", True))),
            "cache_ttl_hours": int(settings.get("search_cache_ttl_hours", 24)),
            "timeout_seconds": int(settings.get("bloodhound_timeout_seconds", settings.get("search_timeout_seconds", 20))),
            "enable_onion": bool(settings.get("bloodhound_enable_onion", settings.get("enable_onion_search", False))),
            "tor_socks_proxy": str(settings.get("tor_socks_proxy", "127.0.0.1:9050")),
            "save_history": False,
        }
    )

    runner = search_runner or run_bloodhound_search
    progress("Searching and extracting sources")
    try:
        payload = runner(query, config=config, progress_callback=progress)
    except TypeError:
        payload = runner(query)
    except Exception as exc:
        payload = {
            "ranked_results": [],
            "summary": "",
            "final_answer": "",
            "coverage": {"failed_sources": [str(exc)]},
            "errors": [str(exc)],
        }
    errors.extend(str(error) for error in payload.get("errors", []) if error)

    progress("Scoring source trust")
    sources = [score_source_trust(item, query) for item in payload.get("ranked_results", [])]
    sources = dedupe_sources(sources)
    if not request.show_weak_matches:
        sources = [source for source in sources if source.match_strength in {"High", "Medium"} or source.trust_label in {"High", "Medium"}]
    sources = sources[: max(1, int(request.max_sources))]

    progress("Extracting claims")
    claims = extract_claim_records(sources)
    progress("Checking contradictions")
    contradictions = detect_claim_contradictions(claims)

    checking = is_verification_request(query) if request.verify_claim is None else request.verify_claim
    asking = second_opinion_callback if request.second_opinion else None
    if asking is not None and checking:
        progress("Asking the model to read the evidence too")
    meaning = meaning_embedder() if checking and request.compare_meaning and meaning_embedder is not None else None
    verdict_data = determine_verdict(
        query, sources, claims, contradictions, verify=request.verify_claim, second_opinion=asking, meaning=meaning
    )
    if verdict_data["verdict"] and errors:
        # Don't imply the search was exhaustive when parts of it failed.
        verdict_data["uncertainty"].append(f"{len(errors)} search or page-fetch step(s) failed, so coverage is incomplete.")

    summary = _local_summary(query, sources, claims, contradictions)
    report = ResearchReport(
        query=query,
        timestamp=timestamp,
        request=request.to_dict(),
        summary=summary,
        final_answer=payload.get("final_answer") or summary,
        sources=sources,
        claims=claims,
        contradictions=contradictions,
        coverage=payload.get("coverage", {}),
        errors=errors,
        verdict=verdict_data["verdict"],
        verdict_confidence=verdict_data["confidence"],
        verdict_why=verdict_data["why"],
        strongest_supporting_sources=verdict_data["supporting"],
        strongest_contradicting_sources=verdict_data["contradicting"],
        weak_irrelevant_sources=verdict_data["weak"],
        uncertainty_notes=verdict_data["uncertainty"],
        verdict_claim=verdict_data["claim"],
        verdict_evidence=verdict_data["evidence_strength"],
        claim_evidence=verdict_data["evidence"],
        unaddressed_sources=verdict_data["unaddressed"],
        repeated_sources=verdict_data["repeats"],
        second_opinion=verdict_data["second_opinion"],
    )

    if request.use_ai_summary and ai_callback and sources:
        progress("Synthesizing grounded report")
        try:
            ai_answer = clean_text(ai_callback(_build_ai_prompt(report)))
            if ai_answer:
                report.final_answer = ai_answer
        except Exception as exc:
            report.errors.append(f"AI synthesis failed: {exc}")
    if report.verdict:
        # Also applies when synthesis fails or returns nothing, which used to drop the verdict.
        report.final_answer = (
            f"Claim check: {report.verdict} (evidence: {report.verdict_evidence.lower()}). {report.final_answer}"
        )

    if request.save_to_memory:
        progress("Saving to memory")
        report.memory_saved = add_report_to_memory(report, research_module)

    if request.save_report:
        progress("Saving report")
        report.saved_paths = save_report(report)

    return report
