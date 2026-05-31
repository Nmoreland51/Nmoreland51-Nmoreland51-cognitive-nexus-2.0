"""Lightweight internal contradiction checks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


CONTRADICTION_PAIRS = [
    (r"\bfaster[- ]than[- ]light .* impossible\b", r"\bstandard .* exceed light speed\b", "FTL impossibility conflicts with ordinary light-speed exceedance."),
    (r"\bno evidence\b", r"\bproven\b", "No-evidence language conflicts with proof language."),
    (r"\bunknown\b", r"\bdefinitely\b", "Unknown language conflicts with definite certainty."),
    (r"\bfictional\b", r"\breal-world working\b", "Fictional framing conflicts with real-world functionality."),
]


@dataclass
class ContradictionReport:
    contradictions: list[str] = field(default_factory=list)
    risk: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_contradictions(text: str) -> ContradictionReport:
    lowered = (text or "").lower()
    contradictions: list[str] = []
    for first, second, message in CONTRADICTION_PAIRS:
        if re.search(first, lowered, flags=re.IGNORECASE | re.DOTALL) and re.search(second, lowered, flags=re.IGNORECASE | re.DOTALL):
            contradictions.append(message)
    risk = min(1.0, len(contradictions) * 0.35)
    return ContradictionReport(contradictions=contradictions, risk=round(risk, 3))

