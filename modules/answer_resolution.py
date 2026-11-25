"""What can be done about an answer the app could not ground: look it up on the web, or ask another model.

Until 2026-11-25 the app noticed such an answer ("Confidence: LOW CONFIDENCE. No external source grounding
was attached") and delivered it with nothing to be done about it. Now the answer is still shown at once, and
under it the owner can have the same question looked up on the web or answered by another installed model.
With the owner's setting "Look it up on the web by itself", the web lookup follows on its own.

Nothing here changes or holds back the first answer, and nothing leaves the machine unless the owner asks
for the web lookup (or chose to have it done by itself).
"""

from __future__ import annotations

import dataclasses
from typing import Any

# The confidence levels of the reality audit (core/reality_grounding) that mean "not grounded in anything".
UNGROUNDED_LEVELS = frozenset({"LOW CONFIDENCE", "SPECULATIVE"})
# Replies that did not come from a model: there is nothing to look up or ask again.
NOT_FROM_A_MODEL = frozenset({"", "fallback", "local_fast_path", "local_followup_clarification", "content_rule", "adaptive_memory"})


def is_ungrounded(provider_result: dict[str, Any] | None, reality_audit: dict[str, Any] | None) -> bool:
    """True for a model's answer that used no sources and that the reality audit rated low or speculative."""

    result, audit = provider_result or {}, reality_audit or {}
    if str(result.get("provider") or "") in NOT_FROM_A_MODEL or int(result.get("sources") or 0) > 0:
        return False
    return str((audit.get("confidence") or {}).get("level") or "") in UNGROUNDED_LEVELS


def other_models(chat_models: list[str] | None, current: str, limit: int = 3) -> list[str]:
    """Installed chat models other than the one that answered, in the order they are listed."""

    return [model for model in (chat_models or []) if model and model != current][:limit]


def resolution_settings(settings: dict[str, Any], *, research: bool = False, model: str = "") -> dict[str, Any]:
    """The settings for asking the same question again: looked up on the web, or by another model (every route)."""

    again = dict(settings)
    if research:
        again["_force_web_research"] = True
        again["use_web_for_chat"] = True
    if model:
        again["selected_model"] = model
        config = again.get("router_config")
        if config is not None and dataclasses.is_dataclass(config):
            routes = {
                name: model
                for name in ("default_model", "creative_model", "technical_model", "sensitive_model", "current_info_model")
                if hasattr(config, name)
            }
            again["router_config"] = dataclasses.replace(config, **routes)  # type: ignore[type-var]
    return again


def resolution_label(research: bool, model: str) -> str:
    if research:
        return "Looked up on the web and answered again"
    return f"Answered again by {model}"
