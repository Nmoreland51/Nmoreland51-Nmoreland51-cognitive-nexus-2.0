from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SimulationStage:
    name: str
    description: str
    results: List[Dict[str, Any]] = field(default_factory=list)


class SimulationLoop:
    """A simple observe-model-test-refine simulation loop."""

    def __init__(self) -> None:
        self.stages: List[SimulationStage] = []

    def add_stage(self, name: str, description: str) -> None:
        self.stages.append(SimulationStage(name=name, description=description))

    def run(self, input_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        return {
            "input": input_text,
            "stages": [stage.name for stage in self.stages],
            "status": "executed",
            "context": context,
        }
