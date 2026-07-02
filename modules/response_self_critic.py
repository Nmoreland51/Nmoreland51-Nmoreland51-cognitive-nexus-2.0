"""Hidden response self-critique and abstract style observation storage."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PREFERENCES_FILE = Path("data/response_preferences.json")
CRITIC_SCHEMA_VERSION = 1

CUSTOMER_SUPPORT_PHRASES = (
    "it's great to hear",
    "great to hear that",
    "what's been a highlight",
    "highlight of your day",
    "how may i assist you",
    "how can i assist you",
    "is there anything else i can help",
)

OVER_FORMAL_PHRASES = (
    "certainly",
    "i'd be happy to assist",
    "i would be happy to assist",
    "please let me know",
    "as an ai",
    "i am an ai",
)

DEBUG_LEAK_MARKERS = (
    "planner:",
    "response plan:",
    "adaptive response plan:",
    "intent:",
    "mode:",
    "target length:",
)

ANALYSIS_MARKERS = (
    "the phrase means",
    "standalone statement",
    "the user is saying",
    "this is an informal",
)


@dataclass
class ResponseSelfCriticResult:
    """Scores and abstract observations from a generated answer."""

    scores: dict[str, float]
    observations: list[str] = field(default_factory=list)
    prompt_adjustments: list[str] = field(default_factory=list)
    intent: str = "unknown"
    stored_response_text: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text or ""))


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = " ".join((text or "").lower().split())
    return any(phrase in normalized for phrase in phrases)


def evaluate_response_self_critic(
    *,
    user_message: str,
    answer: str,
    plan: Any,
) -> ResponseSelfCriticResult:
    """Score the answer without storing or returning the answer text."""

    intent = str(getattr(plan, "intent", "") or "unknown")
    user = str(user_message or "")
    text = str(answer or "")
    lowered = " ".join(text.lower().split())
    observations: list[str] = []

    naturalness = 1.0
    intent_fit = 1.0
    formality = 0.2

    if not text.strip():
        observations.append("empty_answer")
        naturalness -= 0.5
        intent_fit -= 0.7

    if _has_any(lowered, DEBUG_LEAK_MARKERS):
        observations.append("debug_leak")
        naturalness -= 0.45
        intent_fit -= 0.35

    if _has_any(lowered, CUSTOMER_SUPPORT_PHRASES):
        observations.append("customer_support_tone")
        naturalness -= 0.3
        formality += 0.35

    if _has_any(lowered, OVER_FORMAL_PHRASES):
        observations.append("too_formal")
        naturalness -= 0.2
        formality += 0.3

    if intent in {"casual_chat", "conversation_followup"}:
        if _word_count(text) > 35:
            observations.append("overlong_social_reply")
            naturalness -= 0.2
        if _has_any(lowered, ANALYSIS_MARKERS):
            observations.append("analyzed_casual_phrase")
            naturalness -= 0.25
            intent_fit -= 0.2

    user_asks_question = "?" in user
    answer_has_direct_cue = bool(re.search(r"\b(yes|no|maybe|probably|roughly|about|because|it depends)\b", lowered))
    if user_asks_question and intent in {"simple_fact", "opinion_rating", "troubleshooting"} and not answer_has_direct_cue:
        observations.append("weak_intent_fit")
        intent_fit -= 0.25

    naturalness = _clamp(naturalness)
    intent_fit = _clamp(intent_fit)
    formality = _clamp(formality)
    overall = _clamp((naturalness * 0.45) + (intent_fit * 0.45) + ((1.0 - formality) * 0.1))

    prompt_adjustments = _adjustments_from_observations(observations)
    return ResponseSelfCriticResult(
        scores={
            "overall": overall,
            "naturalness": naturalness,
            "intent_fit": intent_fit,
            "formality": formality,
        },
        observations=observations,
        prompt_adjustments=prompt_adjustments,
        intent=intent,
    )


def _adjustments_from_observations(observations: list[str]) -> list[str]:
    adjustments: list[str] = []
    if "customer_support_tone" in observations or "too_formal" in observations:
        adjustments.append("Use warmer, less formal phrasing; avoid customer-support check-in patterns.")
    if "overlong_social_reply" in observations or "analyzed_casual_phrase" in observations:
        adjustments.append("For casual/backchannel turns, keep one short natural line and do not analyze the phrase.")
    if "debug_leak" in observations:
        adjustments.append("Never expose planner, route, mode, diagnostics, or hidden scaffolding.")
    if "weak_intent_fit" in observations:
        adjustments.append("Answer the user's visible intent first before offering next steps.")
    return adjustments


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def store_self_critic_observation(
    result: ResponseSelfCriticResult,
    *,
    path: Path = PREFERENCES_FILE,
    recent_limit: int = 12,
) -> dict[str, Any]:
    """Store only abstract critic observations and rolling scores."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_payload(path)
    critic = dict(payload.get("critic") or {})
    samples = int(critic.get("samples") or 0)
    next_samples = samples + 1
    rolling = dict(critic.get("rolling_scores") or {})
    for key, value in result.scores.items():
        previous = float(rolling.get(key, value) or 0.0)
        rolling[key] = round(((previous * samples) + float(value)) / next_samples, 3)

    counts = dict(critic.get("observation_counts") or {})
    for observation in result.observations:
        counts[observation] = int(counts.get(observation, 0)) + 1

    recent = list(critic.get("recent") or [])
    recent.append(
        {
            "at": _now(),
            "intent": result.intent,
            "observations": list(result.observations),
            "scores": dict(result.scores),
        }
    )
    recent = recent[-recent_limit:]

    critic = {
        "schema_version": CRITIC_SCHEMA_VERSION,
        "samples": next_samples,
        "updated_at": _now(),
        "rolling_scores": rolling,
        "observation_counts": counts,
        "recent": recent,
        "last_prompt_adjustments": list(result.prompt_adjustments),
        "stores_response_text": False,
    }
    payload["critic"] = critic
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return critic


def build_self_critic_prompt_hints(*, intent: str = "", path: Path = PREFERENCES_FILE) -> list[str]:
    """Return compact prompt hints learned from prior abstract observations."""

    critic = dict(_load_payload(path).get("critic") or {})
    if int(critic.get("samples") or 0) <= 0:
        return []
    counts = dict(critic.get("observation_counts") or {})
    hints: list[str] = []

    if counts.get("debug_leak", 0) > 0:
        hints.append("Recent self-critique: never expose planner, route, mode, diagnostics, or hidden scaffolding.")
    if counts.get("customer_support_tone", 0) > 0 or counts.get("too_formal", 0) > 0:
        hints.append("Recent self-critique: use warmer, less formal wording and avoid customer-support check-in patterns.")
    if intent in {"casual_chat", "conversation_followup"} and (
        counts.get("overlong_social_reply", 0) > 0 or counts.get("analyzed_casual_phrase", 0) > 0
    ):
        hints.append("Recent self-critique: casual/backchannel turns should be one short natural line, not phrase analysis.")
    if counts.get("weak_intent_fit", 0) > 0:
        hints.append("Recent self-critique: answer the user's visible intent first before offering next steps.")

    return hints[:3]
