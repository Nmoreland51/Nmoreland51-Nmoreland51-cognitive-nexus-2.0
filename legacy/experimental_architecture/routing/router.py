from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class RouteDecision:
    route_name: str
    confidence: float
    reason: str
    metadata: Dict[str, Any] = None


class Router:
    """Simplified router for Cognitive Nexus query flow."""

    def __init__(self) -> None:
        self.routes: Dict[str, str] = {}

    def register_route(self, name: str, description: str) -> None:
        self.routes[name] = description

    def decide(self, query: str) -> RouteDecision:
        normalized = query.strip().lower()
        for name, description in self.routes.items():
            if name in normalized or any(token in normalized for token in description.lower().split()):
                return RouteDecision(route_name=name, confidence=0.75, reason=f"Matched route {name}")

        return RouteDecision(route_name="default", confidence=0.5, reason="No strong route matched")
