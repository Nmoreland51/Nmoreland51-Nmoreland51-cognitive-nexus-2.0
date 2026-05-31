"""Structural hallucination checks for procedural-looking answers."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


FAKE_COMPONENT_MARKERS = [
    "stabilizer",
    "harmonizer",
    "resonance field",
    "synchronization matrix",
    "phase array",
    "chrono",
    "temporal core",
]


@dataclass
class ProceduralStructureReport:
    structural_risk: float
    fake_component_markers: list[str] = field(default_factory=list)
    stepwise_framing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_procedural_structure(answer: str) -> ProceduralStructureReport:
    lowered = (answer or "").lower()
    markers = [marker for marker in FAKE_COMPONENT_MARKERS if marker in lowered]
    stepwise = bool(re.search(r"(^|\n)\s*(\d+\.|-)\s+|you (will|would) need|components?:", lowered))
    risk = min(1.0, len(markers) * 0.18 + (0.25 if stepwise and markers else 0.0))
    return ProceduralStructureReport(round(risk, 3), markers, stepwise)

