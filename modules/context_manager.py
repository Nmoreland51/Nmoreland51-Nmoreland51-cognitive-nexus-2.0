"""Long-context packing for Cognitive Nexus chat turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from core.reality_grounding.prompt_firewall import build_firewall_instruction, sandbox_content
from modules import profile_store
from modules.profile_store import KIND_LABELS

# The saved profile is read and written only through modules/profile_store.py.
USER_PROFILE_FILE = profile_store.PROFILE_FILE


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
    trust_audit: dict[str, Any] = field(default_factory=dict)


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


def _tokenize_relevant_text(text: str) -> set[str]:
    normalized = re.sub(r'[^a-z0-9\s]', ' ', str(text or "").lower())
    tokens = {token for token in normalized.split() if len(token) > 2}
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "have", "your",
        "about", "their", "there", "what", "when", "where", "which", "also",
        "will", "been", "more", "can", "should", "could",
    }
    return tokens - stop_words


def _is_relevant_fact(user_message: str, fact: str) -> bool:
    user_tokens = _tokenize_relevant_text(user_message)
    fact_tokens = _tokenize_relevant_text(fact)
    if not user_tokens or not fact_tokens:
        return False
    intersect = user_tokens & fact_tokens
    if len(intersect) >= 2:
        return True
    if user_tokens & {"name", "nickname", "alias", "email", "phone"}:
        return False
    return bool(intersect)


def _message_text(message: dict[str, Any]) -> str:
    role = str(message.get("role", "user")).strip() or "user"
    content = str(message.get("content", "")).strip()
    source_type = "assistant" if role == "assistant" else "user"
    wrapped, _audit = sandbox_content(content, source_type, f"{role} conversation turn")
    return f"{role.title()}:\n{wrapped}"


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


def load_user_fact_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Saved facts that are in use (not replaced, not expired), oldest first."""

    try:
        return profile_store.active_facts(profile_store.load_profile(path or USER_PROFILE_FILE))
    except Exception:
        return []


def load_user_facts(path: Path | None = None) -> list[str]:
    """Text of the saved facts that are in use."""

    return [str(fact.get("text") or "") for fact in load_user_fact_records(path) if fact.get("text")]


def load_user_profile(path: Path | None = None) -> dict[str, Any]:
    """Load the saved profile (migrated to the current schema), preserving unknown keys."""

    return profile_store.load_profile(path or USER_PROFILE_FILE)


def remember_user_fact(
    text: str,
    path: Path | None = None,
    source: str = "user_statement",
    *,
    expires_at: str | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    """Save something the user asked to have remembered."""

    if source.startswith("explicit"):
        source = "user_statement"  # names used before schema version 2
    return profile_store.remember(text, path=path or USER_PROFILE_FILE, source=source, expires_at=expires_at, replace=replace)


def forget_user_fact(query: str, path: Path | None = None) -> dict[str, Any]:
    """Remove saved facts that contain every distinctive word of the request, as whole words."""

    return profile_store.forget(query, path=path or USER_PROFILE_FILE)


def load_user_profile_summary(path: Path | None = None, limit: int = 12) -> dict[str, Any]:
    """Return dashboard-ready memory rows from the local profile."""

    profile = load_user_profile(path)
    active = profile_store.active_facts(profile)
    fact_rows = [
        {
            "text": str(fact.get("text") or ""),
            "kind": fact.get("kind", ""),
            "source": fact.get("source", ""),
            "confidence": fact.get("confidence", ""),
            "created_at": fact.get("created_at", ""),
            "last_confirmed": fact.get("last_verified_at") or "",
            "expires_at": fact.get("expires_at") or "",
            "updated_at": fact.get("updated_at", ""),
        }
        for fact in active[-limit:]
    ]
    preferences = profile.get("preferences", {})
    patterns = profile.get("patterns", {})
    facts = profile.get("facts", [])
    return {
        "fact_count": len(active),
        "facts": fact_rows,
        "replaced_count": sum(1 for fact in facts if fact.get("status") == "superseded"),
        "expired_count": sum(1 for fact in facts if fact.get("status") == "active" and profile_store.is_expired(fact)),
        "preference_count": len(preferences) if isinstance(preferences, dict) else 0,
        "pattern_count": len(patterns) if isinstance(patterns, dict) else 0,
        "schema_version": profile.get("schema_version"),
        "updated_at": profile.get("updated_at", ""),
    }


_EXPIRY_FOR = re.compile(
    r"^for\s+(?:the\s+next\s+)?(?P<count>\d{1,4}|an?|one)\s+(?P<unit>minute|hour|day|week|month)s?[,:]?\s+(?:that\s+)?(?P<text>.+)$",
    re.IGNORECASE,
)
_EXPIRY_UNTIL = re.compile(r"^until\s+(?P<date>\d{4}-\d{2}-\d{2})[,:]?\s+(?:that\s+)?(?P<text>.+)$", re.IGNORECASE)
_UNIT_HOURS = {"minute": 1 / 60, "hour": 1, "day": 24, "week": 24 * 7, "month": 24 * 30}


def split_expiry(text: str, now: datetime | None = None) -> tuple[str, str | None]:
    """Split "for 3 days that the office is closed" into the fact and when it stops applying."""

    current = now or datetime.now(timezone.utc)
    match = _EXPIRY_FOR.match(text.strip())
    if match:
        count_text = match.group("count").lower()
        count = 1 if count_text in {"a", "an", "one"} else int(count_text)
        expires = current + timedelta(hours=count * _UNIT_HOURS[match.group("unit").lower()])
        return match.group("text").strip(), expires.isoformat(timespec="seconds")
    match = _EXPIRY_UNTIL.match(text.strip())
    if match:
        try:
            day = datetime.fromisoformat(match.group("date")).replace(hour=23, minute=59, second=59, tzinfo=current.tzinfo)
        except ValueError:
            return text, None
        return match.group("text").strip(), day.isoformat(timespec="seconds")
    return text, None


def handle_local_memory_command(message: str, path: Path | None = None) -> dict[str, Any] | None:
    """Handle explicit local memory commands without requiring a model provider.

    remember ...                         save it; a new value for the same thing replaces the old one
    remember also: ...                   save it and keep the earlier value too
    remember for 3 days that ...         save it with an end date (also: remember until 2026-12-01 ...)
    forget ...                           remove it, its history and related records
    what do you remember                 list what is saved, with how each item is known
    """

    text = str(message or "").strip()
    remember_match = re.match(
        r"^\s*(?:please\s+)?(?:also\s+)?remember(?P<also>\s+also)?(?:\s+(?:this|that))?(?:\s*:\s*|\s+)(?P<rest>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if remember_match:
        keep_both = bool(remember_match.group("also")) or bool(re.match(r"^\s*(?:please\s+)?also\s+remember", text, flags=re.IGNORECASE))
        content, expires_at = split_expiry(remember_match.group("rest"))
        return remember_user_fact(content, path=path, expires_at=expires_at, replace=not keep_both)

    forget_match = re.match(
        r"^\s*(?:please\s+)?forget(?:\s+(?:this|that))?(?:\s*:\s*|\s+)(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if forget_match:
        return forget_user_fact(forget_match.group(1), path=path)

    if re.search(r"\bwhat do you remember\b|\bshow saved memor(?:y|ies)\b|\blist saved memor(?:y|ies)\b", text, flags=re.IGNORECASE):
        records = load_user_fact_records(path or USER_PROFILE_FILE)
        if not records:
            return {
                "success": True,
                "action": "recall",
                "message": "I do not have any saved local facts yet.",
                "fact_count": 0,
            }
        shown = records[-12:]
        lines = []
        for fact in shown:
            label = KIND_LABELS.get(str(fact.get("kind")), "saved")
            until = f", until {str(fact['expires_at'])[:10]}" if fact.get("expires_at") else ""
            lines.append(f"- {fact.get('text')} ({label}{until})")
        return {
            "success": True,
            "action": "recall",
            "message": "Saved local facts:\n" + "\n".join(lines),
            "fact_count": len(records),
        }

    return None


def _fact_parts(fact: Any) -> tuple[str, str]:
    """(text, kind) of a saved fact given as a record or as plain text."""

    if isinstance(fact, dict):
        return str(fact.get("text") or "").strip(), str(fact.get("kind") or "fact")
    return str(fact or "").strip(), ""


def build_context_bundle(
    *,
    user_message: str,
    messages: list[dict[str, str]],
    system_prompt: str,
    route_label: str,
    route_reason: str = "",
    memory_context: str = "",
    retrieved_context: str = "",
    user_facts: list[Any] | None = None,
    max_context_chars: int = 12000,
    recent_message_limit: int = 8,
    summary_message_limit: int = 18,
) -> ContextBundle:
    """Pack recent chat, older summary, memory, and retrieved context into one prompt."""

    # Records carry how each fact is known; plain strings (older callers) are accepted too.
    user_facts = user_facts if user_facts is not None else load_user_fact_records()
    fact_parts = [parts for parts in (_fact_parts(fact) for fact in user_facts) if parts[0]]
    prior_messages = list(messages[:-1]) if messages and messages[-1].get("content") == user_message else list(messages)
    recent_history = prior_messages[-recent_message_limit:] if recent_message_limit > 0 else []
    older_window = prior_messages[-(summary_message_limit + recent_message_limit) : -recent_message_limit]
    older_summary = summarize_older_messages(older_window)

    trust_audit: dict[str, Any] = {}
    facts_text = ""
    if fact_parts:
        # Standing instructions ("call me Sam") apply to every turn. Other facts are included
        # when they relate to the message; outside casual chat the most recent ones are included.
        instructions = [parts for parts in fact_parts if parts[1] == "instruction"][-4:]
        others = [parts for parts in fact_parts if parts[1] != "instruction"][-20:]
        if route_label.lower().startswith("standard conversation"):
            others = [parts for parts in others if _is_relevant_fact(user_message, parts[0])]
        relevant_facts = instructions + others[-6:]

        if relevant_facts:
            sandboxed_facts = []
            fact_audits = []
            for text, kind in relevant_facts:
                # Saying how a fact is known lets the model treat a guess differently from
                # something the user stated.
                label = f"[{KIND_LABELS[kind]}] " if kind in KIND_LABELS else ""
                wrapped, audit = sandbox_content(f"- {label}{text}", "memory", "persistent fact")
                sandboxed_facts.append(wrapped)
                fact_audits.append(audit.to_dict())
            facts_text = "Persistent facts:\n" + "\n".join(sandboxed_facts)
            trust_audit["persistent_facts"] = fact_audits

    recent_text = "\n".join(_message_text(message) for message in recent_history)
    memory_text = trim_text(memory_context, 2200)
    retrieved_text = trim_text(retrieved_context, 3200)
    memory_wrapped = ""
    retrieved_wrapped = ""
    user_wrapped, user_audit = sandbox_content(user_message, "user", "current user request")
    trust_audit["user_request"] = user_audit.to_dict()
    if memory_text:
        memory_wrapped, memory_audit = sandbox_content(memory_text, "memory", "memory context")
        trust_audit["memory_context"] = memory_audit.to_dict()
    if retrieved_text:
        retrieved_wrapped, retrieved_audit = sandbox_content(retrieved_text, "retrieved", "retrieved knowledge")
        trust_audit["retrieved_context"] = retrieved_audit.to_dict()

    sections = [
        system_prompt.strip(),
        build_firewall_instruction(),
        f"Active route: {route_label}",
        f"Route reason: {route_reason}" if route_reason else "",
        facts_text,
        older_summary,
        f"Relevant memory:\n{memory_wrapped}" if memory_wrapped else "",
        f"Relevant files/knowledge:\n{retrieved_wrapped}" if retrieved_wrapped else "",
        f"Recent conversation:\n{recent_text}" if recent_text else "",
        f"User request:\n{user_wrapped}",
        "Final answer:",
    ]
    prompt = "\n\n".join(section for section in sections if section.strip())
    trimmed = False
    if len(prompt) > max_context_chars:
        trimmed = True
        overflow = len(prompt) - max_context_chars
        retrieved_wrapped = trim_text(retrieved_wrapped, max(700, len(retrieved_wrapped) - overflow))
        sections[7] = f"Relevant files/knowledge:\n{retrieved_wrapped}" if retrieved_wrapped else ""
        prompt = "\n\n".join(section for section in sections if section.strip())
    if len(prompt) > max_context_chars:
        trimmed = True
        memory_wrapped = trim_text(memory_wrapped, 700)
        older_summary = trim_text(older_summary, 600)
        sections[5] = older_summary
        sections[6] = f"Relevant memory:\n{memory_wrapped}" if memory_wrapped else ""
        prompt = "\n\n".join(section for section in sections if section.strip())
    if len(prompt) > max_context_chars:
        trimmed = True
        protected_tail = f"\n\nUser request:\n{user_wrapped}\n\nFinal answer:"
        head_budget = max(500, max_context_chars - len(protected_tail) - 16)
        prompt = trim_text(prompt, head_budget) + protected_tail

    return ContextBundle(
        prompt=prompt,
        recent_history=recent_history,
        older_summary=older_summary,
        memory_context=memory_text,
        retrieved_context=retrieved_text,
        user_facts=[text for text, _kind in fact_parts],
        estimated_tokens=estimate_tokens(prompt),
        trimmed=trimmed,
        trust_audit=trust_audit,
    )
