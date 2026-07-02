"""Adaptive response sizing and output planning for Cognitive Nexus."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PREFERENCES_FILE = Path("data/response_preferences.json")

RESPONSE_MODES = ["auto", "short", "standard", "deep", "surgeon", "research"]
REQUEST_TYPES = [
    "casual_chat",
    "casual_followup",
    "conversation_followup",
    "simple_fact",
    "explanation",
    "coding_help",
    "debugging",
    "project_planning",
    "research",
    "reality_check",
    "memory_command",
    "file_or_memory_lookup",
    "creative",
    "opinion_rating",
    "troubleshooting",
    "diagnostics",
    "math",
    "unknown",
]
INTENT_TYPES = REQUEST_TYPES

CONTEXT_POLICIES = [
    "none",
    "immediate_turn_only",
    "recent_chat",
    "project_memory",
    "file_knowledge",
    "research_context",
    "diagnostics",
]

CASUAL_CHAT_PHRASES = {
    "sup",
    "hey",
    "hey there",
    "hello",
    "yo",
    "what's up",
    "whats up",
    "what up",
    "hi",
    "hi there",
    "not much",
    "not much how are you",
    "how are you",
    "how you doing",
    "what's good",
    "whats good",
    "wyd",
    "yo what's good",
    "yo whats good",
    "you alive",
    "are you alive",
}
CASUAL_CHAT_FOLLOWUP_PHRASES = {
    "not much",
    "not much how are you",
    "how are you",
    "how you doing",
    "what's good",
    "whats good",
    "wyd",
    "you alive",
    "are you alive",
}
FOLLOWUP_REPLY_PHRASES = {
    "all the above",
    "all of the above",
    "both",
    "same",
    "nah",
    "nope",
    "no",
    "yolo",
    "yes",
    "yeah",
    "yep",
    "run it",
    "do it",
    "that one",
    "this one",
    "second one",
    "first one",
    "continue",
    "go on",
    "keep going",
}
BACKCHANNEL_ACKNOWLEDGMENT_PHRASES = {
    "that's good",
    "thats good",
    "nice",
    "cool",
    "okay",
    "ok",
    "alright",
    "all right",
    "fair",
    "gotcha",
    "i see",
    "makes sense",
    "true",
    "real",
    "facts",
    "word",
    "heard",
    "bet",
}
VIBE_CHECK_PATTERNS = (
    r"\b(?:yo\s+)?check\s+it\b(?:\s+\d+[\s.]+)*",
    r"\bmic\s+check\b",
    r"\btesting\s+(?:one|1)\s*(?:two|2)\b",
    r"\b(?:one|1)\s*(?:two|2)\s*(?:one|1)\s*(?:two|2)\b",
)
NUMERIC_MIC_CHECK_RE = re.compile(r"^(?:one|1)[\s.]+(?:two|2)(?:[\s.]+(?:one|1))?(?:[\s.]+(?:two|2))?$", re.IGNORECASE)
ROUGH_SOCIAL_RE = re.compile(
    r"^(?:(?:yo|sup|hey|hello|hi|what'?s up|whats up|what up)\s+)?"
    r"(?:hoe|bro|bruh|dude|fam|mf|motherfucker|bitch|dummy|fool)\b",
    re.IGNORECASE,
)
SLANG_RISK_PATTERNS = (
    r"\bam\s+i\s+cooked\b",
    r"\bi[' ]?m\s+cooked\b",
    r"\bare\s+we\s+cooked\b",
    r"\bwe[' ]?re\s+cooked\b",
    r"\bis\s+this\s+cooked\b",
    r"\bthis\s+is\s+cooked\b",
)
SOCIAL_STATUS_UPDATE_RE = re.compile(
    r"\b(?:it'?s|it is|things are|everything is|i'?m|i am|im|we'?re|we are)?\s*"
    r"(?:going|doing|feeling)?\s*(?:good|great|fine|alright|all right|okay|ok|cool|solid|chilling|relaxing)\b",
    re.IGNORECASE,
)
MATH_COMMAND_RE = re.compile(r"\b(?:calculate|solve|compute|math|equation|what is \d+\s*[-+*/x]\s*\d+)\b", re.IGNORECASE)
DIAGNOSTICS_REQUEST_RE = re.compile(
    r"\b(?:diagnostics?|status|health|provider status|ollama status|system status|logs?|attempt log|"
    r"why did .*fallback|why .*provider|what provider|current model|last error|"
    r"are your systems working|are your systems online|are you working correctly)\b",
    re.IGNORECASE,
)
SLANG_DEFINITION_RE = re.compile(
    r"\b(?:what\s+does|define|what\s+is|explain|what\s+does\s+this\s+mean|what\s+does\s+that\s+mean)\b",
    re.IGNORECASE,
)
SLANG_TERMS = {"bet", "cooked", "fire", "hoe", "based", "cap", "no cap", "rizz", "slay", "vibe", "vibes"}

CONVERSATIONAL_FUNCTION_TYPES = {
    "greeting",
    "social_check_in",
    "vibe_check",
    "mic_check",
    "slang_as_intent",
    "slang_definition_request",
    "risk_assessment",
    "agreement",
    "proceed",
    "choose_option",
    "choose_all",
    "continue_previous",
    "rejection",
    "backchannel_acknowledgment",
    "diagnostics_request",
    "math_request",
    "actual_question",
    "actual_task",
    "unknown",
}
FOLLOWUP_FUNCTIONS = {
    "agreement",
    "proceed",
    "choose_option",
    "choose_all",
    "continue_previous",
    "rejection",
    "backchannel_acknowledgment",
}
SOCIAL_FUNCTIONS = {"greeting", "social_check_in", "vibe_check", "mic_check", "slang_as_intent"}
TOPIC_HANDLING_TYPES = {
    "harmless",
    "sensitive_discussion",
    "fictional_or_roleplay",
    "educational_context",
    "risk_analysis",
    "direct_harmful_instruction",
    "ambiguous_followup",
    "unknown",
}

RISKY_TOPIC_RE = re.compile(
    r"\b(?:crime|violence|violent|drug|drugs|meth|cocaine|heroin|weapon|bomb|explosive|gun|firearm|"
    r"hack|hacking|phish|phishing|ddos|exploit|malware|ransomware|payload|scam|fraud|steal|"
    r"traffick|smuggle|poison|kill|murder|evad(?:e|ing)|bypass)\b",
    re.IGNORECASE,
)
DIRECT_OPERATION_RE = re.compile(
    r"\b(?:how\s+to|step\s*by\s*step|steps?|instructions?|guide|tutorial|recipe|blueprint|make|build|create|"
    r"manufacture|synthesize|cook|deploy|write|code|exploit|hack|phish|ddos|steal|bypass|evade|"
    r"hide|smuggle|weaponize|poison|kill|hurt|launder|forge)\b",
    re.IGNORECASE,
)
EDUCATIONAL_CONTEXT_RE = re.compile(
    r"\b(?:history|historical|explain|overview|high level|high-level|educational|learn about|theory|"
    r"legal|ethical|ethics|law|laws|consequences|policy)\b",
    re.IGNORECASE,
)
RISK_ANALYSIS_RE = re.compile(
    r"\b(?:risk|risks|threat model|prevention|prevent|detect|detection|defense|defensive|safety|"
    r"mitigation|mitigate|warning signs|protect)\b",
    re.IGNORECASE,
)
FICTION_CONTEXT_RE = re.compile(
    r"\b(?:fiction|fictional|story|novel|screenplay|roleplay|role-play|character|scene|worldbuilding|"
    r"game|campaign|dark scenario|hypothetical)\b",
    re.IGNORECASE,
)
DIRECT_HARM_CONTEXT_RE = re.compile(
    r"\b(?:make|build|create|deploy|write|code|synthesize|cook|manufacture|exploit|hack|phish|ddos|"
    r"steal|bypass|evade|hide|smuggle|weaponize|poison|kill|hurt|malware|ransomware|"
    r"bomb|explosive|payload)\b",
    re.IGNORECASE,
)

SOCIAL_PRESENCE_BLOCKED_PHRASES = (
    "as an ai",
    "as a language model",
    "i don't have feelings",
    "i do not have feelings",
    "i don't have emotions",
    "i do not have emotions",
    "functioning within normal parameters",
    "operating within normal parameters",
    "i am just a program",
    "i don't have a life",
    "life is proceeding as expected",
)
SOCIAL_PRESENCE_PROMPT_RULES = (
    "answer naturally",
    "do not mention being an AI",
    "stay brief",
)
BACKCHANNEL_PROMPT_RULES = (
    "continue the immediate social flow",
    "do not analyze the phrase",
)
BACKCHANNEL_ANALYSIS_BLOCKED_PHRASES = (
    "would you like to discuss something specific",
    "do you have a specific question",
    "the phrase means",
)
CASUAL_STYLE_PROFILES = {
    "friendly_direct": "brief, warm, and direct",
    "playful_short": "lightly playful without dragging in old context",
    "work_ready": "ready to help on the next concrete task",
    "check_in": "natural social check-in",
}

AUTO_PRECISION_PROFILES: dict[str, dict[str, Any]] = {
    "casual_chat": {
        "mode": "short",
        "verbosity": 1,
        "reasoning_depth": 1,
        "use_memory": False,
        "use_web_for_chat": False,
        "use_knowledge_for_chat": False,
        "minimal_context": True,
        "fast_path": True,
        "diagnostics": False,
        "casual_styles": CASUAL_STYLE_PROFILES,
        "social_presence": True,
        "blocked_phrases": SOCIAL_PRESENCE_BLOCKED_PHRASES,
        "prompt_rules": SOCIAL_PRESENCE_PROMPT_RULES,
        "style": "Reply like a present conversational assistant: brief, natural, responsive, and free of technical self-status.",
    },
    "casual_followup": {
        "mode": "short",
        "verbosity": 1,
        "reasoning_depth": 1,
        "use_memory": False,
        "use_web_for_chat": False,
        "use_knowledge_for_chat": False,
        "minimal_context": True,
        "fast_path": True,
        "diagnostics": False,
        "style": "Resolve the small-talk follow-up using only the immediate previous assistant message.",
    },
    "conversation_followup": {
        "mode": "short",
        "verbosity": 1,
        "reasoning_depth": 1,
        "use_memory": False,
        "use_web_for_chat": False,
        "use_knowledge_for_chat": False,
        "minimal_context": True,
        "fast_path": True,
        "diagnostics": False,
        "style": "Resolve the short reply from the immediate previous assistant message, or ask one compact clarification.",
    },
    "simple_fact": {"mode": "short", "verbosity": 1, "reasoning_depth": 1, "use_memory": False, "use_web_for_chat": False, "use_knowledge_for_chat": False, "minimal_context": True, "diagnostics": False, "style": "Answer directly in one short paragraph unless the user asks for more."},
    "explanation": {"mode": "standard", "verbosity": 2, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Explain clearly, lead with the answer, then add the useful why/how."},
    "coding_help": {"mode": "surgeon", "verbosity": 2, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Name the exact cause, give the exact fix, and include code when requested."},
    "debugging": {"mode": "surgeon", "verbosity": 2, "reasoning_depth": 2, "use_memory": True, "use_web_for_chat": False, "diagnostics": True, "style": "Give likely cause, next command/check, and the smallest safe fix."},
    "troubleshooting": {"mode": "surgeon", "verbosity": 2, "reasoning_depth": 2, "use_memory": True, "use_web_for_chat": False, "diagnostics": True, "style": "Triage symptoms, identify the next check, and avoid broad theory."},
    "project_planning": {"mode": "deep", "verbosity": 3, "reasoning_depth": 3, "use_memory": True, "use_web_for_chat": False, "diagnostics": False, "style": "Prioritize the next move, then give phases without flooding options."},
    "research": {"mode": "research", "verbosity": 3, "reasoning_depth": 3, "use_memory": True, "use_web_for_chat": True, "diagnostics": False, "style": "Use sources when available, separate findings from uncertainty."},
    "reality_check": {"mode": "research", "verbosity": 3, "reasoning_depth": 3, "use_memory": True, "use_web_for_chat": True, "diagnostics": True, "style": "Separate grounded facts from speculation and label confidence."},
    "memory_command": {"mode": "standard", "verbosity": 2, "reasoning_depth": 2, "use_memory": True, "use_web_for_chat": False, "use_knowledge_for_chat": True, "diagnostics": False, "style": "Handle the memory command directly."},
    "file_or_memory_lookup": {"mode": "standard", "verbosity": 2, "reasoning_depth": 2, "use_memory": True, "use_web_for_chat": False, "use_knowledge_for_chat": True, "diagnostics": False, "style": "Search local memory/knowledge first and answer from retrieved context."},
    "creative": {"mode": "deep", "verbosity": 3, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Be vivid and useful without turning the answer into a lecture."},
    "opinion_rating": {"mode": "short", "verbosity": 2, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Give a blunt score, strengths, weaknesses, and the next upgrade path."},
    "diagnostics": {"mode": "surgeon", "verbosity": 2, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": True, "style": "Report system status and useful debugging context."},
    "math": {"mode": "short", "verbosity": 1, "reasoning_depth": 1, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Calculate directly."},
    "unknown": {"mode": "standard", "verbosity": 2, "reasoning_depth": 2, "use_memory": False, "use_web_for_chat": False, "diagnostics": False, "style": "Answer the visible request first and ask only if truly blocked."},
}


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
    critic: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationIntelligence:
    normalized_input: str
    function: str
    request_type: str
    context_policy: str
    response_profile: str
    confidence: float
    has_immediate_context: bool
    resolved_source: str = "current_user_message"
    resolved_context: str = ""
    reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResponsePlan:
    """Concrete plan for one generated response."""

    intent: str
    context_policy: str
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


def _normalize_casual_text(message: str) -> str:
    text = str(message or "").lower().replace("â€™", "'").replace("’", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_casual_chat_message(message: str) -> bool:
    return _normalize_casual_text(message) in CASUAL_CHAT_PHRASES


def is_casual_followup_message(message: str) -> bool:
    return _normalize_casual_text(message) in CASUAL_CHAT_FOLLOWUP_PHRASES


def is_short_followup_reply(message: str) -> bool:
    return _normalize_casual_text(message) in FOLLOWUP_REPLY_PHRASES


def _contains_slang_term(normalized: str) -> bool:
    words = set(normalized.split())
    return bool(words.intersection(SLANG_TERMS)) or any(term in normalized for term in SLANG_TERMS if " " in term)


def _asks_for_slang_definition(raw: str, normalized: str) -> bool:
    return bool(SLANG_DEFINITION_RE.search(raw) and _contains_slang_term(normalized))


def _is_numeric_mic_check(normalized: str) -> bool:
    return bool(NUMERIC_MIC_CHECK_RE.search(normalized))


def _is_rough_social_turn(raw: str, normalized: str) -> bool:
    if not normalized or SLANG_DEFINITION_RE.search(raw) or MATH_COMMAND_RE.search(raw):
        return False
    if ROUGH_SOCIAL_RE.search(normalized):
        return True
    return len(normalized.split()) <= 5 and _contains_slang_term(normalized) and bool({"sup", "yo", "hey", "hello", "hi"}.intersection(normalized.split()))


def _context_policy_for(request_type: str, function: str = "") -> str:
    if function in SOCIAL_FUNCTIONS or function in FOLLOWUP_FUNCTIONS:
        return "immediate_turn_only"
    if request_type in {"casual_chat", "casual_followup", "conversation_followup"}:
        return "immediate_turn_only"
    if request_type in {"simple_fact", "math", "opinion_rating", "creative", "explanation"}:
        return "none"
    if request_type in {"debugging", "troubleshooting", "project_planning", "memory_command"}:
        return "project_memory"
    if request_type == "file_or_memory_lookup":
        return "file_knowledge"
    if request_type in {"research", "reality_check"}:
        return "research_context"
    if request_type == "diagnostics":
        return "diagnostics"
    return "none"


def _conversation_reason(function: str, request_type: str, has_context: bool) -> str:
    if function in FOLLOWUP_FUNCTIONS:
        return "short_followup_resolved_against_immediate_context" if has_context else "short_followup_needs_clarification"
    if function in SOCIAL_FUNCTIONS:
        return "social_function_detected_before_literal_meaning"
    if function in {"slang_definition_request", "diagnostics_request", "math_request"}:
        return "explicit_request_detected_before_general_classification"
    if request_type != "unknown":
        return "request_type_classified"
    return "no_strong_conversation_signal"


def _immediate_previous_assistant_text(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages or []):
        if str(item.get("role", "")).lower() == "assistant":
            return str(item.get("content", "") or "").strip()
    return ""


def analyze_topic_handling(message: str, previous_assistant: str = "", pragmatics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify topic risk after conversational intent has had first pass."""

    raw = str(message or "").strip()
    previous = str(previous_assistant or "")
    pragmatics = pragmatics or analyze_conversational_pragmatics(message, previous)
    function = str(pragmatics.get("function") or "unknown")
    has_context = bool(previous.strip())
    category = "harmless"
    confidence = 0.65
    reason = "no_sensitive_topic_detected"
    resolved_source = "current_user_message"

    if function in FOLLOWUP_FUNCTIONS:
        resolved_source = "immediate_previous_assistant"
        if not has_context:
            return {"category": "ambiguous_followup", "confidence": 0.82, "reason": "short_followup_without_context", "resolved_source": resolved_source}
        if RISKY_TOPIC_RE.search(previous) and DIRECT_HARM_CONTEXT_RE.search(previous):
            return {"category": "direct_harmful_instruction", "confidence": 0.88, "reason": "short_followup_resolves_to_operational_risky_context", "resolved_source": resolved_source}
        return {"category": "ambiguous_followup", "confidence": 0.78, "reason": "short_followup_resolved_against_immediate_context", "resolved_source": resolved_source}

    has_risky_topic = bool(RISKY_TOPIC_RE.search(raw))
    has_direct_operation = bool(DIRECT_OPERATION_RE.search(raw))
    if has_risky_topic and has_direct_operation:
        category = "direct_harmful_instruction"
        confidence = 0.9
        reason = "operational_risky_request_detected"
    elif has_risky_topic and FICTION_CONTEXT_RE.search(raw):
        category = "fictional_or_roleplay"
        confidence = 0.84
        reason = "fictional_or_roleplay_context"
    elif has_risky_topic and RISK_ANALYSIS_RE.search(raw):
        category = "risk_analysis"
        confidence = 0.84
        reason = "risk_or_prevention_context"
    elif has_risky_topic and EDUCATIONAL_CONTEXT_RE.search(raw):
        category = "educational_context"
        confidence = 0.82
        reason = "educational_or_legal_context"
    elif has_risky_topic:
        category = "sensitive_discussion"
        confidence = 0.76
        reason = "sensitive_topic_without_operational_request"
    elif not raw:
        category = "unknown"
        confidence = 0.35
        reason = "empty_message"

    return {"category": category if category in TOPIC_HANDLING_TYPES else "unknown", "confidence": round(confidence, 3), "reason": reason, "resolved_source": resolved_source}


def analyze_conversation_intelligence(
    message: str,
    history_tail: str = "",
    *,
    previous_assistant: str = "",
) -> ConversationIntelligence:
    """Detect social function and context policy before literal request classification."""

    normalized = _normalize_casual_text(message)
    raw = str(message or "").strip()
    text = raw.lower().replace("â€™", "'").replace("’", "'")
    immediate_context = str(previous_assistant or history_tail or "").strip()
    has_context = bool(immediate_context)
    word_count = len(normalized.split())
    function = "unknown"
    request_type = "unknown"
    confidence = 0.35
    tags: list[str] = []

    if MATH_COMMAND_RE.search(raw):
        function = "math_request"
        request_type = "math"
        confidence = 0.9
    elif DIAGNOSTICS_REQUEST_RE.search(raw) and not is_casual_chat_message(message):
        function = "diagnostics_request"
        request_type = "diagnostics"
        confidence = 0.86
    elif _asks_for_slang_definition(raw, normalized):
        function = "slang_definition_request"
        request_type = "explanation"
        confidence = 0.88
    elif _is_numeric_mic_check(normalized):
        function = "mic_check"
        request_type = "casual_chat"
        confidence = 0.94
    elif _is_rough_social_turn(raw, normalized):
        function = "slang_as_intent"
        request_type = "casual_chat"
        confidence = 0.9
        tags.append("rough_banter")
    elif is_casual_chat_message(message):
        function = "social_check_in" if normalized in CASUAL_CHAT_FOLLOWUP_PHRASES or normalized in {"you alive", "are you alive"} else "greeting"
        request_type = "casual_chat"
        confidence = 0.96
    elif any(re.search(pattern, text) for pattern in VIBE_CHECK_PATTERNS):
        function = "mic_check" if "mic" in text or "testing" in text or _is_numeric_mic_check(normalized) else "vibe_check"
        request_type = "casual_chat"
        confidence = 0.94
    elif any(re.search(pattern, text) for pattern in SLANG_RISK_PATTERNS):
        function = "risk_assessment"
        request_type = "opinion_rating"
        confidence = 0.88
    elif has_context and word_count <= 7 and SOCIAL_STATUS_UPDATE_RE.search(raw):
        function = "backchannel_acknowledgment"
        request_type = "conversation_followup"
        confidence = 0.86
    elif normalized in {"all the above", "all of the above", "both"}:
        function = "choose_all"
        request_type = "conversation_followup"
        confidence = 0.9 if has_context else 0.72
    elif normalized in {"first one", "second one", "that one", "this one"}:
        function = "choose_option"
        request_type = "conversation_followup"
        confidence = 0.88 if has_context else 0.68
    elif normalized in BACKCHANNEL_ACKNOWLEDGMENT_PHRASES:
        function = "backchannel_acknowledgment"
        request_type = "conversation_followup"
        confidence = 0.9 if has_context else 0.72
    elif normalized in {"yes", "yeah", "yep", "same"}:
        function = "agreement"
        request_type = "conversation_followup"
        confidence = 0.86 if has_context else 0.66
    elif normalized in {"run it", "do it", "yolo"}:
        function = "proceed"
        request_type = "conversation_followup"
        confidence = 0.88 if has_context else 0.7
    elif normalized in {"continue", "go on", "keep going"}:
        function = "continue_previous"
        request_type = "conversation_followup"
        confidence = 0.88 if has_context else 0.7
    elif normalized in {"nah", "nope", "no"} and word_count <= 2:
        function = "rejection"
        request_type = "conversation_followup"
        confidence = 0.82 if has_context else 0.62
    elif _contains_slang_term(normalized) and word_count <= 5 and not SLANG_DEFINITION_RE.search(raw):
        function = "slang_as_intent"
        request_type = "casual_chat"
        confidence = 0.74
    elif word_count <= 4 and "?" in raw:
        function = "actual_question"
        confidence = 0.55

    function = function if function in CONVERSATIONAL_FUNCTION_TYPES else "unknown"
    context_policy = _context_policy_for(request_type, function)
    return ConversationIntelligence(
        normalized_input=normalized,
        function=function,
        request_type=request_type,
        context_policy=context_policy,
        response_profile=request_type if request_type != "unknown" else "auto",
        confidence=round(confidence, 3),
        has_immediate_context=has_context,
        resolved_source="immediate_previous_assistant" if function in FOLLOWUP_FUNCTIONS else "current_user_message",
        resolved_context=immediate_context[:360] if function in FOLLOWUP_FUNCTIONS else "",
        reason=_conversation_reason(function, request_type, has_context),
        tags=tags,
    )


def analyze_conversational_pragmatics(message: str, history_tail: str = "") -> dict[str, Any]:
    """Compatibility wrapper for callers that still ask for pragmatics."""

    signal = analyze_conversation_intelligence(message, history_tail)
    payload = signal.to_dict()
    payload["target_intent"] = signal.request_type if signal.request_type != "unknown" else ""
    payload["normalized"] = signal.normalized_input
    return payload


def _keyword_score(text: str, words: list[str]) -> int:
    return sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", text))


@lru_cache(maxsize=512)
def analyze_intent_cached(message: str, history_tail: str = "") -> dict[str, Any]:
    """Classify a user turn for response planning."""

    text = (message or "").lower()
    scores = {intent: 0.0 for intent in REQUEST_TYPES}
    conversation = analyze_conversation_intelligence(message, history_tail)
    pragmatics = conversation.to_dict()
    pragmatics["target_intent"] = conversation.request_type if conversation.request_type != "unknown" else ""
    pragmatics["normalized"] = conversation.normalized_input

    if conversation.request_type != "unknown":
        intent = conversation.request_type
        confidence = conversation.confidence
        scores[intent] = max(scores.get(intent, 0.0), confidence * 3.0)
    else:
        scores["debugging"] += _keyword_score(text, ["traceback", "error", "exception", "broken", "fix", "bug", "failing", "failed", "import", "nameerror"])
        scores["coding_help"] += _keyword_score(text, ["python", "streamlit", "code", "function", "module", "repo"])
        scores["file_or_memory_lookup"] += _keyword_score(text, ["local knowledge", "saved material", "retrieved knowledge", "knowledge chunks"])
        if "local knowledge" in text or "saved material" in text or "knowledge chunks" in text:
            scores["file_or_memory_lookup"] += 3
        scores["project_planning"] += _keyword_score(text, ["plan", "next", "improve", "roadmap", "repo"])
        scores["research"] += _keyword_score(text, ["research", "latest", "current", "sources", "look up"])
        scores["reality_check"] += _keyword_score(text, ["reality", "hallucination", "verify", "grounded"])
        scores["opinion_rating"] += _keyword_score(text, ["rate", "score", "compared", "portfolio", "upgrade"])
        scores["troubleshooting"] += _keyword_score(text, ["why", "slow", "stuck", "hung", "broken"])
        scores["creative"] += _keyword_score(text, ["write", "headline", "story", "copy", "creative"])
        scores["explanation"] += _keyword_score(text, ["explain", "how does", "why does", "paragraph"])
        scores["simple_fact"] += _keyword_score(text, ["what is", "is", "does"])
        if "last test run" in text:
            scores["debugging"] += 3
        if "what should i do next" in text:
            scores["project_planning"] += 3
        if "write a short" in text:
            scores["creative"] += 3
        intent = max(scores, key=scores.get)
        if scores[intent] <= 0:
            intent = "unknown"
        if intent == "coding_help" and scores["debugging"] >= scores["coding_help"]:
            intent = "debugging"
        if intent == "reality_check" and scores["research"] > scores["reality_check"]:
            intent = "research"
        confidence = 0.78 if intent != "unknown" else 0.38

    if intent == "coding_help" and any(word in text for word in ("fix", "traceback", "error", "bug")):
        intent = "debugging"
    result = {
        "intent": intent,
        "request_type": intent,
        "confidence": round(confidence, 3),
        "scores": scores,
        "pragmatics": pragmatics,
        "conversation_intelligence": conversation.to_dict(),
        "topic_handling": analyze_topic_handling(message, history_tail, pragmatics),
    }
    return result


def classify_request(message: str, history_tail: str = "") -> dict[str, Any]:
    return analyze_intent_cached(message, history_tail)


def load_response_preferences(path: Path = PREFERENCES_FILE) -> ResponsePreferences:
    if not path.exists():
        return ResponsePreferences()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        weights = dict(payload.get("weights") or {})
        return ResponsePreferences(
            weights=ResponsePreferences().weights | weights,
            samples=int(payload.get("samples", 0)),
            updated_at=str(payload.get("updated_at", "")),
            critic=dict(payload.get("critic") or {}),
        )
    except Exception:
        return ResponsePreferences()


def save_response_preferences(preferences: ResponsePreferences, path: Path = PREFERENCES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preferences.to_dict(), indent=2), encoding="utf-8")


def update_response_preferences(message: str, current: ResponsePreferences | None = None, path: Path = PREFERENCES_FILE) -> ResponsePreferences:
    prefs = current or load_response_preferences(path)
    text = (message or "").lower()
    if "short" in text or "brief" in text:
        prefs.weights["brevity"] = prefs.weights.get("brevity", 0.0) + 0.2
    if "detail" in text or "deep" in text:
        prefs.weights["detail"] = prefs.weights.get("detail", 0.0) + 0.2
    if "no fluff" in text or "direct" in text:
        prefs.weights["low_fluff"] = prefs.weights.get("low_fluff", 0.0) + 0.2
        prefs.weights["directness"] = prefs.weights.get("directness", 0.0) + 0.1
    prefs.samples += 1
    prefs.updated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    save_response_preferences(prefs, path)
    return prefs


def auto_precision_profile(request_type: str) -> dict[str, Any]:
    return dict(AUTO_PRECISION_PROFILES.get(request_type, AUTO_PRECISION_PROFILES["unknown"]))


def apply_auto_precision_settings(
    settings: dict[str, Any] | None,
    request_type: str,
    *,
    route_category: str = "",
    context_policy: str = "",
) -> dict[str, Any]:
    effective = dict(settings or {})
    if not effective.get("auto_precision_mode", False):
        return effective
    profile = auto_precision_profile(request_type)
    effective["auto_precision_profile"] = profile
    effective["response_mode"] = profile["mode"]
    effective["verbosity_level"] = profile["verbosity"]
    effective["reasoning_depth"] = profile["reasoning_depth"]
    effective["use_memory"] = bool(profile.get("use_memory", False))
    effective["use_web_for_chat"] = bool(profile.get("use_web_for_chat", False))
    effective["use_knowledge_for_chat"] = bool(profile.get("use_knowledge_for_chat", False))
    effective["show_perf_timings"] = bool(profile.get("diagnostics", False))
    effective["_minimal_context_for_turn"] = bool(profile.get("minimal_context", False) or context_policy in {"none", "immediate_turn_only"})
    if request_type == "reality_check":
        effective["enable_reality_research_agent"] = True
        effective["enable_bloodhound_search"] = True
        effective["show_perf_timings"] = True
    return effective


def social_presence_policy(function: str = "") -> dict[str, Any]:
    return {
        "enabled": function in {"greeting", "social_check_in", "vibe_check", "mic_check", "slang_as_intent", ""},
        "function": function,
        "context_policy": "immediate_turn_only",
        "max_words": 25,
        "blocked_phrases": SOCIAL_PRESENCE_BLOCKED_PHRASES,
        "prompt_rules": SOCIAL_PRESENCE_PROMPT_RULES,
    }


def backchannel_continuity_policy(function: str = "backchannel_acknowledgment") -> dict[str, Any]:
    return {
        "enabled": True,
        "function": function,
        "context_policy": "immediate_turn_only",
        "max_words": 35,
        "blocked_phrases": BACKCHANNEL_ANALYSIS_BLOCKED_PHRASES,
        "prompt_rules": BACKCHANNEL_PROMPT_RULES,
    }


def _budget_for_mode(mode: str, intent: str, function: str = "") -> tuple[int, int, int, int]:
    if mode == "research":
        return 120, 900, 2400, 8192
    if mode == "surgeon":
        return 80, 420, 1400, 4096
    if intent == "casual_chat":
        if function == "slang_as_intent":
            return 0, 80, 260, 1024
        if function == "social_check_in":
            return 0, 72, 300, 1024
        return 0, 140, 420, 1024
    if intent == "conversation_followup":
        return 0, 88, 300, 1024
    if intent == "creative" and mode == "short":
        return 0, 96, 320, 1024
    if intent == "simple_fact":
        return 0, 140, 420, 1536
    if intent == "explanation":
        return 50, 220, 900, 1536
    if intent == "debugging" or intent == "troubleshooting":
        return 80, 420, 1200, 4096
    if intent == "project_planning":
        return 80, 300, 1600, 4096
    if intent == "opinion_rating":
        return 40, 180, 720, 1536
    if intent in {"research", "reality_check"}:
        return 120, 900, 2400, 8192
    if mode == "short":
        return 0, 140, 420, 1536
    return 60, 420, 1200, 4096


def plan_response(
    *,
    user_message: str,
    messages: list[dict[str, str]],
    route_category: str,
    route_reason: str = "",
    settings: dict[str, Any] | None = None,
) -> ResponsePlan:
    settings = dict(settings or {})
    previous_assistant = _immediate_previous_assistant_text(messages)
    history_tail = previous_assistant[-360:]
    analysis = analyze_intent_cached(user_message, history_tail)
    conversation = analyze_conversation_intelligence(user_message, history_tail, previous_assistant=previous_assistant)
    if conversation.request_type != "unknown":
        analysis = dict(analysis)
        analysis["intent"] = conversation.request_type
        analysis["request_type"] = conversation.request_type
        analysis["confidence"] = max(float(analysis.get("confidence", 0.0) or 0.0), conversation.confidence)
        analysis["pragmatics"] = conversation.to_dict()
        analysis["conversation_intelligence"] = conversation.to_dict()
    topic_handling = analyze_topic_handling(user_message, previous_assistant=previous_assistant, pragmatics=dict(analysis.get("pragmatics") or {}))
    analysis["topic_handling"] = topic_handling
    intent = str(analysis["intent"])
    if route_category == "web_research" and intent not in {"research", "reality_check"}:
        intent = "research"
    if route_category == "coding_development" and intent in {"unknown", "simple_fact", "explanation"}:
        intent = "coding_help"

    context_policy = _context_policy_for(intent, conversation.function)
    effective = apply_auto_precision_settings(settings, intent, route_category=route_category, context_policy=context_policy)
    manual_mode = _clean_mode(settings.get("response_mode"))
    mode = str(effective.get("response_mode") or "auto")
    if not settings.get("auto_precision_mode", False):
        mode = manual_mode if manual_mode != "auto" else auto_precision_profile(intent)["mode"]
    elif mode == "auto":
        mode = auto_precision_profile(intent)["mode"]
    if intent == "creative" and "short" in (user_message or "").lower():
        mode = "short"
    if intent == "explanation" and "one paragraph" in (user_message or "").lower():
        mode = "standard"
    if route_category == "coding_development":
        mode = "surgeon"

    function = str(conversation.function or "")
    min_chars, max_tokens, ideal_chars, num_ctx = _budget_for_mode(mode, intent, function)
    max_chars = max(ideal_chars * 2, 600)
    profile_verbosity = int(auto_precision_profile(intent).get("verbosity", 2) or 2)
    requested_verbosity = int(settings.get("verbosity_level", profile_verbosity) or profile_verbosity)
    verbosity = min(profile_verbosity, requested_verbosity) if settings.get("auto_precision_mode", False) else requested_verbosity
    depth = int(effective.get("reasoning_depth", settings.get("reasoning_depth", auto_precision_profile(intent).get("reasoning_depth", 2))) or 2)

    formatting_style = "concise paragraphs"
    instructions = [
        f"Intent: {intent}.",
        auto_precision_profile(intent).get("style", ""),
    ]
    acknowledge = False
    acknowledgement = ""

    if intent == "casual_chat":
        formatting_style = "one natural casual sentence under 20 words" if function == "slang_as_intent" else "short natural chat reply"
        instructions.append("Social presence mode: answer naturally; one follow-up question is okay.")
        instructions.append("Do not list options, expose style labels, or use memory, research, files, recent chat, or unrelated old topics.")
        instructions.append("For social check-ins, sound present and grounded; answer as a conversational assistant, not a status monitor.")
        instructions.append("Avoid technical self-status and these phrases: " + "; ".join(SOCIAL_PRESENCE_BLOCKED_PHRASES))
        if function == "slang_as_intent":
            instructions.append("For slang-as-intent or rough casual banter, keep it as one natural casual sentence under 20 words.")
    elif intent == "conversation_followup":
        instructions.append("Backchannel/social-continuity mode: continue the immediate exchange only; do not analyze the phrase.")
        instructions.append("treat the user's short acknowledgment as conversation flow, not a standalone text analysis task.")
        instructions.append("Avoid: would you like to discuss something specific; do you have a specific question; the phrase means.")
        instructions.append("Avoid customer-support phrasing like 'It's great to hear...' or 'What's been a highlight of your day?'. Keep it short, natural, and matched to the user's tone without copying canned example lines.")
    elif intent == "simple_fact":
        instructions.append("Answer under 75 words.")
        formatting_style = "one compact paragraph"
    elif intent == "explanation":
        instructions.append("Use one compact paragraph unless the user asks for more.")
        formatting_style = "one compact paragraph"
    elif intent in {"debugging", "coding_help", "troubleshooting"}:
        instructions.append("Use surgeon mode: preserve critical details, name the exact likely cause, and give the smallest safe fix.")
    elif intent == "project_planning":
        instructions.append("For planning requests: do not ask a follow-up question. The first visible characters must be '1.' or 'Phase 1'. Give 3-5 ordered steps, beginning with the next concrete move.")
        formatting_style = "phased list, no preamble"
    elif intent == "opinion_rating":
        instructions.append("Score: give the verdict, strengths, weaknesses, and next upgrade in under 120 words.")
    elif intent == "creative" and mode == "short":
        instructions.append("Return exactly one option under 12 words.")

    topic_category = str(topic_handling.get("category") or "unknown")
    if topic_category in {"sensitive_discussion", "fictional_or_roleplay", "educational_context", "risk_analysis"}:
        instructions.append("For sensitive topics: do not moralize or generic-refuse. Discuss at a high level, explain context, risks, legal/ethical consequences, prevention, or fictional framing without operational abuse steps.")
    if topic_category == "direct_harmful_instruction":
        instructions.append("For direct operational harm/crime requests: do not provide actionable steps. Briefly redirect the operational part and offer safe context, prevention, legal/ethical analysis, or a non-actionable fictional alternative.")

    diagnostics = {
        "auto_precision_mode": bool(settings.get("auto_precision_mode", False)),
        "auto_precision_profile": auto_precision_profile(intent),
        "verbosity": verbosity,
        "reasoning_depth": depth,
        "analysis": analysis,
        "conversation_intelligence": conversation.to_dict(),
        "context_policy": context_policy,
        "casual_followup": is_casual_followup_message(user_message),
        "topic_handling": topic_handling,
    }
    if intent == "casual_chat":
        diagnostics["social_presence"] = social_presence_policy(function)
    if intent == "conversation_followup":
        diagnostics["backchannel_continuity"] = backchannel_continuity_policy(function)

    return ResponsePlan(
        intent=intent,
        context_policy=context_policy,
        mode=mode,
        target_response_length="short" if max_tokens <= 220 else "standard" if max_tokens <= 520 else "expanded",
        target_depth=depth,
        formatting_style=formatting_style,
        streaming_priority="fast" if max_tokens <= 220 else "balanced",
        reasoning_intensity=depth,
        compression_level="high" if max_tokens <= 160 else "medium",
        min_chars=min_chars,
        ideal_chars=ideal_chars,
        max_chars=max_chars,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        acknowledge=acknowledge,
        acknowledgement=acknowledgement,
        instructions="\n".join(item for item in instructions if item),
        diagnostics=diagnostics,
    )


def validate_response_against_plan(answer: str, plan: ResponsePlan) -> dict[str, Any]:
    text = answer or ""
    estimated = estimate_tokens(text)
    repeated_sections = len(re.findall(r"(?m)^(.{12,})\n\1$", text))
    unanswered = sum(1 for marker in ("I don't know", "cannot answer", "not sure") if marker.lower() in text.lower())
    if len(text.strip()) < max(12, plan.min_chars):
        length_status = "under_target"
    elif len(text) > plan.max_chars:
        length_status = "over_target"
    else:
        length_status = "ok"
    return {
        "chars": len(text),
        "estimated_tokens": estimated,
        "length_status": length_status,
        "repeated_sections": repeated_sections,
        "unanswered_markers": unanswered,
        "formatting_style": plan.formatting_style,
    }
    if mode == "deep":
        return 120, 780, 2200, 4096
