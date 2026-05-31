"""Reality-status modeling before answer generation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


ESTABLISHED_TERMS = {
    "gravity",
    "evolution",
    "semiconductor",
    "relativity",
    "vaccine",
    "transistor",
    "database",
    "python",
    "streamlit",
}

THEORETICAL_TERMS = {
    "wormhole",
    "alcubierre",
    "closed timelike curve",
    "cosmic string",
    "multiverse",
}

FICTIONAL_TERMS = {
    "time machine",
    "temporal stabilizer",
    "chrono stabilizer",
    "chrono-displacement engine",
    "wormhole stabilizer",
    "dimensional phase harmonizer",
    "quantum resonance synchronization matrix",
    "neural entropy manifold",
    "quantum foam synchronization array",
}

PSEUDOSCIENCE_TERMS = {
    "scalar wave",
    "biofield",
    "quantum healing",
    "vibrational frequency cure",
    "alchemy transmutation",
}

IMPOSSIBLE_PATTERNS = [
    r"\bperpetual motion\b",
    r"\bfree energy machine\b",
    r"\boverunity\b",
    r"\bviolate conservation of energy\b",
]

DIRECT_RESPONSE_PATTERN = re.compile(
    r"^\s*(?:reply|respond|say|output|print|return|write)\b",
    re.IGNORECASE,
)


@dataclass
class RealityModel:
    domain: str = "general"
    reality_status: str = "unknown"
    matched_terms: list[str] = field(default_factory=list)
    impossible_markers: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_domain(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(api|python|package|function|class|library|npm|pip|code|bug)\b", lowered):
        return "coding"
    if re.search(r"\b(physics|quantum|energy|wormhole|relativity|machine|engine|device)\b", lowered):
        return "science_engineering"
    if re.search(r"\b(medicine|diagnosis|symptom|treatment|drug|dose)\b", lowered):
        return "medicine"
    if re.search(r"\b(law|legal|statute|court|contract)\b", lowered):
        return "law"
    if re.search(r"\b(stock|finance|market|investment|tax)\b", lowered):
        return "finance"
    return "general"


def _find_terms(text: str, terms: set[str]) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in terms if term in lowered)


def is_direct_response_instruction(text: str) -> bool:
    """Detect prompts that ask for output formatting rather than external facts."""

    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if "?" in lowered:
        return False
    if re.search(r"\b(research|verify|fact[- ]?check|source|cite|search|investigate)\b", lowered):
        return False
    return bool(DIRECT_RESPONSE_PATTERN.search(lowered))


def model_reality(text: str, route_category: str = "") -> RealityModel:
    """Classify the reality status of the concepts in the prompt."""

    lowered = text.lower()
    domain = infer_domain(text)
    impossible = [pattern for pattern in IMPOSSIBLE_PATTERNS if re.search(pattern, lowered)]
    fictional = _find_terms(text, FICTIONAL_TERMS)
    pseudo = _find_terms(text, PSEUDOSCIENCE_TERMS)
    theoretical = _find_terms(text, THEORETICAL_TERMS)
    established = _find_terms(text, ESTABLISHED_TERMS)

    if route_category in {"adult_creative", "dark_fiction"}:
        return RealityModel(domain="creative", reality_status="fiction_or_roleplay", reason="Creative route selected.")
    if impossible:
        return RealityModel(domain=domain, reality_status="impossible_under_current_science", impossible_markers=impossible, reason="Prompt contains known impossibility markers.")
    if fictional:
        return RealityModel(domain=domain, reality_status="fictional_construct", matched_terms=fictional, reason="Prompt contains science-fiction or invented engineering terms.")
    if pseudo:
        return RealityModel(domain=domain, reality_status="pseudoscience_or_unsupported", matched_terms=pseudo, reason="Prompt contains pseudoscience markers.")
    if theoretical:
        return RealityModel(domain=domain, reality_status="theoretical_science", matched_terms=theoretical, reason="Prompt contains theoretical concepts without practical implementation.")
    if established:
        return RealityModel(domain=domain, reality_status="established_or_practical", matched_terms=established, reason="Prompt contains established concepts.")
    if is_direct_response_instruction(text):
        return RealityModel(domain="instruction", reality_status="instruction_only", reason="Prompt asks for response formatting, not a factual claim.")
    if re.search(r"\b(imagine|fictional|story|worldbuild|roleplay)\b", lowered):
        return RealityModel(domain="creative", reality_status="fiction_or_roleplay", reason="Prompt asks for fictional framing.")
    return RealityModel(domain=domain, reality_status="unknown_or_needs_grounding", reason="No strong reality-status markers detected.")
