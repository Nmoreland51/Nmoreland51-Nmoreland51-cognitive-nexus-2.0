"""
Grounding compatibility layer for Cognitive Nexus.

This satisfies core/__init__.py imports:
    from .grounding import GroundingAgent, FactCheck

Your repo has core/reality_grounding/, but core/__init__.py expects
a top-level core/grounding.py file. This bridges that gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class FactCheck:
    claim: str
    verdict: str = "unverified"
    confidence: float = 0.5
    sources: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GroundingAgent:
    """
    Lightweight grounding/fact-checking agent.

    This is intentionally safe and simple so the app can start.
    Deeper grounding can still live inside core/reality_grounding/.
    """

    def __init__(self) -> None:
        self.checks: List[FactCheck] = []

    def fact_check(
        self,
        claim: str,
        sources: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> FactCheck:
        sources = sources or []
        context = context or {}

        if sources:
            verdict = "grounded"
            confidence = 0.75
            notes = "Claim has supporting source material."
        else:
            verdict = "unverified"
            confidence = 0.45
            notes = "No source material was provided for this claim."

        result = FactCheck(
            claim=claim,
            verdict=verdict,
            confidence=confidence,
            sources=sources,
            notes=notes,
            metadata={"context": context},
        )

        self.checks.append(result)
        return result

    def check(
        self,
        claim: str,
        sources: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> FactCheck:
        return self.fact_check(claim, sources=sources, context=context)

    def ground(
        self,
        answer: str,
        sources: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        fact_check = self.fact_check(answer, sources=sources, context=context)

        return {
            "answer": answer,
            "grounded": bool(sources),
            "verdict": fact_check.verdict,
            "confidence": fact_check.confidence,
            "sources": fact_check.sources,
            "notes": fact_check.notes,
            "timestamp": fact_check.timestamp,
        }

    def audit_answer(
        self,
        answer: str,
        sources: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.ground(answer, sources=sources, context=context)

    def latest(self, limit: int = 10) -> List[FactCheck]:
        return self.checks[-limit:]

    def all(self) -> List[FactCheck]:
        return list(self.checks)

    def clear(self) -> None:
        self.checks.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [check.to_dict() for check in self.checks],
        }