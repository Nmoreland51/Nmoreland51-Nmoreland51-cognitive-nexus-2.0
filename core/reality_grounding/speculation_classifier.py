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


# Each pattern groups its alternatives so the word boundaries apply to every word. Without the
# group, `\bmay|might|...\b` matched "might" inside any word and "may" inside "maybe".
_FICTION = re.compile(r"\b(?:fictional|fantasy|roleplay|in this story|worldbuilding)\b")
_SCI_FI = re.compile(r"\b(?:science fiction|wormhole stabilizer|time machine|faster-than-light drive)\b")
_THEORETICAL = re.compile(r"\b(?:theoretical|hypothetical|in principle|not currently practical)\b")
_CONSPIRACY = re.compile(r"\b(?:conspiracy|secret cabal|cover[- ]?up|they don't want you to know)\b")
_HEDGING = re.compile(r"\b(?:may|might|could|appears|seems|possibly|speculative)\b")


def classify_speculation(text: str, route_category: str = "", source_count: int = 0) -> SpeculationReport:
    lowered = (text or "").lower()
    if route_category in {"adult_creative", "dark_fiction"}:
        return SpeculationReport("roleplay/fantasy", 0.95, "Creative route selected.")
    if _FICTION.search(lowered):
        return SpeculationReport("roleplay/fantasy", 0.9, "Answer self-labels as fiction or roleplay.")
    if _SCI_FI.search(lowered):
        return SpeculationReport("science fiction", 0.86, "Contains currently fictional technology framing.")
    if _THEORETICAL.search(lowered):
        return SpeculationReport("theoretical science", 0.72, "Uses theoretical/hypothetical framing.")
    if _CONSPIRACY.search(lowered):
        return SpeculationReport("unsupported claim", 0.78, "Conspiracy-like framing requires evidence.")
    if _HEDGING.search(lowered):
        if source_count > 0:
            # Caveats such as "there may be more recent news" are normal in a sourced answer
            # and don't make its sourced facts speculative.
            return SpeculationReport("established fact", 0.35, f"Hedging language, but backed by {source_count} sources.")
        return SpeculationReport("speculative hypothesis", 0.55, "Uses uncertainty language.")
    return SpeculationReport("established fact", 0.35, "No strong speculation markers detected.")
