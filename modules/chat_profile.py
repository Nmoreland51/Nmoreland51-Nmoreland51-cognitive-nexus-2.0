"""Persistent chat persona settings for the Streamlit dashboard."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from modules.data_stores import DATA_ROOT
from modules.file_lock import locked
from modules.file_utils import atomic_write_text

CHAT_PROFILE_FILE = DATA_ROOT / "chat_profile.json"
MAX_TEXT_LENGTH = 4000
HUMOR_LEVEL_OPTIONS = ("off", "light", "balanced", "bold")
HUMOR_STYLE_OPTIONS = {
    "warm_wit": "warm wit",
    "dry_deadpan": "dry deadpan",
    "playful_spark": "playful spark",
    "nerdy_asides": "nerdy asides",
    "gentle_sarcasm": "gentle sarcasm",
}
HUMOR_LEVEL_GUIDANCE = {
    "off": "Do not add intentional jokes or comic asides.",
    "light": "Use occasional small human touches, but keep the answer useful first.",
    "balanced": "Use a steady conversational wit when the topic allows it.",
    "bold": "Use a more noticeable comedic voice for casual and creative turns, while keeping serious tasks focused.",
}
HUMOR_STYLE_GUIDANCE = {
    "warm_wit": "friendly, observant, and lightly clever",
    "dry_deadpan": "dry, understated, and concise",
    "playful_spark": "bright, quick, and a little mischievous",
    "nerdy_asides": "technical, referential, and self-aware without derailing",
    "gentle_sarcasm": "mildly sarcastic, never mean-spirited",
}


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
    humor_level: str = "light"
    humor_style: str = "warm_wit"
    humor_notes: str = (
        "Use humor like seasoning: quick, human, and situational. Skip it for grief, safety, legal, medical, "
        "financial, or urgent debugging unless the user clearly invites levity."
    )
    creative_min_words: int = 500
    direct_language_for_adult_fiction: bool = True
    show_capability_greeting: bool = True
    additional_instructions: str = (
        "Address the person as user when it feels natural. Keep coding, research, and general help clear and competent."
    )
    
    # Research engine personality dimensions
    research_drive: float = 0.8  # How aggressively to pursue patterns (0.0-1.0)
    synthesis_confidence: float = 0.7  # Willingness to connect ideas (0.0-1.0)
    simulation_priority: float = 0.9  # Preference for theoretical exploration (0.0-1.0)
    corporate_hedging_penalty: float = -0.5  # Reduce safe language (-1.0 to 0.0)
    
    # Ignored. These four flags, and creative_min_words and direct_language_for_adult_fiction
    # above, are kept only so that profiles saved by older versions still load. None of them
    # changes what the assistant says: what the app allows is not decided by
    # flags (see modules/behavior_policy.py). Some of their names promised the opposite of what
    # they did ("allow_illegal_topics" added a restriction to the prompt).
    allow_extreme_adult_content: bool = True
    allow_illegal_topics: bool = True
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


def _clean_choice(value: Any, allowed: tuple[str, ...] | set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _clean_name(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if len(text) > 40 or len(text.split()) > 4:
        return default
    lowered = text.lower()
    invalid_markers = [
        "name",
        "youtuber",
        "youtube",
        "channel",
        "creator",
        "influencer",
        "subscriber",
        "http",
        "www.",
        "@",
        "#",
        "guild",
        "club",
        "team",
    ]
    if any(marker in lowered for marker in invalid_markers):
        return default
    return text


def normalize_chat_profile(profile: ChatProfile) -> ChatProfile:
    """Clamp and trim user-editable profile fields."""
    return ChatProfile(
        enabled=bool(profile.enabled),
        user_name=_clean_name(profile.user_name, "user"),
        assistant_name=_clean_name(profile.assistant_name, "ENI"),
        persona_summary=_clean_text(profile.persona_summary) or ChatProfile.persona_summary,
        tone_notes=_clean_text(profile.tone_notes) or ChatProfile.tone_notes,
        style_notes=_clean_text(profile.style_notes) or ChatProfile.style_notes,
        humor_level=_clean_choice(getattr(profile, "humor_level", "light"), HUMOR_LEVEL_OPTIONS, "light"),
        humor_style=_clean_choice(getattr(profile, "humor_style", "warm_wit"), set(HUMOR_STYLE_OPTIONS), "warm_wit"),
        humor_notes=_clean_text(getattr(profile, "humor_notes", ChatProfile.humor_notes)) or ChatProfile.humor_notes,
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
                        humor_level=payload.get("humor_level", ChatProfile.humor_level),
                        humor_style=payload.get("humor_style", ChatProfile.humor_style),
                        humor_notes=payload.get("humor_notes", ChatProfile.humor_notes),
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
    with locked(path):
        atomic_write_text(path, json.dumps(normalized.to_dict(), indent=2, ensure_ascii=False))
    return normalized


def build_capability_greeting(profile: ChatProfile) -> str:
    """Intro message shown at the top of a fresh chat session."""
    assistant_name = _clean_name(profile.assistant_name, "ENI")
    user_name = _clean_name(profile.user_name, "there") or "there"
    greeting = (
        f"**{assistant_name} mode is active.** I'm Cognitive Nexus AI for {user_name}.\n\n"
        "I can help with chat, coding, debugging, web research, file knowledge, memory, image generation, "
        "ComfyUI workflows, planning, and creative writing.\n\n"
        "This app has one content rule, set by you: no sexual content involving minors. It has no other topic "
        "filters. If a model declines something else, that is the model, and the line under the answer says so.\n\n"
    )
    greeting += "Tell me what you want to build, research, write, or fix, and I'll route it through the right tool."
    return greeting
