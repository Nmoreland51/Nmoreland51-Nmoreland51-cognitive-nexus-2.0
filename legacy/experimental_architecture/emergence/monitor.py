from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EmergenceEvent:
    description: str
    novelty_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class EmergenceMonitor:
    """Lightweight monitor for emergent behavior and insight discovery."""

    def __init__(self) -> None:
        self.events: List[EmergenceEvent] = []

    def record_event(self, description: str, novelty_score: float, metadata: dict[str, Any] | None = None) -> None:
        self.events.append(EmergenceEvent(description=description, novelty_score=novelty_score, metadata=metadata or {}))

    def latest(self, limit: int = 10) -> List[EmergenceEvent]:
        return self.events[-limit:]

    def summary(self) -> str:
        return f"Emergence monitor captured {len(self.events)} events."
