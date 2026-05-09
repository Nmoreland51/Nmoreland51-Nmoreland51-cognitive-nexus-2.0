"""Adaptive response sizing and output planning for Cognitive Nexus."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PREFERENCES_FILE = Path("data/response_preferences.json")

RESPONSE_MODES = ["auto", "short", "standard", "deep", "surgeon", "research"]
INTENT_TYPES = [
    "casual_chat",
    "concise_answer",
    "detailed_explanation",
    "technical_debugging",
    "coding_request",
    "brainstorming",
    "emotional_support",
    "long_form_generation",
    "quick_fact",
    "comparison",
    "tutorial",
    "research_mode",
]


@dataclass
class ResponsePreferences:
    """Rolling response style preferences learned from user turns."""

    weights: dict[str, float] = field(default_factory=lambda: {
        "brevity": 0.0,
        "detail": 0.0,
        "code_examples": 0.0,
        "step_by_step": 0.0,
        "directness": 0.5,
        "low_fluff": 0.5,
    })
    samples: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResponsePlan:
    """Concrete plan for one generated response."""

    intent: str
    mode: str
    target_response_length: str
    target_depth: int
    formatting_style: str
    streaming_priority: str
    reasoning_intensity: int
    compression_level: str
    min_chars: int
    ideal_chars: int
    max_chars: int
    max_tokens: int
    num_ctx: int
    acknowledge: bool
    acknowledgement: str
    instructions: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_tokens(text: str) -> int:
    """Estimate tokens with a cheap chars/4 heuristic."""

    return max(1, len(text or "") // 4)


def _clean_mode(value: str | None) -> str:
    value = (value or "auto").strip().lower()
    return value if value in RESPONSE_MODES else "auto"


def _keyword_score(text: str, words: list[str]) -> int:
    return sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", text))


@lru_cache(maxsize=512)
def analyze_intent_cached(message: str, history_tail: str = "") -> dict[str, Any]:
    """Classify prompt intent with lightweight heuristics and no model call."""

    text = re.sub(r"\s+", " ", (message or "").strip().lower())
    words = text.split()
    word_count = len(words)
    question_marks = text.count("?")
    exclamations = text.count("!")
    scores = {intent: 0.0 for intent in INTENT_TYPES}

    scores["casual_chat"] += _keyword_score(text, ["hello", "hi", "hey", "thanks", "thank", "joke"])
    scores["concise_answer"] += _keyword_score(text, ["brief", "quick", "short", "concise", "simple", "summary"])
    scores["detailed_explanation"] += _keyword_score(text, ["explain", "detail", "deep", "thorough", "why", "how"])
    scores["technical_debugging"] += _keyword_score(text, ["traceback", "error", "bug", "fix", "broken", "debug", "exception"])
    scores["coding_request"] += _keyword_score(text, ["code", "function", "class", "refactor", "implement", "python", "streamlit", "api"])
    scores["brainstorming"] += _keyword_score(text, ["brainstorm", "ideas", "options", "alternatives", "names", "concepts"])
    scores["emotional_support"] += _keyword_score(text, ["stressed", "sad", "anxious", "panic", "overwhelmed", "hurt"])
    scores["long_form_generation"] += _keyword_score(text, ["write", "draft", "scene", "chapter", "story", "essay", "long-form"])
    scores["quick_fact"] += _keyword_score(text, ["what is", "who is", "when did", "define", "meaning"])
    scores["comparison"] += _keyword_score(text, ["compare", "versus", " vs ", "difference", "better", "pros", "cons"])
    scores["tutorial"] += _keyword_score(text, ["tutorial", "walkthrough", "step-by-step", "guide", "teach me"])
    scores["research_mode"] += _keyword_score(text, ["research", "sources", "latest", "current", "web", "evidence", "citations"])

    if word_count <= 5:
        scores["casual_chat"] += 0.8
        scores["quick_fact"] += 0.4 if question_marks else 0.0
    if word_count > 35:
        scores["detailed_explanation"] += 0.7
    if question_marks > 1:
        scores["detailed_explanation"] += 0.4
        scores["comparison"] += 0.2
    if exclamations:
        scores["emotional_support"] += min(exclamations * 0.1, 0.3)
    if "```" in message or "traceback" in text:
        scores["technical_debugging"] += 1.0
    if any(term in history_tail.lower() for term in ["debug", "traceback", "tests failed"]):
        scores["technical_debugging"] += 0.2

    intent = max(scores, key=scores.get)
    confidence = min(0.98, max(0.35, scores[intent] / 3.0))
    if scores[intent] <= 0:
        intent = "casual_chat" if word_count <= 8 else "detailed_explanation"
        confidence = 0.4

    return {
        "intent": intent,
        "confidence": round(confidence, 3),
        "scores": {key: round(value, 3) for key, value in scores.items() if value > 0},
        "word_count": word_count,
        "question_marks": question_marks,
    }


def load_response_preferences(path: Path = PREFERENCES_FILE) -> ResponsePreferences:
    """Load persistent response-style preferences."""

    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                weights = payload.get("weights", {})
                if isinstance(weights, dict):
                    prefs = ResponsePreferences()
                    prefs.weights.update({str(k): float(v) for k, v in weights.items()})
                    prefs.samples = int(payload.get("samples", 0))
                    prefs.updated_at = str(payload.get("updated_at", ""))
                    return prefs
    except Exception:
        pass
    return ResponsePreferences()


def save_response_preferences(preferences: ResponsePreferences, path: Path = PREFERENCES_FILE) -> None:
    """Persist response-style preferences."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preferences.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def update_response_preferences(
    message: str,
    current: ResponsePreferences | None = None,
    path: Path = PREFERENCES_FILE,
) -> ResponsePreferences:
    """Learn lightweight preferences from explicit user language."""

    prefs = current or load_response_preferences(path)
    text = (message or "").lower()
    adjustments = {
        "brevity": 0.0,
        "detail": 0.0,
        "code_examples": 0.0,
        "step_by_step": 0.0,
        "directness": 0.0,
        "low_fluff": 0.0,
    }
    if any(phrase in text for phrase in ["keep it short", "short answer", "be brief", "quick answer", "concise"]):
        adjustments["brevity"] += 0.25
        adjustments["detail"] -= 0.15
    if any(phrase in text for phrase in ["go deep", "more detail", "explain fully", "thorough", "long answer"]):
        adjustments["detail"] += 0.25
        adjustments["brevity"] -= 0.1
    if any(phrase in text for phrase in ["show code", "code example", "give me code", "full code"]):
        adjustments["code_examples"] += 0.2
    if any(phrase in text for phrase in ["step by step", "walk me through", "tutorial"]):
        adjustments["step_by_step"] += 0.2
    if any(phrase in text for phrase in ["no fluff", "direct", "straight to it", "don't ramble"]):
        adjustments["directness"] += 0.2
        adjustments["low_fluff"] += 0.2

    changed = False
    for key, delta in adjustments.items():
        if delta:
            changed = True
            prefs.weights[key] = max(-1.0, min(1.0, float(prefs.weights.get(key, 0.0)) + delta))
    if changed:
        prefs.samples += 1
        prefs.updated_at = datetime.now().isoformat()
        save_response_preferences(prefs, path)
    return prefs


def _provider_speed_class(settings: dict[str, Any]) -> str:
    order = list(settings.get("provider_order") or [])
    selected = str(settings.get("selected_model") or "").lower()
    if order and order[0] in {"openai", "anthropic"}:
        return "fast"
    if "70b" in selected or "13b" in selected:
        return "slow"
    if order and order[0] == "fallback":
        return "instant"
    if order and order[0] == "ollama":
        return "local"
    return "unknown"


def _auto_mode(intent: str, route_category: str, prefs: ResponsePreferences, manual_mode: str) -> str:
    manual_mode = _clean_mode(manual_mode)
    if manual_mode != "auto":
        return manual_mode
    if intent in {"technical_debugging", "coding_request"} or route_category == "coding_development":
        return "surgeon"
    if intent in {"research_mode", "comparison"} or route_category == "web_research":
        return "research"
    if intent in {"quick_fact", "concise_answer", "casual_chat"} or prefs.weights.get("brevity", 0) > 0.5:
        return "short"
    if intent in {"detailed_explanation", "tutorial", "long_form_generation", "brainstorming"}:
        return "deep"
    return "standard"


def _budget_for_mode(mode: str, intent: str) -> tuple[int, int, int]:
    budgets = {
        "short": (180, 550, 1000),
        "standard": (450, 1200, 2200),
        "deep": (1000, 2600, 5200),
        "surgeon": (350, 1100, 2400),
        "research": (900, 2400, 5200),
    }
    min_chars, ideal_chars, max_chars = budgets.get(mode, budgets["standard"])
    if intent == "long_form_generation":
        min_chars, ideal_chars, max_chars = max(min_chars, 1200), max(ideal_chars, 3200), max(max_chars, 6500)
    return min_chars, ideal_chars, max_chars


def plan_response(
    *,
    user_message: str,
    messages: list[dict[str, str]],
    route_category: str,
    route_reason: str = "",
    settings: dict[str, Any] | None = None,
) -> ResponsePlan:
    """Create a concrete response plan for one chat turn."""

    settings = settings or {}
    history_tail = "\n".join(str(item.get("content", ""))[-240:] for item in messages[-4:])
    analysis = analyze_intent_cached(user_message, history_tail)
    prefs = update_response_preferences(user_message)

    manual_mode = settings.get("response_mode", "auto")
    mode = _auto_mode(analysis["intent"], route_category, prefs, str(manual_mode))
    verbosity = int(settings.get("verbosity_level", 2))
    reasoning_depth = int(settings.get("reasoning_depth", 2))
    provider_speed = _provider_speed_class(settings)

    min_chars, ideal_chars, max_chars = _budget_for_mode(mode, analysis["intent"])
    scale = 0.7 + (verbosity * 0.18)
    ideal_chars = int(ideal_chars * scale)
    max_chars = int(max_chars * scale)
    min_chars = int(min_chars * max(0.75, scale - 0.2))

    context_chars = int(settings.get("max_context_chars") or 12000)
    if context_chars < 8000:
        max_chars = min(max_chars, 2200)
        ideal_chars = min(ideal_chars, 1200)
    if provider_speed in {"slow", "local"} and mode not in {"short", "surgeon"}:
        ideal_chars = int(ideal_chars * 0.72)
        max_chars = int(max_chars * 0.72)
    if provider_speed == "instant":
        mode = "short"
        min_chars, ideal_chars, max_chars = (120, 420, 800)

    max_tokens = max(96, min(1600, math.ceil(max_chars / 4)))
    if mode == "research":
        max_tokens = max(max_tokens, 700)
    if provider_speed in {"slow", "local"}:
        max_tokens = min(max_tokens, 1150 if mode in {"deep", "research"} else 850)
    num_ctx = 4096 if mode in {"deep", "research"} else 2048

    formatting = {
        "short": "compact prose or 2-4 bullets only when useful",
        "standard": "brief sections or concise paragraphs",
        "deep": "clear sections, examples, and ordered steps where useful",
        "surgeon": "precise change list, file references, commands, and verification",
        "research": "answer, findings, uncertainty, sources, and next steps",
    }.get(mode, "concise paragraphs")

    compression = "high" if mode == "short" or context_chars < 8000 else ("medium" if provider_speed in {"slow", "local"} else "low")
    streaming_priority = "immediate" if mode in {"short", "surgeon"} else "staged"
    acknowledge = bool(settings.get("staged_streaming", True) and mode in {"deep", "research", "surgeon"} and provider_speed != "instant")
    acknowledgement = {
        "surgeon": "I'll keep this surgical and verify the moving parts.\n\n",
        "research": "I'll gather the answer into a sourced, compact synthesis.\n\n",
        "deep": "I'll build this in layers so it stays useful, not bloated.\n\n",
    }.get(mode, "")

    instructions = (
        "Adaptive response plan:\n"
        f"- Intent: {analysis['intent']} ({analysis['confidence']})\n"
        f"- Mode: {mode}\n"
        f"- Target length: {min_chars}-{max_chars} characters, ideal around {ideal_chars}\n"
        f"- Depth: {reasoning_depth}/5; explain only the reasoning needed for the user-facing answer.\n"
        f"- Format: {formatting}\n"
        f"- Compression: {compression}; preserve critical details first, remove filler.\n"
        "- Do not expose hidden chain-of-thought; provide concise rationale or checks instead.\n"
        "- Cover all explicit subrequests before adding optional detail.\n"
    )

    return ResponsePlan(
        intent=str(analysis["intent"]),
        mode=mode,
        target_response_length={"short": "short", "standard": "standard", "deep": "long", "surgeon": "precise", "research": "expanded"}[mode],
        target_depth=max(1, min(5, reasoning_depth)),
        formatting_style=formatting,
        streaming_priority=streaming_priority,
        reasoning_intensity=max(1, min(5, reasoning_depth)),
        compression_level=compression,
        min_chars=min_chars,
        ideal_chars=ideal_chars,
        max_chars=max_chars,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        acknowledge=acknowledge,
        acknowledgement=acknowledgement,
        instructions=instructions,
        diagnostics={
            "analysis": analysis,
            "preferences": prefs.to_dict(),
            "provider_speed": provider_speed,
            "route_category": route_category,
            "route_reason": route_reason,
            "manual_mode": manual_mode,
            "verbosity": verbosity,
            "reasoning_depth": reasoning_depth,
        },
    )


def validate_response_against_plan(answer: str, plan: ResponsePlan) -> dict[str, Any]:
    """Check completion, repetition, and rough length fit after generation."""

    text = answer or ""
    paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
    repeated = len(paragraphs) - len(set(paragraphs))
    unanswered_markers = sum(1 for marker in ("TODO", "[placeholder]", "as an AI language model") if marker.lower() in text.lower())
    length_status = "ok"
    if len(text) < plan.min_chars and plan.mode not in {"short"}:
        length_status = "under_target"
    elif len(text) > plan.max_chars * 1.25:
        length_status = "over_target"
    return {
        "chars": len(text),
        "estimated_tokens": estimate_tokens(text),
        "length_status": length_status,
        "repeated_sections": max(0, repeated),
        "unanswered_markers": unanswered_markers,
        "formatting_style": plan.formatting_style,
    }
