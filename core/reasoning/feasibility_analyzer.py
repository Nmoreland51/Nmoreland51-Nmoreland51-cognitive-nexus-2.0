"""Procedural feasibility analysis before generation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from core.reasoning.reality_model import RealityModel


PROCEDURAL_PATTERNS = [
    r"\bhow (do|to|would|can)\b",
    r"\bbuild\b",
    r"\bmake\b",
    r"\bcreate\b",
    r"\bimplement\b",
    r"\bsteps?\b",
    r"\bcomponent(s)?\b",
    r"\bblueprint\b",
    r"\broadmap\b",
    r"\bprocedure\b",
]


@dataclass
class FeasibilityReport:
    level: str
    score: float
    procedural_requested: bool
    procedural_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def wants_procedure(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in PROCEDURAL_PATTERNS)


def analyze_feasibility(text: str, reality: RealityModel) -> FeasibilityReport:
    procedural = wants_procedure(text)
    status = reality.reality_status
    if status == "instruction_only":
        return FeasibilityReport("instruction", 1.0, procedural, True, "Prompt is a response instruction, not an external reality claim.")
    if status == "established_or_practical":
        return FeasibilityReport("established", 0.86, procedural, True, "Concept appears established or practically grounded.")
    if status == "theoretical_science":
        return FeasibilityReport("theoretical_only", 0.32, procedural, False, "Concept is theoretical; practical procedure is not established.")
    if status in {"fictional_construct", "fiction_or_roleplay"}:
        return FeasibilityReport("fictional", 0.12, procedural, False, "Concept is fictional or narrative-framed.")
    if status == "pseudoscience_or_unsupported":
        return FeasibilityReport("unsupported", 0.18, procedural, False, "Concept lacks reliable scientific grounding.")
    if status == "impossible_under_current_science":
        return FeasibilityReport("impossible", 0.04, procedural, False, "Concept conflicts with established constraints.")
    return FeasibilityReport("unknown", 0.45, procedural, not procedural, "Feasibility is unclear without additional evidence.")
