from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ProviderStatus:
    available: bool
    models: List[str]
    notes: str = ""


class LocalModelProvider:
    """A minimal local provider abstraction for Cognitive Nexus."""

    def __init__(self, provider_name: str = "local") -> None:
        self.provider_name = provider_name
        self.models: List[str] = []

    def register_model(self, model_name: str) -> None:
        if model_name not in self.models:
            self.models.append(model_name)

    def infer(self, prompt: str, model: str | None = None) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": model or self.models[0] if self.models else "default",
            "prompt": prompt,
            "response": "[simulated local provider response]",
        }

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            available=True,
            models=self.models,
            notes="Local provider interface available.",
        )
