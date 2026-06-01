from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Experiment:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    results: List[Dict[str, Any]] = field(default_factory=list)

    def record_result(self, result: Dict[str, Any]) -> None:
        self.results.append(result)

    def summary(self) -> str:
        return f"Experiment {self.name}: {len(self.results)} results."
