from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TheoryEvaluation:
    coherence: float
    evidence_strength: float
    contradictions: List[str] = field(default_factory=list)


@dataclass
class Theory:
    title: str
    hypothesis: str
    rationale: str
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self) -> TheoryEvaluation:
        score = 0.5 + min(len(self.evidence) * 0.05, 0.4)
        return TheoryEvaluation(coherence=score, evidence_strength=score)

    def summary(self) -> str:
        return f"{self.title}: {self.hypothesis} (evidence={len(self.evidence)})"
