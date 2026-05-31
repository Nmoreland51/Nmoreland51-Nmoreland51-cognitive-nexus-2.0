"""
Internal model compatibility layer for Cognitive Nexus.

This file satisfies core/__init__.py imports:
    from .model import BeliefSystem, InternalModel

It gives the app a lightweight belief/internal-state system so startup does not crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Belief:
    key: str
    value: Any
    confidence: float = 1.0
    source: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BeliefSystem:
    """
    Stores beliefs/assumptions the AI can use internally.

    Example:
        beliefs.set("ollama_available", True, confidence=0.95)
        beliefs.get("ollama_available")
    """

    def __init__(self) -> None:
        self._beliefs: Dict[str, Belief] = {}

    def set(
        self,
        key: str,
        value: Any,
        confidence: float = 1.0,
        source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Belief:
        belief = Belief(
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            metadata=metadata or {},
        )
        self._beliefs[key] = belief
        return belief

    def update(
        self,
        key: str,
        value: Any,
        confidence: float = 1.0,
        source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Belief:
        return self.set(
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

    def get(self, key: str, default: Any = None) -> Any:
        belief = self._beliefs.get(key)
        return belief.value if belief else default

    def get_belief(self, key: str) -> Optional[Belief]:
        return self._beliefs.get(key)

    def has(self, key: str) -> bool:
        return key in self._beliefs

    def remove(self, key: str) -> None:
        self._beliefs.pop(key, None)

    def clear(self) -> None:
        self._beliefs.clear()

    def all(self) -> List[Belief]:
        return list(self._beliefs.values())

    def to_dict(self) -> Dict[str, Any]:
        return {key: belief.to_dict() for key, belief in self._beliefs.items()}


class InternalModel:
    """
    Lightweight internal state container.

    This gives Cognitive Nexus somewhere to store:
    - beliefs
    - observations
    - session state
    - runtime metadata
    """

    def __init__(self) -> None:
        self.beliefs = BeliefSystem()
        self.state: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

    def set_state(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.metadata["updated_at"] = datetime.utcnow().isoformat()

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def update_state(self, values: Dict[str, Any]) -> None:
        self.state.update(values)
        self.metadata["updated_at"] = datetime.utcnow().isoformat()

    def clear_state(self) -> None:
        self.state.clear()
        self.metadata["updated_at"] = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beliefs": self.beliefs.to_dict(),
            "state": dict(self.state),
            "metadata": dict(self.metadata),
        }