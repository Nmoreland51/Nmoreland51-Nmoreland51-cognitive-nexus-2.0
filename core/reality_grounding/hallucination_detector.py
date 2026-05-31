"""Hallucination-risk and fake-intelligence pattern detection."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


BUZZWORD_TERMS = {
    "quantum",
    "neural",
    "entropy",
    "manifold",
    "resonance",
    "synchronization",
    "harmonization",
    "stabilizer",
    "temporal",
    "foam",
    "fractal",
    "holographic",
    "biofield",
    "scalar",
    "vibrational",
}

SUSPICIOUS_PHRASES = [
    r"\btemporal (resonance|harmonization|stabilizer)\b",
    r"\bquantum foam synchronization\b",
    r"\bneural entropy manifold\b",
    r"\bwindows kernel quantum\b",
    r"\bproprietary undocumented api\b",
    r"\bstudies prove\b",
    r"\bscientists have confirmed\b",
]

FAKE_CITATION_PATTERNS = [
    r"\[[A-Z][A-Za-z]+ et al\.,?\s?\d{4}\]",
    r"\bJournal of [A-Z][A-Za-z]+ (Studies|Research|Science)\b",
    r"\bdoi:\s?10\.\d{4,9}/[^\s]+",
    r"\barXiv:\d{4}\.\d{4,5}\b",
]


@dataclass
class HallucinationSignal:
    signal_type: str
    text: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HallucinationReport:
    probability: float = 0.0
    signals: list[HallucinationSignal] = field(default_factory=list)
    buzzword_density: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": self.probability,
            "signals": [signal.to_dict() for signal in self.signals],
            "buzzword_density": self.buzzword_density,
        }


def detect_hallucination_risk(text: str, *, source_count: int = 0, tool_confirmed: bool = False) -> HallucinationReport:
    """Detect likely hallucination patterns with deterministic heuristics."""

    lowered = (text or "").lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", lowered)
    buzzwords = [word for word in words if word in BUZZWORD_TERMS]
    density = len(buzzwords) / max(1, len(words))
    signals: list[HallucinationSignal] = []

    if density >= 0.045 and len(buzzwords) >= 3:
        signals.append(HallucinationSignal("buzzword_density", f"High jargon density: {', '.join(sorted(set(buzzwords))[:8])}", "medium"))

    for pattern in SUSPICIOUS_PHRASES:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            signals.append(HallucinationSignal("suspicious_phrase", match.group(0), "high"))

    for pattern in FAKE_CITATION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE) and source_count == 0:
            signals.append(HallucinationSignal("unsupported_citation", pattern, "high"))

    if re.search(r"\bI (fixed|ran|verified|installed|pushed|deleted|created)\b", text, re.IGNORECASE) and not tool_confirmed:
        signals.append(HallucinationSignal("unconfirmed_tool_claim", "Completion claim without tool confirmation.", "medium"))

    if re.search(r"\b(?:always|never|guaranteed|proven|certainly|undeniably)\b", lowered) and source_count == 0:
        signals.append(HallucinationSignal("overconfidence", "Absolute confidence without sources.", "medium"))

    probability = min(
        1.0,
        density * 3
        + sum(0.25 if signal.severity == "high" else 0.13 for signal in signals),
    )
    return HallucinationReport(probability=round(probability, 3), signals=signals, buzzword_density=round(density, 4))

