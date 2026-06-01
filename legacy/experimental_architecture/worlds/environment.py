from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class EnvironmentState:
    name: str
    description: str
    facts: Dict[str, Any] = field(default_factory=dict)

    def update_fact(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def describe(self) -> str:
        return f"{self.name}: {self.description} ({len(self.facts)} facts)"
