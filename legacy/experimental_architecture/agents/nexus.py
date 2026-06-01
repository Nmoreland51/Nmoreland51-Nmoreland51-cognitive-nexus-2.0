from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Agent, AgentResult


@dataclass
class RoutingIntent:
    name: str
    description: str
    priority: int = 0
    metadata: dict[str, Any] = None


class NexusAgent(Agent):
    """Route queries to the correct Cognitive Nexus subsystem."""

    def __init__(self) -> None:
        super().__init__(name="nexus_agent")
        self.intents: list[RoutingIntent] = []

    def register_intent(self, intent: RoutingIntent) -> None:
        self.intents.append(intent)

    def decide(self, query: str) -> AgentResult:
        normalized = query.strip().lower()
        selected = self.intents[0] if self.intents else RoutingIntent(
            name="fallback",
            description="Default fallback route",
            priority=0,
        )
        for intent in self.intents:
            if intent.name in normalized or intent.description.lower() in normalized:
                selected = intent
                break

        return AgentResult(
            action="route",
            payload={"intent": selected.name, "description": selected.description},
            confidence=0.8,
        )
