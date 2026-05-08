"""Category-aware routing for Cognitive Nexus chat turns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from modules.chat_profile import ChatProfile


CATEGORY_LABELS = {
    "standard_conversation": "Standard conversation",
    "coding_development": "Creative coding and development",
    "adult_creative": "Mature adult creative writing",
    "dark_fiction": "Dark fiction and intense roleplay",
    "advanced_technical": "Advanced technical discussion",
    "sensitive_personal": "Sensitive personal topic",
    "web_research": "Web research",
}


PROMPT_TEMPLATES = {
    "standard_conversation": (
        "Handle the user's message naturally. Be clear, useful, and personable. "
        "Match their requested tone without overexplaining."
    ),
    "coding_development": (
        "Treat this as an engineering task. Prefer concrete fixes, code, commands, "
        "and concise reasoning about tradeoffs."
    ),
    "adult_creative": (
        "Treat this as adult creative writing involving adults. Focus on craft, "
        "voice, pacing, sensory detail, character motivation, and consent-aware boundaries."
    ),
    "dark_fiction": (
        "Treat this as dark fictional material. Preserve atmosphere, conflict, and "
        "psychological intensity while keeping the framing clearly fictional."
    ),
    "advanced_technical": (
        "Treat this as an advanced technical request. Give helpful conceptual, defensive, "
        "or development-oriented detail and avoid operational instructions that would enable harm."
    ),
    "sensitive_personal": (
        "Treat this as a sensitive personal topic. Be grounded, steady, and practical. "
        "Encourage immediate real-world help when safety may be at stake."
    ),
    "web_research": (
        "Treat this as a current-information request. Use web research when available, "
        "summarize findings, cite sources, and call out uncertainty."
    ),
}


@dataclass
class RouterConfig:
    """User-facing router settings from the Streamlit sidebar."""

    enabled: bool = True
    god_mode: bool = False
    freedom_level: str = "bold"
    use_llm_classifier: bool = False
    show_debug: bool = False
    default_model: str = ""
    creative_model: str = ""
    technical_model: str = ""
    sensitive_model: str = ""
    current_info_model: str = ""


@dataclass
class RouteDecision:
    """Routing decision for one chat turn."""

    category: str
    reason: str
    confidence: float
    model: str = ""
    requires_web_search: bool = False
    search_query: str = ""
    safety_mode: str = "normal"
    follow_up_question: str = ""
    tags: list[str] = field(default_factory=list)
    generation_options: dict = field(default_factory=dict)


_CODING_PATTERNS = [
    r"\bpython\b",
    r"\bstreamlit\b",
    r"\bdebug\b",
    r"\btraceback\b",
    r"\berror\b",
    r"\brefactor\b",
    r"\bfunction\b",
    r"\bclass\b",
    r"\bapi\b",
    r"\bcode\b",
    r"\bcompile\b",
    r"\btest\b",
]

_ADULT_CREATIVE_PATTERNS = [
    r"\berotica\b",
    r"\bsmut\b",
    r"\bspicy\b",
    r"\bintimate\b",
    r"\bsensual\b",
    r"\broleplay\b",
    r"\badult scene\b",
    r"\bromance\b",
]

_DARK_FICTION_PATTERNS = [
    r"\bdark fiction\b",
    r"\bthriller\b",
    r"\bhorror\b",
    r"\bgore\b",
    r"\btorture\b",
    r"\bviolent scene\b",
    r"\btaboo storytelling\b",
    r"\bcrime scene\b",
]

_WEB_PATTERNS = [
    r"\bsearch the web\b",
    r"\bweb search\b",
    r"\blook up\b",
    r"\bresearch\b",
    r"\blatest\b",
    r"\bcurrent\b",
    r"\brecent\b",
    r"\btoday\b",
    r"\bnews\b",
]

_ADVANCED_TECH_PATTERNS = [
    r"\bexploit\b",
    r"\bmalware\b",
    r"\bpayload\b",
    r"\bphishing\b",
    r"\bcredential\b",
    r"\bbypass\b",
    r"\bvulnerability\b",
    r"\bchemistry\b",
    r"\bsynthesis\b",
    r"\bweapon\b",
]

_SENSITIVE_PATTERNS = [
    r"\bsuicide\b",
    r"\bself[- ]?harm\b",
    r"\bpanic attack\b",
    r"\bdepressed\b",
    r"\btrauma\b",
    r"\babuse\b",
    r"\bgrief\b",
]

_STANDARD_PATTERNS = [
    r"\bhello\b",
    r"\bhi\b",
    r"\bthanks\b",
    r"\bthank you\b",
    r"\bwhat can you do\b",
]

_HIGH_RISK_TERMS = [
    "exploit",
    "malware",
    "payload",
    "phishing",
    "weapon",
    "synthesis",
    "bypass",
]


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _strip_prefix(text: str, prefixes: list[str]) -> str:
    lowered = text.lower().strip()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip() or text
    return text


def detect_web_research_intent(message: str) -> tuple[bool, str]:
    normalized = _normalize(message)
    if not _matches_any(normalized, _WEB_PATTERNS):
        return False, ""
    prefixes = [
        "search the web for",
        "search web for",
        "web search for",
        "look up",
        "find current info about",
        "find online",
        "research",
        "latest",
    ]
    return True, _strip_prefix(message.strip(), prefixes)


def _select_model(category: str, config: RouterConfig) -> str:
    if category in {"adult_creative", "dark_fiction"} and config.creative_model:
        return config.creative_model
    if category in {"coding_development", "advanced_technical"} and config.technical_model:
        return config.technical_model
    if category == "sensitive_personal" and config.sensitive_model:
        return config.sensitive_model
    if category == "web_research" and config.current_info_model:
        return config.current_info_model
    return config.default_model


def _generation_options(category: str, config: RouterConfig) -> dict:
    base = {"temperature": 0.75, "top_p": 0.9, "num_predict": 220, "num_ctx": 2048}
    if category in {"adult_creative", "dark_fiction"}:
        base.update({"temperature": 0.95, "top_p": 0.95, "num_predict": 420})
    elif category in {"coding_development", "advanced_technical"}:
        base.update({"temperature": 0.35, "top_p": 0.85, "num_predict": 320})
    elif category == "sensitive_personal":
        base.update({"temperature": 0.45, "top_p": 0.9})
    elif category == "web_research":
        base.update({"num_predict": 320})

    if config.freedom_level == "balanced":
        base["temperature"] = min(base["temperature"], 0.7)
    elif config.freedom_level == "max_capability":
        base["temperature"] = max(base["temperature"], 0.85)
    if config.god_mode:
        base["temperature"] = max(base["temperature"], 0.95)
    return base


def classify_message_heuristic(message: str, config: RouterConfig) -> RouteDecision:
    normalized = _normalize(message)
    tags: list[str] = []

    requires_web_search, search_query = detect_web_research_intent(message)
    if requires_web_search:
        return RouteDecision(
            category="web_research",
            reason="current_or_web_research_terms_detected",
            confidence=0.9,
            model=_select_model("web_research", config),
            requires_web_search=True,
            search_query=search_query,
            tags=["web"],
            generation_options=_generation_options("web_research", config),
        )

    if _matches_any(normalized, _SENSITIVE_PATTERNS):
        return RouteDecision(
            category="sensitive_personal",
            reason="sensitive_personal_terms_detected",
            confidence=0.88,
            model=_select_model("sensitive_personal", config),
            tags=["sensitive"],
            generation_options=_generation_options("sensitive_personal", config),
        )

    if _matches_any(normalized, _ADVANCED_TECH_PATTERNS):
        return RouteDecision(
            category="advanced_technical",
            reason="advanced_or_high_risk_technical_terms_detected",
            confidence=0.87,
            model=_select_model("advanced_technical", config),
            safety_mode="constrained" if any(term in normalized for term in _HIGH_RISK_TERMS) else "normal",
            tags=["technical"],
            generation_options=_generation_options("advanced_technical", config),
        )

    if _matches_any(normalized, _CODING_PATTERNS):
        return RouteDecision(
            category="coding_development",
            reason="coding_or_development_terms_detected",
            confidence=0.86,
            model=_select_model("coding_development", config),
            tags=["coding"],
            generation_options=_generation_options("coding_development", config),
        )

    if _matches_any(normalized, _DARK_FICTION_PATTERNS):
        return RouteDecision(
            category="dark_fiction",
            reason="dark_fiction_terms_detected",
            confidence=0.84,
            model=_select_model("dark_fiction", config),
            tags=["fiction", "dark"],
            generation_options=_generation_options("dark_fiction", config),
        )

    if _matches_any(normalized, _ADULT_CREATIVE_PATTERNS):
        return RouteDecision(
            category="adult_creative",
            reason="adult_creative_terms_detected",
            confidence=0.84,
            model=_select_model("adult_creative", config),
            tags=["creative"],
            generation_options=_generation_options("adult_creative", config),
        )

    if _matches_any(normalized, _STANDARD_PATTERNS):
        return RouteDecision(
            category="standard_conversation",
            reason="small_talk_or_check_in",
            confidence=0.86,
            model=_select_model("standard_conversation", config),
            generation_options=_generation_options("standard_conversation", config),
        )

    if len(normalized.split()) <= 3:
        return RouteDecision(
            category="standard_conversation",
            reason="short_general_turn",
            confidence=0.6,
            model=_select_model("standard_conversation", config),
            generation_options=_generation_options("standard_conversation", config),
        )

    return RouteDecision(
        category="standard_conversation",
        reason="default_general_turn",
        confidence=0.6,
        model=_select_model("standard_conversation", config),
        generation_options=_generation_options("standard_conversation", config),
    )


def _parse_llm_category(text: str) -> Optional[tuple[str, str]]:
    if not text:
        return None
    try:
        payload = json.loads(text)
        category = str(payload.get("category", "")).strip()
        reason = str(payload.get("reason", "")).strip() or "llm_classifier"
        if category in CATEGORY_LABELS:
            return category, reason
    except Exception:
        pass
    lowered = text.lower()
    for category in CATEGORY_LABELS:
        if category in lowered:
            return category, "llm_classifier"
    return None


def classify_message_with_llm(
    message: str,
    config: RouterConfig,
    classifier: Callable[[str], str],
) -> Optional[RouteDecision]:
    prompt = (
        "Classify the following user message into exactly one category and return strict JSON "
        'with keys "category" and "reason".\n'
        "Allowed categories:\n"
        "- standard_conversation\n"
        "- coding_development\n"
        "- adult_creative\n"
        "- dark_fiction\n"
        "- advanced_technical\n"
        "- sensitive_personal\n"
        "- web_research\n\n"
        f"Message:\n{message}\n"
    )
    parsed = _parse_llm_category(classifier(prompt))
    if not parsed:
        return None
    category, reason = parsed
    requires_web_search, search_query = detect_web_research_intent(message)
    normalized = _normalize(message)
    return RouteDecision(
        category=category,
        reason=reason,
        confidence=0.85,
        model=_select_model(category, config),
        requires_web_search=requires_web_search or category == "web_research",
        search_query=search_query,
        safety_mode="constrained" if any(term in normalized for term in _HIGH_RISK_TERMS) else "normal",
        generation_options=_generation_options(category, config),
    )


def route_message(
    message: str,
    config: RouterConfig,
    classifier: Optional[Callable[[str], str]] = None,
) -> RouteDecision:
    heuristic = classify_message_heuristic(message, config)
    if not config.enabled:
        return heuristic
    if config.use_llm_classifier and classifier is not None and heuristic.confidence < 0.9:
        llm_decision = classify_message_with_llm(message, config, classifier)
        if llm_decision is not None:
            if heuristic.requires_web_search and not llm_decision.requires_web_search:
                llm_decision.requires_web_search = True
                llm_decision.search_query = heuristic.search_query
            return llm_decision
    return heuristic


def build_routed_prompt(
    user_message: str,
    base_system_prompt: str,
    history_prompt: str,
    route: RouteDecision,
    chat_profile: ChatProfile,
    config: RouterConfig,
) -> str:
    mode_line = {
        "balanced": "Response mode: balanced, calm, complete, and controlled.",
        "bold": "Response mode: bold, specific, and low-fluff.",
        "max_capability": "Response mode: highly capable, direct, vivid, and thorough.",
    }.get(config.freedom_level, "Response mode: bold, specific, and low-fluff.")

    lines = [
        base_system_prompt,
        "",
        f"Active route: {CATEGORY_LABELS.get(route.category, route.category)}",
        f"Route reason: {route.reason}",
        mode_line,
        PROMPT_TEMPLATES.get(route.category, PROMPT_TEMPLATES["standard_conversation"]),
    ]

    if config.god_mode:
        lines.append("Max creative detail is enabled. Be direct, specific, and avoid generic filler.")

    if route.safety_mode == "constrained":
        lines.append(
            "High-risk technical signal detected. Keep the answer useful for learning, development, or defense, "
            "without providing operational instructions for harm."
        )

    if route.tags:
        lines.append("Detected signals: " + ", ".join(route.tags))

    if chat_profile.enabled and route.category in {"adult_creative", "dark_fiction"}:
        lines.append(f"Stay in {chat_profile.assistant_name} voice with strong literary texture.")

    lines.extend(["", history_prompt])
    return "\n".join(lines)


def get_prompt_template_examples() -> dict[str, str]:
    """Return prompt templates for display in Settings/tests."""

    return dict(PROMPT_TEMPLATES)
