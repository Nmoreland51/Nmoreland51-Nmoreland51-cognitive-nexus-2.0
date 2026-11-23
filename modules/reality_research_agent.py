"""Reality-First Research Agent orchestration.

This module turns the existing Bloodhound search, web research, grounding, and
memory pieces into one coherent source-grounded research workflow.
"""

from __future__ import annotations

import json
import logging
import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.reality_grounding.claim_validator import extract_claims
from modules.web_research import clean_text, get_domain, slugify_query
from search.bloodhound_search import (
    BloodhoundConfig,
    default_bloodhound_config,
    detect_bloodhound_query,
    run_bloodhound_search,
)


logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/research_reports")
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
    ]
]
# Sentences that report what others say ("some people believe ...") don't count as support.
_ATTRIBUTION_RE = re.compile(
    r"\b(?:believ\w+|claims?|claimed|claiming|alleg\w+|suppos\w+|rumou?r\w*|purported\w*|so-called|proponents?|said to)\b",
    re.IGNORECASE,
)
_INFLECTIONS = frozenset({"", "s", "es", "e", "ed", "d", "ing", "ies", "y", "n", "en"})
_PHYSICS_DEFYING_TOPICS = ("time machine", "perpetual motion", "telepathy", "faster than light")
MAX_PASSAGE_CHARS = 320
CLAIM_CHECK_CAVEAT = (
    "Passages are matched to the claim by keywords, not by understanding them. "
    "Read the quoted passages before relying on this."
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
    return re.findall(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*", (text or "").lower().replace("’", "'"))


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


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", clean_text(text)) if part.strip()]


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _passage_stance(sentence: str, claim_cues: set[str], claim_words: set[str]) -> str:
    if sentence.rstrip().endswith("?"):
        return "mentions"
    sentence_cues = _polarity_cues(sentence)
    # Signals the claim and the passage share cancel out: for the claim "the landing was a hoax",
    # "hoax" in a passage is the claim's own wording, while an extra "debunked" refutes it.
    claim_side = bool(claim_cues - sentence_cues)
    passage_side = bool(sentence_cues - claim_cues)
    if claim_side != passage_side:
        return "contradicts"
    attributions = {word.lower() for word in _ATTRIBUTION_RE.findall(sentence)}
    if any(not any(_same_word(word, claim_word) for claim_word in claim_words) for word in attributions):
        return "mentions"
    return "supports"


def assess_claim_evidence(claim: str, sources: list[SourceRecord]) -> list[ClaimEvidence]:
    """Find, per independent source, the passage that best addresses the claim.

    A passage addresses the claim when one sentence contains its key terms (all of them for claims
    with up to three terms, 70% otherwise). Sources on the same domain count once, and the same
    passage syndicated across sites counts once.
    """

    terms = _claim_terms(claim)
    if len(terms) < 2:
        return []
    needed = len(terms) if len(terms) <= 3 else math.ceil(0.7 * len(terms))
    claim_cues = _polarity_cues(claim)
    claim_words = set(_words(claim))
    trust_rank = {"High": 2, "Medium": 1}

    def rank(item: ClaimEvidence) -> tuple[bool, float, int]:
        return (item.stance != "mentions", item.coverage, trust_rank.get(item.trust_label, 0))

    best_by_domain: dict[str, ClaimEvidence] = {}
    for source in sources:
        best: ClaimEvidence | None = None
        for sentence in _sentences(f"{source.excerpt} {source.snippet}"):
            sentence_words = _words(sentence)
            matched = sum(1 for term in terms if any(_same_word(term, word) for word in sentence_words))
            if matched < needed:
                continue
            candidate = ClaimEvidence(
                stance=_passage_stance(sentence, claim_cues, claim_words),
                passage=sentence if len(sentence) <= MAX_PASSAGE_CHARS else sentence[: MAX_PASSAGE_CHARS - 1].rstrip() + "…",
                url=source.url,
                title=source.title,
                source=source.source,
                trust_label=source.trust_label,
                coverage=round(matched / len(terms), 2),
            )
            if best is None or rank(candidate) > rank(best):
                best = candidate
        if best is None:
            continue
        domain = (source.source or get_domain(source.url) or source.url).lower()
        current = best_by_domain.get(domain)
        if current is None or rank(best) > rank(current):
            best_by_domain[domain] = best

    evidence: list[ClaimEvidence] = []
    seen_passages: set[str] = set()
    for item in sorted(best_by_domain.values(), key=rank, reverse=True):
        key = " ".join(_words(item.passage))[:200]
        if key in seen_passages:
            continue
        seen_passages.add(key)
        evidence.append(item)
    return evidence


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
) -> dict[str, Any]:
    """Check the claim in a verification-style query against the retrieved passages.

    verify=None detects a verification request from the query text; pass True when the caller
    already stripped the "verify ..." command from it.
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
    }
    if not (is_verification_request(query) if verify is None else verify):
        return result
    claim = extract_claim_text(query)
    if len(_claim_terms(claim)) < 2:
        return result  # nothing specific enough to match passages against

    evidence = assess_claim_evidence(claim, sources)
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
    if contradictions:
        uncertainty.append(
            f"The lightweight checker flagged {len(contradictions)} possible contradiction(s) between sources on related statements."
        )
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
                    lines.append(f'- "{item.passage}" - [{label}]({item.url}) (trust: {item.trust_label})')
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
            lines.append("No direct contradictions were detected by the lightweight checker.")
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


def detect_claim_contradictions(claims: list[ClaimRecord]) -> list[ContradictionRecord]:
    """Find likely contradictions without pretending full semantic proof."""

    contradictions: list[ContradictionRecord] = []
    for i, first in enumerate(claims):
        first_terms = _term_set(first.text)
        if not first_terms:
            continue
        for second in claims[i + 1 :]:
            if first.source_url == second.source_url:
                continue
            overlap = first_terms & _term_set(second.text)
            if len(overlap) < 2:
                continue
            first_neg = bool(NEGATION_RE.search(first.text))
            second_neg = bool(NEGATION_RE.search(second.text))
            first_aff = bool(AFFIRMATION_RE.search(first.text))
            second_aff = bool(AFFIRMATION_RE.search(second.text))
            if first_neg != second_neg and (first_aff or second_aff):
                severity = "Medium" if min(first.source_trust, second.source_trust) >= 0.48 else "Weak"
                contradictions.append(
                    ContradictionRecord(
                        claim_a=first.text,
                        claim_b=second.text,
                        source_a=first.source_url,
                        source_b=second.source_url,
                        severity=severity,
                        reason=f"Shared terms with conflicting certainty/negation language: {', '.join(sorted(overlap)[:5])}",
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
    return (
        "You are Cognitive Nexus Reality-First Research Agent. Use only the supplied sources and extracted claims. "
        "Do not invent sources, quotes, dates, or conclusions. Clearly separate confirmed findings from weak leads.\n\n"
        f"Query: {report.query}\n\n"
        f"Source evidence:\n{chr(10).join(source_blocks)}\n\n"
        f"Extracted claims:\n{claim_blocks or 'No claims extracted.'}\n\n"
        f"Potential contradictions:\n{contradiction_blocks or 'None detected.'}\n\n"
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
    json_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def add_report_to_memory(report: ResearchReport, research_module: Any | None = None) -> bool:
    """Store a compact report summary into the existing local knowledge base."""

    ensure_report_dir()
    try:
        MEMORY_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_INDEX_FILE.open("a", encoding="utf-8").write(
            json.dumps(
                {
                    "timestamp": report.timestamp,
                    "query": report.query,
                    "summary": report.summary,
                    "sources": [source.url for source in report.sources[:12]],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        if research_module is not None:
            source_id = f"reality_research:{report.query}:{report.timestamp}"
            chunks = research_module.chunk_text(report.to_markdown(), target_size=650, overlap=80)
            stored = research_module.store_chunks_and_embeddings(source_id, chunks)
            source_hash = hashlib.md5(source_id.encode("utf-8")).hexdigest()[:12]
            research_module.metadata[source_hash] = {
                "url": source_id,
                "title": f"Reality-First Research: {report.query}",
                "timestamp": report.timestamp,
                "word_count": len(report.to_markdown().split()),
                "chunks_count": len(chunks),
                "source_type": "reality_research_report",
            }
            research_module._save_json_file(research_module.metadata_file, research_module.metadata)
            return bool(stored)
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
) -> ResearchReport:
    """Run the full Reality-First research workflow."""

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

    verdict_data = determine_verdict(query, sources, claims, contradictions, verify=request.verify_claim)
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
