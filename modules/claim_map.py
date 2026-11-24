"""Which page states each sentence of a research answer (item 028).

For every sentence of an answer that says something about the world, the passage of a retrieved
page that states it, with the page's title and address and when it was fetched. A sentence that no
page states is listed as such, so a reader can see which parts of an answer are not backed by what
was read. Sentences about the sources themselves ("The web results do not say ...") are kept apart.

Matching is done by rules, without a model, so it costs nothing and gives the same result every
time. A passage (one sentence of a page's title, snippet or text) states an answer sentence when:

* every number and every product or model code in the sentence is in the passage ("1962",
  "1,840", "BH-200", "four"): a sentence with a figure no page gives is never counted as stated;
* enough of the sentence's content words are in the passage (COVERAGE, after a crude stemming
  that treats "baked" and "bake" as the same word); and
* one does not deny what the other says ("not", "no", "never", "no longer", "without").

Measured on labelled sentences (tests/fixtures/claim_map_cases.json; docs/benchmarks/claim_map.json).
What the rules cannot see: a passage that uses the sentence's words but says something else about
them ("Tomas Reik served as mayor from 2010 to 2018" does not make him the current mayor), and a
sentence that says a page's fact in entirely different words.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

COVERAGE = 0.6  # share of a sentence's content words a passage must contain
WHOLE_PAGE_COVERAGE = 0.85  # the share needed when the words are spread over a page rather than in one passage
MIN_CONTENT_WORDS = 2  # a sentence with fewer is not a statement worth matching

_STOP = frozenset(
    """a about above after again against all also am an and any are as at be because been before being below between
    both but by can could did do does doing down during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just me more most my myself nor of off on once only or
    other our ours ourselves out over own same she should so some such than that the their theirs them themselves then
    there these they this those through to too under until up very was we were what when where which while who whom
    why will with would you your yours yourself yourselves s t can't one's per via""".split()
)
# "without" is not here: "works without extra drivers" does not deny "works".
_NEGATIONS = frozenset({"not", "no", "never", "none", "nothing", "cannot", "neither", "nor"})
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100",
    "thousand": "1000", "dozen": "12", "half": "0.5", "quarter": "0.25",
}  # fmt: skip
_TOKEN = re.compile(r"[A-Za-z]+-?\d[\w-]*|[A-Za-z]+(?:-[A-Za-z0-9]+)*|\d[\d,]*(?:\.\d+)?")  # codes (BH-200, H2) first
_CODE = re.compile(r"\b[A-Za-z]{1,6}-?\d[\w.-]*\b")  # BH-200, H2, K9, P3
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_LIST_MARK = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_LABEL = re.compile(r"^\s*(?:\d+[.)]\s*)?(?:direct answer|key findings|answer|summary|in short)\s*:\s*", re.IGNORECASE)
_SECTION_ONLY = re.compile(r"^\s*(?:\d+[.)]\s*)?[A-Z][\w ]{0,40}:\s*$")
_APP_NOTE = re.compile(r"^\s*(?:\[|note:|not found in the sources|names? not found|check these before)", re.IGNORECASE)
_URL = re.compile(r"https?://\S+")
# What the answer says about the sources, not about the world.
_ABOUT_SOURCES = re.compile(
    r"^(?:however,?\s+)?(?:the\s+)?(?:web\s+)?(?:search\s+)?(?:results|sources|pages|context|articles|research)\s+"
    r"(?:do(?:es)?\s+not|don't|doesn't|did\s+not|never)\s+(?:say|mention|state|contain|give|include|specify)"
    r"|^(?:this|that|the)\s+(?:information|figure|detail)\s+(?:is|was)\s+(?:mentioned|stated|given|found|from)"
    r"|^there\s+(?:is|was|are)\s+no\s+(?:information|mention|data|details?)",
    re.IGNORECASE,
)
# A lead-in that hands a claim to the sources; the claim after it is matched.
_ATTRIBUTION = re.compile(
    r"^(?:however,?\s+)?(?:they|the\s+(?:web\s+)?(?:results|sources|pages|research|context)"
    r"|(?:the\s+)?[\w' -]{0,40}?\b(?:changelog|docs|documentation|page|website|site|article|review|report|manual|notes|guide))\s+"
    r"(?:mention|mentions|say|says|state|states|suggest|suggests|indicate|indicates|show|shows|report|reports|note|notes)\s+(?:that\s+)?",
    re.IGNORECASE,
)
# Advice and next steps are not statements about the world.
_ADVICE = re.compile(r"^(?:check|ensure|consider|contact|verify|look|try|if you|you may|you might|you could|it is worth)\b", re.IGNORECASE)


@dataclass
class SentenceSource:
    sentence: str
    kind: str  # "stated" (a page states it), "not found" (no page does), "about the sources", "advice"
    title: str = ""
    url: str = ""
    retrieved_at: str = ""
    passage: str = ""
    coverage: float = 0.0
    missing: list[str] = field(default_factory=list)  # numbers or codes no page has, for "not found"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stem(word: str) -> str:
    word = word.lower()
    for suffix in ("ingly", "edly", "ings", "ing", "ied", "ies", "ed", "es", "ly", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            word = word[: -len(suffix)]
            if suffix in {"ied", "ies"}:
                word += "y"
            break
    return word.rstrip("e") if len(word) > 3 else word


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.replace("’", "'")) if token]


def _names(text: str) -> set[str]:
    """Capitalised words other than the first: names a page must contain for the sentence to be stated."""

    words = _tokens(text)
    return {_stem(word.lower()) for word in words[1:] if word[:1].isupper() and word.lower() not in _STOP and not _CODE.fullmatch(word) and word.lower() not in _NUMBER_WORDS}


def _figures(text: str) -> set[str]:
    """Numbers (digits or words) and product codes: what must be on a page for the sentence to be stated."""

    found: set[str] = set()
    for code in _CODE.findall(text):
        found.add(code.lower().replace("-", ""))
    for token in _tokens(text):
        low = token.lower()
        if low in _NUMBER_WORDS:
            found.add(_NUMBER_WORDS[low])
        elif token[0].isdigit():
            found.add(token.replace(",", "").rstrip("."))
    return found


def _content(text: str) -> set[str]:
    words: set[str] = set()
    for token in _tokens(text):
        low = token.lower()
        if low in _STOP or low in _NEGATIONS or low in _NUMBER_WORDS or token[0].isdigit() or _CODE.fullmatch(token):
            continue
        if len(low) < 2:
            continue
        words.add(_stem(low))
    return words


def _negated(text: str) -> bool:
    low = f" {text.lower()} "
    return any(f" {word} " in low for word in _NEGATIONS) or "n't " in low or " no longer " in low


def answer_sentences(answer: str) -> list[str]:
    """The sentences of an answer, without the app's notes, section labels, list marks and source lists."""

    sentences: list[str] = []
    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if not line or _APP_NOTE.match(line) or _SECTION_ONLY.match(line):
            continue
        line = _LIST_MARK.sub("", line)
        line = _LABEL.sub("", line)
        if not line or (_URL.search(line) and len(_URL.sub("", line).split()) <= 8):
            continue  # an entry of a source list
        for piece in _SENTENCE_END.split(line):
            piece = piece.strip()
            if piece:
                sentences.append(piece)
    return sentences


def _passages(source: dict[str, Any]) -> list[str]:
    pieces: list[str] = []
    for key in ("title", "snippet", "text", "excerpt", "content"):
        value = str(source.get(key) or "")
        if value:
            pieces.extend(part.strip() for part in _SENTENCE_END.split(value) if part.strip())
    return list(dict.fromkeys(pieces))


def _best_passage(claim: str, sources: list[dict[str, Any]]) -> tuple[int, str, float, set[str], bool]:
    """The best match for a claim: (index of the source or -1, passage, coverage, figures or names
    missing, whether it is stated).

    A passage is one sentence of a page; it states the claim with COVERAGE of its words. When no
    single passage does, the page as a whole is tried, with the higher WHOLE_PAGE_COVERAGE: an
    answer sentence often joins two of a page's sentences, or its title and its text ("to begin in
    spring", "will take five months"), but words found in different places of a page are weaker
    evidence than words found together.
    """

    words, negated = _content(claim), _negated(claim)
    required = _figures(claim) | _names(claim)

    def score(text: str) -> tuple[set[str], float]:
        present = _figures(text) | {_stem(word.lower()) for word in _tokens(text)}
        missing = required - present
        coverage = len(words & _content(text)) / max(1, len(words))
        if _negated(text) != negated:
            coverage *= 0.5  # one denies what the other says
        return missing, coverage

    best: tuple[int, str, float, set[str], bool] = (-1, "", 0.0, set(required), False)
    best_key: tuple[bool, int, float] = (False, -1_000, -1.0)
    for index, source in enumerate(sources):
        passages = _passages(source)
        candidates = [(passage, *score(passage), COVERAGE) for passage in passages]
        if passages:
            whole_missing, whole_coverage = score(" ".join(passages))
            # The page as a whole, shown by its passage that shares most words with the sentence.
            shown = max(passages, key=lambda passage: len(words & _content(passage)))
            candidates.append((shown, whole_missing, whole_coverage, WHOLE_PAGE_COVERAGE))
        for passage, missing, coverage, needed in candidates:
            stated = not missing and coverage >= needed
            key = (stated, -len(missing), coverage)
            if key > best_key:
                best_key, best = key, (index, passage, round(coverage, 2), missing, stated)
    return best


def map_sentences(answer: str, sources: Iterable[dict[str, Any]]) -> list[SentenceSource]:
    """Each sentence of `answer` with the page passage that states it, or why it has none.

    `sources` are dicts with title, url, snippet and/or text (or excerpt), and retrieved_at when known.
    """

    listed = [dict(source) for source in sources]
    mapped: list[SentenceSource] = []
    for sentence in answer_sentences(answer):
        if _ABOUT_SOURCES.search(sentence):
            mapped.append(SentenceSource(sentence, "about the sources"))
            continue
        claim = _ATTRIBUTION.sub("", sentence).strip() or sentence
        if _ADVICE.match(claim):
            mapped.append(SentenceSource(sentence, "advice"))
            continue
        if len(_content(claim)) < MIN_CONTENT_WORDS and not _figures(claim):
            mapped.append(SentenceSource(sentence, "about the sources"))
            continue
        index, passage, coverage, missing, stated = _best_passage(claim, listed)
        if index >= 0 and stated:
            source = listed[index]
            mapped.append(
                SentenceSource(
                    sentence, "stated", title=str(source.get("title") or ""), url=str(source.get("url") or ""),
                    retrieved_at=str(source.get("retrieved_at") or source.get("timestamp") or ""), passage=passage, coverage=coverage,
                )  # fmt: skip
            )
        else:
            mapped.append(SentenceSource(sentence, "not found", coverage=coverage, missing=sorted(missing)))
    return mapped


def sources_from(results: Iterable[dict[str, Any]], pages: Iterable[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Search results joined with the pages fetched for them (same address): what a sentence can be matched against."""

    fetched = {str(page.get("url") or ""): page for page in pages if page.get("url")}
    joined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        url = str(result.get("url") or "")
        page = fetched.get(url, {})
        joined.append(
            {
                "title": result.get("title") or page.get("title") or "",
                "url": url,
                "snippet": result.get("snippet") or "",
                "text": page.get("text") or page.get("excerpt") or "",
                "retrieved_at": page.get("retrieved_at") or result.get("retrieved_at") or "",
            }
        )
        seen.add(url)
    for url, page in fetched.items():
        if url not in seen:
            joined.append({"title": page.get("title") or "", "url": url, "text": page.get("text") or page.get("excerpt") or "", "retrieved_at": page.get("retrieved_at") or ""})
    return joined


def summary(mapped: list[SentenceSource]) -> dict[str, int]:
    counts = {"stated": 0, "not found": 0, "about the sources": 0, "advice": 0}
    for item in mapped:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def not_found_note(mapped: list[SentenceSource], limit: int = 3) -> str:
    """A line for under the answer when some of its statements are on none of the pages read; "" otherwise."""

    missing = [item.sentence for item in mapped if item.kind == "not found"]
    if not missing:
        return ""
    shown = "; ".join(f'"{text[:120]}"' for text in missing[:limit])
    more = f" and {len(missing) - limit} more" if len(missing) > limit else ""
    return f"\n\n[Not stated on any page read: {shown}{more}. Check before relying on it.]"
