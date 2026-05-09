"""Long-context packing for Cognitive Nexus chat turns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


USER_PROFILE_FILE = Path("data/user_profile.json")


@dataclass
class ContextBundle:
    """A compact prompt bundle sent to a provider."""

    prompt: str
    recent_history: list[dict[str, str]]
    older_summary: str = ""
    memory_context: str = ""
    retrieved_context: str = ""
    user_facts: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    trimmed: bool = False


def estimate_tokens(text: str) -> int:
    """Fast token estimate good enough for trimming decisions."""

    return max(1, len(text or "") // 4)


def trim_text(text: str, max_chars: int) -> str:
    """Trim text at a word boundary when practical."""

    text = text or ""
    if len(text) <= max_chars:
        return text
    clipped = text[: max(0, max_chars - 24)].rsplit(" ", 1)[0]
    return f"{clipped}\n[trimmed]"


def _message_text(message: dict[str, Any]) -> str:
    role = str(message.get("role", "user")).strip() or "user"
    content = str(message.get("content", "")).strip()
    return f"{role.title()}: {content}"


def summarize_older_messages(messages: Iterable[dict[str, Any]], max_chars: int = 1800) -> str:
    """Create a deterministic short summary of older chat without another model call."""

    parts = []
    for message in messages:
        content = re.sub(r"\s+", " ", str(message.get("content", "")).strip())
        if not content:
            continue
        role = str(message.get("role", "user")).title()
        parts.append(f"- {role}: {content[:240]}")
    if not parts:
        return ""
    return trim_text("Older conversation summary:\n" + "\n".join(parts), max_chars)


def load_user_facts(path: Path = USER_PROFILE_FILE) -> list[str]:
    """Load persisted user/project facts for context preservation."""

    try:
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        if isinstance(facts, list):
            return [str(fact) for fact in facts if str(fact).strip()]
    except Exception:
        return []
    return []


def build_context_bundle(
    *,
    user_message: str,
    messages: list[dict[str, str]],
    system_prompt: str,
    route_label: str,
    route_reason: str = "",
    memory_context: str = "",
    retrieved_context: str = "",
    user_facts: list[str] | None = None,
    max_context_chars: int = 12000,
    recent_message_limit: int = 8,
    summary_message_limit: int = 18,
) -> ContextBundle:
    """Pack recent chat, older summary, memory, and retrieved context into one prompt."""

    user_facts = user_facts if user_facts is not None else load_user_facts()
    prior_messages = list(messages[:-1]) if messages and messages[-1].get("content") == user_message else list(messages)
    recent_history = prior_messages[-recent_message_limit:] if recent_message_limit > 0 else []
    older_window = prior_messages[-(summary_message_limit + recent_message_limit) : -recent_message_limit]
    older_summary = summarize_older_messages(older_window)

    facts_text = ""
    if user_facts:
        facts_text = "Persistent facts:\n" + "\n".join(f"- {fact}" for fact in user_facts[-20:])

    recent_text = "\n".join(_message_text(message) for message in recent_history)
    memory_text = trim_text(memory_context, 2200)
    retrieved_text = trim_text(retrieved_context, 3200)

    sections = [
        system_prompt.strip(),
        f"Active route: {route_label}",
        f"Route reason: {route_reason}" if route_reason else "",
        facts_text,
        older_summary,
        f"Relevant memory:\n{memory_text}" if memory_text else "",
        f"Relevant files/knowledge:\n{retrieved_text}" if retrieved_text else "",
        f"Recent conversation:\n{recent_text}" if recent_text else "",
        f"User request:\n{user_message}",
        "Final answer:",
    ]
    prompt = "\n\n".join(section for section in sections if section.strip())
    trimmed = False
    if len(prompt) > max_context_chars:
        trimmed = True
        overflow = len(prompt) - max_context_chars
        retrieved_text = trim_text(retrieved_text, max(700, len(retrieved_text) - overflow))
        sections[6] = f"Relevant files/knowledge:\n{retrieved_text}" if retrieved_text else ""
        prompt = "\n\n".join(section for section in sections if section.strip())
    if len(prompt) > max_context_chars:
        trimmed = True
        memory_text = trim_text(memory_text, 700)
        older_summary = trim_text(older_summary, 600)
        sections[4] = older_summary
        sections[5] = f"Relevant memory:\n{memory_text}" if memory_text else ""
        prompt = "\n\n".join(section for section in sections if section.strip())
    if len(prompt) > max_context_chars:
        trimmed = True
        protected_tail = f"\n\nUser request:\n{user_message}\n\nFinal answer:"
        head_budget = max(500, max_context_chars - len(protected_tail) - 16)
        prompt = trim_text(prompt, head_budget) + protected_tail

    return ContextBundle(
        prompt=prompt,
        recent_history=recent_history,
        older_summary=older_summary,
        memory_context=memory_text,
        retrieved_context=retrieved_text,
        user_facts=user_facts,
        estimated_tokens=estimate_tokens(prompt),
        trimmed=trimmed,
    )
