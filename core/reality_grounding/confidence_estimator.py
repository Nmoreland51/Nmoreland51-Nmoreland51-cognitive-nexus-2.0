"""Confidence scoring for grounded answers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ConfidenceReport:
    level: str
    factual_certainty: float
    source_confidence: float
    reasoning_confidence: float
    contradiction_risk: float
    speculation_probability: float
    hallucination_probability: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_confidence(
    *,
    source_status: str,
    source_count: int,
    hallucination_probability: float,
    contradiction_risk: float,
    speculation_probability: float,
    claim_count: int,
) -> ConfidenceReport:
    source_conf = 0.15
    if source_status in {"verified", "source-grounded"}:
        source_conf = min(0.95, 0.55 + min(source_count, 6) * 0.07)
    elif source_status in {"memory-grounded", "tool-confirmed"}:
        source_conf = 0.65

    factual = 0.78
    factual -= hallucination_probability * 0.45
    factual -= contradiction_risk * 0.35
    factual -= max(0.0, speculation_probability - 0.5) * 0.25
    if claim_count > 5 and source_count == 0:
        factual -= 0.18
    factual = max(0.05, min(0.98, factual))

    reasoning = max(0.05, min(0.95, 0.82 - contradiction_risk * 0.5 - hallucination_probability * 0.3))
    combined = factual * 0.45 + source_conf * 0.30 + reasoning * 0.25

    if speculation_probability >= 0.82:
        level = "FICTIONAL / UNKNOWN"
    elif combined >= 0.86:
        level = "VERIFIED"
    elif combined >= 0.72:
        level = "HIGH CONFIDENCE"
    elif combined >= 0.55:
        level = "MODERATE CONFIDENCE"
    elif combined >= 0.35:
        level = "LOW CONFIDENCE"
    else:
        level = "SPECULATIVE"

    return ConfidenceReport(
        level=level,
        factual_certainty=round(factual, 3),
        source_confidence=round(source_conf, 3),
        reasoning_confidence=round(reasoning, 3),
        contradiction_risk=round(contradiction_risk, 3),
        speculation_probability=round(speculation_probability, 3),
        hallucination_probability=round(hallucination_probability, 3),
    )

