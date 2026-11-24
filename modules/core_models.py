"""How NexusCore asks a model: provider requests, short internal questions, labels for who answered, speed profiles.

Moved out of NexusCore (modules/nexus_core.py) unchanged; NexusCore is built from this class
(audit item 121). The methods use the attributes NexusCore.__init__ sets.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from modules.provider_router import ProviderRequest
from modules.answer_meta import answer_meta
from modules.response_planner import (
    ResponsePlan,
)
from nexus_router import RouterConfig

logger = logging.getLogger("modules.nexus_core")  # the same name as before the move


class ModelCalls:
    def _has_ready_model_provider(self, provider_order: list[str]) -> bool:
        for provider in provider_order:
            if provider == "fallback":
                continue
            try:
                if self.provider_router.detect_provider(provider).available:
                    return True
            except Exception:
                continue
        return False

    def _provider_request(
        self,
        prompt: str,
        settings: dict[str, Any],
        route_options: dict[str, Any],
        model: str = "",
        system_prompt: str = "",
    ) -> ProviderRequest:
        return ProviderRequest(
            prompt=prompt,
            model=model or settings.get("selected_model") or "",
            provider_order=list(settings.get("provider_order") or self.config.get("provider_order", [])),
            base_url=settings.get("base_url") or str(self.config.get("ollama_url", "")),
            options=dict(route_options or {}),
            timeout=float(settings.get("generation_timeout") or 300.0),
            system_prompt=system_prompt,
            max_tokens=int((route_options or {}).get("num_predict", 512)),
            # None leaves the decision to the saved allow_cloud_fallback setting.
            allow_cloud_fallback=(bool(settings["allow_cloud_fallback"]) if settings.get("allow_cloud_fallback") is not None else None),
        )

    def _model_text(self, prompt: str, settings: dict[str, Any], options: dict[str, Any]) -> str:
        """Text written by a real model, or ModelUnavailableError.

        Used wherever the text is stored or shown as the model's work (summaries, reports,
        knowledge answers), so the fallback notice can never be saved as if it were an answer.
        """

        request = self._provider_request(prompt, settings, options, model=settings.get("selected_model") or "")
        return self.provider_router.generate_or_raise(request).text

    def _produced_by(self, provider: str, started: float, *, answered: bool, tools: list[str]) -> dict[str, Any]:
        """How a research or knowledge result was produced, from the router's last request."""

        model_meta = dict(getattr(self.provider_router, "last_stream_metadata", {}) or {})
        tool_path = provider in {"web_research", "reality_research_agent", "bloodhound_search"}
        return answer_meta(
            {
                "provider": provider if (tool_path or not answered) else str(model_meta.get("provider") or provider),
                "model_provider": str(model_meta.get("provider") or ""),
                "model": str(model_meta.get("model") or ""),
                "success": answered,
                "partial": bool(model_meta.get("partial")),
                "elapsed": time.perf_counter() - started,
                "fallback_reason": "" if answered else str(model_meta.get("fallback_reason") or ""),
                "skipped_cloud": list(model_meta.get("skipped_cloud") or []),
                "usage": dict(model_meta.get("usage") or {}),
                "model_note": str(model_meta.get("model_note") or ""),
                "tools_run": tools,
            }
        )

    def _apply_throughput_profile(
        self,
        options: dict[str, Any],
        settings: dict[str, Any],
        plan: ResponsePlan,
    ) -> dict[str, Any]:
        """Tune local generation options for lower latency and higher token throughput."""

        tuned = dict(options or {})
        mode = str(settings.get("throughput_mode") or "balanced").lower()
        if mode not in {"balanced", "fast", "turbo"}:
            mode = "balanced"
        if mode == "balanced":
            return tuned

        max_ctx = 2048 if mode == "fast" else 1024
        max_predict = 384 if mode == "fast" else 220
        if plan.intent in {"research", "reality_check"}:
            max_ctx = max(max_ctx, 4096)
            max_predict = max(max_predict, 700)
        elif plan.intent in {"debugging", "troubleshooting", "project_planning"}:
            max_predict = max(max_predict, 320)
        if plan.diagnostics.get("requested_words"):
            # A length the owner asked for outranks the speed profile. "Fast" used to cap every
            # answer at 384 tokens, about 290 words, whatever was asked for.
            max_predict = max(max_predict, int(plan.max_tokens))
            max_ctx = max(max_ctx, 4096)

        tuned["num_ctx"] = min(int(tuned.get("num_ctx", max_ctx) or max_ctx), max_ctx)
        tuned["num_predict"] = min(int(tuned.get("num_predict", max_predict) or max_predict), max_predict)
        tuned["temperature"] = min(float(tuned.get("temperature", 0.6) or 0.6), 0.55 if mode == "fast" else 0.35)
        tuned["top_k"] = min(int(tuned.get("top_k", 40) or 40), 30 if mode == "fast" else 20)
        tuned["top_p"] = min(float(tuned.get("top_p", 0.9) or 0.9), 0.85 if mode == "fast" else 0.75)
        tuned["repeat_last_n"] = min(int(tuned.get("repeat_last_n", 128) or 128), 96 if mode == "fast" else 64)
        # No load-time option here (num_batch, num_thread and the like). "Fast" used to send
        # num_batch 256 while the content-rule check, the search plan, the result judge and the web
        # answer send none, and Ollama reloads the model whenever such an option changes ("runner
        # options changed" in its log, about 4 s each time here; measured 2026-11-24).
        tuned.pop("num_batch", None)
        return tuned

    def _uses_slow_startup_ollama_model(self, model: str) -> bool:
        """Return True for local models that need more than a tiny first-token window."""

        normalized = str(model or "").lower()
        return "blackhillsinfosec/" in normalized or "abliterated" in normalized

    def _make_classifier(self, settings: dict[str, Any], router_config: RouterConfig):
        if not router_config.use_llm_classifier:
            return None
        if not settings.get("provider_ready") and not settings.get("provider_order"):
            return None

        def classify(prompt: str) -> str:
            result = self.provider_router.generate(
                ProviderRequest(
                    prompt=prompt,
                    model=router_config.default_model or settings.get("selected_model") or "",
                    provider_order=list(settings.get("provider_order") or []),
                    base_url=settings.get("base_url") or "",
                    options={"temperature": 0.1, "num_predict": 120},
                    timeout=min(float(settings.get("generation_timeout", 300.0)), 120.0),
                )
            )
            # A model that did not answer has no opinion; the rule-based route is used instead.
            return result.text if result.success else ""

        return classify
