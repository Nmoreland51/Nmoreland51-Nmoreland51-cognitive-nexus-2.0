"""Long-context packing for Cognitive Nexus chat turns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.reality_grounding.prompt_firewall import build_firewall_instruction, sandbox_content


USER_PROFILE_FILE = Path("data/user_profile.json")
MAX_USER_FACTS = 60


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


def load_user_facts(path: Path | None = None) -> list[str]:
    """Load persisted user/project facts for context preservation."""

    resolved = path or USER_PROFILE_FILE
    try:
        if not resolved.exists():
            return []
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        if isinstance(facts, list):
            cleaned_facts = []
            for fact in facts:
                text = _fact_text(fact)
                if text:
                    cleaned_facts.append(text)
            return cleaned_facts
    except Exception:
        return []
    return []


def _timestamp() -> str:
    return datetime.now().isoformat()


def _normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text).lower())).strip()


def _fact_text(fact: Any) -> str:
    if isinstance(fact, dict):
        return str(fact.get("text") or fact.get("value") or "").strip()
    return str(fact or "").strip()


def load_user_profile(path: Path | None = None) -> dict[str, Any]:
    """Load the persistent local profile, preserving unknown keys."""

    resolved = path or USER_PROFILE_FILE
    try:
        if resolved.exists():
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("facts", [])
                payload.setdefault("preferences", {})
                payload.setdefault("patterns", {})
                payload.setdefault("recurring_topics", {})
                payload.setdefault("recent_feedback", [])
                return payload
    except Exception:
        pass
    return {
        "facts": [],
        "preferences": {},
        "patterns": {},
        "recurring_topics": {},
        "recent_feedback": [],
        "updated_at": _timestamp(),
    }


def save_user_profile(profile: dict[str, Any], path: Path | None = None) -> None:
    resolved = path or USER_PROFILE_FILE
    resolved.parent.mkdir(parents=True, exist_ok=True)
    profile["updated_at"] = _timestamp()
    resolved.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


def remember_user_fact(text: str, path: Path | None = None, source: str = "explicit_chat_memory") -> dict[str, Any]:
    """Persist a user-approved fact to local JSON memory."""

    content = " ".join(str(text or "").strip().split())
    if not content:
        return {"success": False, "action": "remember", "message": "Tell me what you want me to remember."}

    profile = load_user_profile(path)
    facts = profile.get("facts", [])
    if not isinstance(facts, list):
        facts = []
    normalized = _normalize_memory_text(content)
    existing = [fact for fact in facts if _normalize_memory_text(_fact_text(fact)) != normalized]
    entry = {
        "id": f"fact_{abs(hash(normalized)) % 10_000_000:07d}",
        "text": content,
        "kind": "explicit",
        "source": source,
        "updated_at": _timestamp(),
    }
    existing.append(entry)
    profile["facts"] = existing[-MAX_USER_FACTS:]
    save_user_profile(profile, path)
    return {
        "success": True,
        "action": "remember",
        "message": f"I'll remember that: {content}",
        "fact": entry,
        "fact_count": len(profile["facts"]),
    }


def forget_user_fact(query: str, path: Path | None = None) -> dict[str, Any]:
    """Remove matching local profile facts."""

    needle = _normalize_memory_text(query)
    if not needle:
        return {"success": False, "action": "forget", "message": "Tell me which saved memory to forget."}
    terms = [term for term in needle.split() if term]
    profile = load_user_profile(path)
    facts = profile.get("facts", [])
    if not isinstance(facts, list):
        facts = []

    def matches(fact: Any) -> bool:
        text = _normalize_memory_text(_fact_text(fact))
        return needle in text or all(term in text for term in terms)

    kept = [fact for fact in facts if not matches(fact)]
    removed = len(facts) - len(kept)
    profile["facts"] = kept
    save_user_profile(profile, path)
    if removed:
        return {
            "success": True,
            "action": "forget",
            "message": f"I forgot {removed} matching saved memory item(s).",
            "removed": removed,
            "fact_count": len(kept),
        }
    return {
        "success": False,
        "action": "forget",
        "message": "I couldn't find a matching saved memory to forget.",
        "removed": 0,
        "fact_count": len(kept),
    }


def load_user_profile_summary(path: Path | None = None, limit: int = 12) -> dict[str, Any]:
    """Return dashboard-ready memory rows from the local profile."""

    profile = load_user_profile(path)
    facts = profile.get("facts", [])
    facts = facts if isinstance(facts, list) else []
    fact_rows = []
    for fact in facts[-limit:]:
        if isinstance(fact, dict):
            fact_rows.append(
                {
                    "text": _fact_text(fact),
                    "kind": fact.get("kind", ""),
                    "source": fact.get("source", ""),
                    "updated_at": fact.get("updated_at", ""),
                }
            )
        else:
            fact_rows.append({"text": _fact_text(fact), "kind": "legacy", "source": "", "updated_at": ""})
    preferences = profile.get("preferences", {})
    patterns = profile.get("patterns", {})
    return {
        "fact_count": len([fact for fact in facts if _fact_text(fact)]),
        "facts": fact_rows,
        "preference_count": len(preferences) if isinstance(preferences, dict) else 0,
        "pattern_count": len(patterns) if isinstance(patterns, dict) else 0,
        "updated_at": profile.get("updated_at", ""),
    }


def handle_local_memory_command(message: str, path: Path | None = None) -> dict[str, Any] | None:
    """Handle explicit local memory commands without requiring a model provider."""

    text = str(message or "").strip()
    remember_match = re.match(
        r"^\s*(?:please\s+)?remember(?:\s+(?:this|that))?(?:\s*:\s*|\s+)(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if remember_match:
        return remember_user_fact(remember_match.group(1), path=path)

    forget_match = re.match(
        r"^\s*(?:please\s+)?forget(?:\s+(?:this|that))?(?:\s*:\s*|\s+)(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if forget_match:
        return forget_user_fact(forget_match.group(1), path=path)

    if re.search(r"\bwhat do you remember\b|\bshow saved memor(?:y|ies)\b|\blist saved memor(?:y|ies)\b", text, flags=re.IGNORECASE):
        facts = load_user_facts(path or USER_PROFILE_FILE)
        if not facts:
            return {
                "success": True,
                "action": "recall",
                "message": "I do not have any saved local facts yet.",
                "fact_count": 0,
            }
        shown = facts[-12:]
        return {
            "success": True,
            "action": "recall",
            "message": "Saved local facts:\n" + "\n".join(f"- {fact}" for fact in shown),
            "fact_count": len(facts),
        }

    return None


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

    trust_audit: dict[str, Any] = {}
    facts_text = ""
    if user_facts:
        relevant_facts = []
        if route_label.lower().startswith("standard conversation"):
            relevant_facts = [fact for fact in user_facts[-20:] if _is_relevant_fact(user_message, fact)]
        else:
            relevant_facts = list(user_facts[-20:])

        if relevant_facts:
            sandboxed_facts = []
            fact_audits = []
            for fact in relevant_facts[-6:]:
                wrapped, audit = sandbox_content(f"- {fact}", "memory", "persistent fact")
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
        user_facts=user_facts,
        estimated_tokens=estimate_tokens(prompt),
        trimmed=trimmed,
        trust_audit=trust_audit,
    )
