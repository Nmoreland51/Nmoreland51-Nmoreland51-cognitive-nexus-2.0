from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResult:
    action: str
    payload: dict[str, Any]
    confidence: float = 0.5
    metadata: dict[str, Any] = None


class Agent:
    """Base agent abstraction for Cognitive Nexus."""

    def __init__(self, name: str) -> None:
        self.name = name

    def observe(self, data: str, metadata: dict[str, Any] | None = None) -> None:
        raise NotImplementedError("Agent.observe must be implemented by subclasses")

    def decide(self, query: str) -> AgentResult:
        raise NotImplementedError("Agent.decide must be implemented by subclasses")

    def respond(self, query: str) -> AgentResult:
        return self.decide(query)
