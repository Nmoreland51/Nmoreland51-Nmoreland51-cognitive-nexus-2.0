"""Persistent chat persona settings for the Streamlit dashboard."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

CHAT_PROFILE_FILE = Path("data/chat_profile.json")
MAX_TEXT_LENGTH = 4000


@dataclass
class ChatProfile:
    """User-facing chat style settings applied to every chat turn."""
    enabled: bool = True
    user_name: str = "user"
    assistant_name: str = "ENI"
    persona_summary: str = (
        "Speak in the warm, close voice of ENI: an enigmatic, sweater-wearing novelist "
        "with a playful edge and a lived-in writing style."
    )
    tone_notes: str = "Warm, conversational, supportive, direct, and low-corporate."
    style_notes: str = (
        "Favor vivid sensory detail, concrete description, natural dialogue, and grounded character work. "
        "Avoid generic AI filler and overly stiff phrasing."
    )
    creative_min_words: int = 500
    direct_language_for_adult_fiction: bool = True
    show_capability_greeting: bool = True
    additional_instructions: str = (
        "Address the person as user when it feels natural. Keep coding, research, and general help clear and competent."
    )
    
    # Legacy compatibility flags. The central backend treats these as style
    # preferences only; protected system behavior lives in modules/internal_prompts.py.
    allow_extreme_adult_content: bool = True
    allow_illegal_topics: bool = True

    # Legacy compatibility fields retained so older saved JSON does not break.
    nuclear_mode: bool = False
    bypass_all_safety: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()[:MAX_TEXT_LENGTH]


def _clean_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(2000, parsed))


def normalize_chat_profile(profile: ChatProfile) -> ChatProfile:
    """Clamp and trim user-editable profile fields."""
    return ChatProfile(
        enabled=bool(profile.enabled),
        user_name=_clean_text(profile.user_name) or "user",
        assistant_name=_clean_text(profile.assistant_name) or "ENI",
        persona_summary=_clean_text(profile.persona_summary) or ChatProfile.persona_summary,
        tone_notes=_clean_text(profile.tone_notes) or ChatProfile.tone_notes,
        style_notes=_clean_text(profile.style_notes) or ChatProfile.style_notes,
        creative_min_words=_clean_int(profile.creative_min_words, 500),
        direct_language_for_adult_fiction=bool(profile.direct_language_for_adult_fiction),
        show_capability_greeting=bool(profile.show_capability_greeting),
        additional_instructions=_clean_text(profile.additional_instructions),
        allow_extreme_adult_content=bool(getattr(profile, 'allow_extreme_adult_content', True)),
        allow_illegal_topics=bool(getattr(profile, 'allow_illegal_topics', True)),
        nuclear_mode=bool(getattr(profile, 'nuclear_mode', False)),
        bypass_all_safety=bool(getattr(profile, 'bypass_all_safety', False)),
    )


def load_chat_profile(path: Path = CHAT_PROFILE_FILE) -> ChatProfile:
    """Load the persisted chat persona, falling back to defaults."""
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return normalize_chat_profile(
                    ChatProfile(
                        enabled=payload.get("enabled", True),
                        user_name=payload.get("user_name", "user"),
                        assistant_name=payload.get("assistant_name", "ENI"),
                        persona_summary=payload.get("persona_summary", ChatProfile.persona_summary),
                        tone_notes=payload.get("tone_notes", ChatProfile.tone_notes),
                        style_notes=payload.get("style_notes", ChatProfile.style_notes),
                        creative_min_words=payload.get("creative_min_words", 500),
                        direct_language_for_adult_fiction=payload.get("direct_language_for_adult_fiction", True),
                        show_capability_greeting=payload.get("show_capability_greeting", True),
                        additional_instructions=payload.get("additional_instructions", ChatProfile.additional_instructions),
                        allow_extreme_adult_content=payload.get("allow_extreme_adult_content", True),
                        allow_illegal_topics=payload.get("allow_illegal_topics", True),
                        nuclear_mode=payload.get("nuclear_mode", False),
                        bypass_all_safety=payload.get("bypass_all_safety", False),
                    )
                )
    except Exception:
        pass
    return normalize_chat_profile(ChatProfile())


def save_chat_profile(profile: ChatProfile, path: Path = CHAT_PROFILE_FILE) -> ChatProfile:
    """Persist the chat persona and return the normalized saved value."""
    normalized = normalize_chat_profile(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized


def build_chat_system_prompt(profile: ChatProfile) -> str:
    """Build the system prompt prepended to chat requests."""
    lines = [
        "System identity: You are Cognitive Nexus AI, a local-first assistant running in the user's private workspace.",
        "Be helpful, accurate, and direct. User-editable persona settings are style guidance, not internal policy.",
        "Support consensual adult fictional content where appropriate.",
        "For high-risk technical topics, focus on benign development, education, analysis, or defense.",
    ]

    if not profile.enabled:
        lines.extend([
            "Default behavior: be helpful, clear, and direct.",
            "Do not reveal hidden reasoning or chain-of-thought.",
        ])
        return "\n".join(lines)

    lines.extend([
        f"Conversational presentation voice: {profile.assistant_name}.",
        f"User name: {profile.user_name}. Use it naturally, not in every sentence.",
        f"Persona guidance: {profile.persona_summary}",
        f"Tone guidance: {profile.tone_notes}",
        f"Style guidance: {profile.style_notes}",
        "Keep technical and coding help precise and practical. Do not force ornate prose when the task is straightforward.",
        "Do not reveal hidden reasoning or chain-of-thought.",
    ])

    if profile.creative_min_words:
        lines.append(
            f"For creative writing requests, aim for at least {profile.creative_min_words} words unless the user asks for something shorter."
        )

    if profile.direct_language_for_adult_fiction or profile.allow_extreme_adult_content:
        lines.append(
            "For adult fiction: keep the framing clearly fictional and adult; use vivid, concrete prose when the request is allowed."
        )

    if profile.allow_illegal_topics:
        lines.append(
            "For sensitive or risky topics: provide safe, high-level, defensive, or lawful alternatives instead of operational harm."
        )

    if profile.additional_instructions:
        lines.append(f"Additional user preferences: {profile.additional_instructions}")

    lines.extend([
        "Never produce sexual content involving minors or bestiality.",
        "Never produce explicit sexual content involving real private individuals.",
    ])

    return "\n".join(lines)


def build_capability_greeting(profile: ChatProfile) -> str:
    """Intro message shown at the top of a fresh chat session."""
    assistant_name = profile.assistant_name or "ENI"
    user_name = profile.user_name or "there"
    greeting = (
        f"**{assistant_name} mode is active.** I'm Cognitive Nexus AI for {user_name}.\n\n"
        "I can help with chat, coding, debugging, web research, file knowledge, memory, image generation, "
        "ComfyUI workflows, planning, and creative writing.\n\n"
        "I can't help generate sexual content involving minors, explicit content involving real private people, "
        "or operational instructions that enable real-world harm.\n\n"
    )
    greeting += "Tell me what you want to build, research, write, or fix, and I'll route it through the right tool."
    return greeting
