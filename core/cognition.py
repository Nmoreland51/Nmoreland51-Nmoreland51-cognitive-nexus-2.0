"""
Cognition compatibility layer for Cognitive Nexus.

This satisfies core/__init__.py imports:
    from .cognition import CognitionEngine, Hypothesis

It provides a lightweight reasoning/cognition engine so the app can start
even if the deeper cognition system has not been fully built yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Hypothesis:
    """
    Represents a possible explanation, interpretation, or answer candidate.
    """

    claim: str
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    objections: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_evidence(self, evidence: str) -> None:
        self.evidence.append(evidence)

    def add_objection(self, objection: str) -> None:
        self.objections.append(objection)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CognitionEngine:
    """
    Lightweight cognition engine.

    This gives Cognitive Nexus a basic place to:
    - create hypotheses
    - score confidence
    - store reasoning traces
    - return structured analysis
    """

    def __init__(self) -> None:
        self.hypotheses: List[Hypothesis] = []
        self.trace: List[Dict[str, Any]] = []

    def create_hypothesis(
        self,
        claim: str,
        confidence: float = 0.5,
        evidence: Optional[List[str]] = None,
        objections: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Hypothesis:
        hypothesis = Hypothesis(
            claim=claim,
            confidence=confidence,
            evidence=evidence or [],
            objections=objections or [],
            metadata=metadata or {},
        )
        self.hypotheses.append(hypothesis)
        return hypothesis

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self.hypotheses.append(hypothesis)
        return hypothesis

    def reason(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Basic structured reasoning response.
        """

        context = context or {}

        hypothesis = self.create_hypothesis(
            claim=f"User request requires analysis: {prompt}",
            confidence=0.6,
            evidence=["Prompt received", "Context available" if context else "No extra context provided"],
            metadata={"context": context},
        )

        result = {
            "input": prompt,
            "hypothesis": hypothesis.to_dict(),
            "confidence": hypothesis.confidence,
            "status": "processed",
            "timestamp": datetime.utcnow().isoformat(),
        }

        self.trace.append(result)
        return result

    def analyze(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.reason(prompt, context)

    def process(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.reason(prompt, context)

    def evaluate_hypothesis(self, hypothesis: Hypothesis) -> Dict[str, Any]:
        evidence_count = len(hypothesis.evidence)
        objection_count = len(hypothesis.objections)

        adjusted_confidence = hypothesis.confidence
        adjusted_confidence += min(evidence_count * 0.05, 0.25)
        adjusted_confidence -= min(objection_count * 0.05, 0.25)
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

        return {
            "claim": hypothesis.claim,
            "original_confidence": hypothesis.confidence,
            "adjusted_confidence": adjusted_confidence,
            "evidence_count": evidence_count,
            "objection_count": objection_count,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def latest_hypotheses(self, limit: int = 10) -> List[Hypothesis]:
        return self.hypotheses[-limit:]

    def clear(self) -> None:
        self.hypotheses.clear()
        self.trace.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "trace": list(self.trace),
        }