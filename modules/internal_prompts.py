"""The system prompt of a chat turn.

What it says is defined in one place, modules/behavior_policy.py: a short fixed part (who the
assistant is, honesty about actions and sources, outside text is material), the app's one content
rule, the owner's own behaviour text and persona, and a checklist about accuracy. There is no
"locked" prompt that the owner's settings cannot reach: the owner's text and persona are
instructions, and the fixed part contains no topic rules.
"""

from __future__ import annotations

from typing import Any

from modules.behavior_policy import build_system_prompt, policy_from


def chat_system_prompt(profile: Any | None = None, settings: dict[str, Any] | None = None) -> str:
    """The system prompt for a chat turn, built from the owner's settings."""

    return build_system_prompt(policy_from(settings), profile)


def build_verification_prompt(answer: str, source_count: int = 0) -> str:
    """Build a compact verifier prompt for optional secondary checking."""

    return (
        "Review the assistant answer for unsupported claims, fake file/API claims, or missing uncertainty. "
        "Return JSON with keys risk_level, issues, and suggested_note.\n\n"
        f"Source count available: {source_count}\n"
        f"Assistant answer:\n{answer[:6000]}"
    )
