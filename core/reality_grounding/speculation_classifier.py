"""Speculation and reality-category classification."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SpeculationReport:
    category: str
    probability: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_speculation(text: str, route_category: str = "") -> SpeculationReport:
    lowered = (text or "").lower()
    if route_category in {"adult_creative", "dark_fiction"}:
        return SpeculationReport("roleplay/fantasy", 0.95, "Creative route selected.")
    if re.search(r"\bfictional|fantasy|roleplay|in this story|worldbuilding\b", lowered):
        return SpeculationReport("roleplay/fantasy", 0.9, "Answer self-labels as fiction or roleplay.")
    if re.search(r"\bscience fiction|wormhole stabilizer|time machine|faster-than-light drive\b", lowered):
        return SpeculationReport("science fiction", 0.86, "Contains currently fictional technology framing.")
    if re.search(r"\btheoretical|hypothetical|in principle|not currently practical\b", lowered):
        return SpeculationReport("theoretical science", 0.72, "Uses theoretical/hypothetical framing.")
    if re.search(r"\bconspiracy|secret cabal|cover[- ]?up|they don't want you to know\b", lowered):
        return SpeculationReport("unsupported claim", 0.78, "Conspiracy-like framing requires evidence.")
    if re.search(r"\bmay|might|could|appears|seems|possibly|speculative\b", lowered):
        return SpeculationReport("speculative hypothesis", 0.55, "Uses uncertainty language.")
    return SpeculationReport("established fact", 0.35, "No strong speculation markers detected.")

