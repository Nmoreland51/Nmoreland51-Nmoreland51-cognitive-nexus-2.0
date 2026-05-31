"""
Observation compatibility layer for Cognitive Nexus.

This file exists because core/__init__.py imports:
    from .observation import Observation, ObservationLog

Without this file, the app crashes on startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Observation:
    content: str
    source: str = "system"
    confidence: float = 1.0
    category: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ObservationLog:
    def __init__(self) -> None:
        self.observations: List[Observation] = []

    def add(
        self,
        content: str,
        source: str = "system",
        confidence: float = 1.0,
        category: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Observation:
        observation = Observation(
            content=content,
            source=source,
            confidence=confidence,
            category=category,
            metadata=metadata or {},
        )
        self.observations.append(observation)
        return observation

    def record(self, *args: Any, **kwargs: Any) -> Observation:
        return self.add(*args, **kwargs)

    def latest(self, limit: int = 10) -> List[Observation]:
        return self.observations[-limit:]

    def all(self) -> List[Observation]:
        return list(self.observations)

    def clear(self) -> None:
        self.observations.clear()

    def to_list(self) -> List[Dict[str, Any]]:
        return [obs.to_dict() for obs in self.observations]