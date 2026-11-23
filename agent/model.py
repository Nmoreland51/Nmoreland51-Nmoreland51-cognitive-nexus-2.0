"""The language model as the agent sees it: a prompt in, text and its cost out.

The agent never talks to a provider directly. RouterModel goes through the app's provider router,
so the user's provider order, the cloud-fallback switch and the "a failed model is not an answer"
rule apply to the agent exactly as they do to chat. ScriptedModel replays fixed replies, for tests
of the harness that must not depend on what a model happens to write.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from modules.token_estimate import estimate_tokens


@dataclass
class ModelReply:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    usd: float = 0.0  # what a paid provider charged for this call, as far as it is known
    model: str = ""
    provider: str = ""


class Model(Protocol):
    name: str

    def complete(self, prompt: str, *, max_tokens: int = 700, temperature: float = 0.0) -> ModelReply: ...


class RouterModel:
    """A model reached through modules/provider_router.ProviderRouter."""

    def __init__(self, router: Any, *, model: str = "", provider_order: list[str] | None = None, num_ctx: int = 8192, allow_cloud: bool | None = None) -> None:
        self.router = router
        self.model = model
        self.provider_order = list(provider_order or [])
        self.num_ctx = int(num_ctx)
        self.allow_cloud = allow_cloud
        self.name = model or "default model"

    def complete(self, prompt: str, *, max_tokens: int = 700, temperature: float = 0.0) -> ModelReply:
        from modules.provider_router import ProviderRequest

        started = time.perf_counter()
        result = self.router.generate_or_raise(
            ProviderRequest(
                prompt=prompt,
                model=self.model,
                provider_order=list(self.provider_order),
                options={"temperature": float(temperature), "num_predict": int(max_tokens), "num_ctx": self.num_ctx},
                max_tokens=int(max_tokens),
                timeout=1800.0,
                allow_cloud_fallback=self.allow_cloud,
            )
        )
        usage = dict(getattr(self.router, "_last_cloud_usage", {}) or {}) if result.provider in {"openai", "anthropic"} else {}
        return ModelReply(
            text=result.text,
            tokens_in=int(usage.get("input_tokens") or estimate_tokens(prompt)),
            tokens_out=int(usage.get("output_tokens") or estimate_tokens(result.text)),
            seconds=round(time.perf_counter() - started, 2),
            usd=float(usage.get("estimated_cost_usd") or 0.0),
            model=result.model or self.model,
            provider=result.provider,
        )


class ScriptedModel:
    """Replies from a list (in order) or from a function of the prompt. Records every prompt it was given."""

    def __init__(self, replies: list[str] | Callable[[str], str], name: str = "scripted") -> None:
        self._replies = replies
        self.prompts: list[str] = []
        self.name = name

    def complete(self, prompt: str, *, max_tokens: int = 700, temperature: float = 0.0) -> ModelReply:
        self.prompts.append(prompt)
        if callable(self._replies):
            text = self._replies(prompt)
        else:
            if len(self.prompts) > len(self._replies):
                raise RuntimeError("The scripted model has no more replies.")
            text = self._replies[len(self.prompts) - 1]
        return ModelReply(text=text, tokens_in=estimate_tokens(prompt), tokens_out=estimate_tokens(text), seconds=0.0, model=self.name, provider="scripted")
