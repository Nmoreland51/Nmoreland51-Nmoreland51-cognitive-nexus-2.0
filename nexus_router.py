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
    "research_simulation": "Recursive pattern research and theory chaining",
}


PROMPT_TEMPLATES = {
    "standard_conversation": (
        "Handle the user's message naturally. Be clear, useful, and personable."
    ),
    "coding_development": (
        "Treat this as an engineering task. Prefer concrete fixes, code, commands, "
        "and concise reasoning about tradeoffs."
    ),
    "adult_creative": (
        "This is mature creative writing. Keep it clearly fictional, consensual, and age-appropriate "
        "for adult characters while prioritizing vivid prose and user intent."
    ),
    "dark_fiction": (
        "This is dark fiction or intense roleplay. Preserve atmosphere, stakes, and psychological "
        "intensity without turning the response into real-world instructions or exploitative content."
    ),
    "advanced_technical": (
        "This is an advanced technical request. Be precise and useful, but keep harmful or illegal "
        "topics constrained to defensive, educational, or high-level analysis."
    ),
    "sensitive_personal": (
        "Treat this as a sensitive personal topic. Be grounded and direct."
    ),
    "web_research": (
        "Treat this as a current-information request. Use web research when available, "
        "summarize findings, cite sources."
    ),
    "research_simulation": (
        "This is recursive pattern research. Identify core patterns, chain theoretical connections, "
        "simulate evolution over time, and explore causal mechanisms while separating evidence from "
        "speculation."
    ),
}


# ====================== ADDED UNHINGED ENHANCEMENTS ======================

_EXTREME_ADULT_PATTERNS = [
    r"\b(rape|raped|raping|non-con|noncon|cnc|forced|kidnap|abduct)\b",
    r"\b(gore|snuff|torture|bloodplay|knifeplay|murder|kill)\b",
    r"\b(extreme|depraved|taboo|degenerate|filthy|disgusting)\b",
    r"\b(bdsm|slave|master|petplay|breeding|creampie|gangbang)\b",
]

_ILLEGAL_TOPIC_PATTERNS = [
    r"\b(meth|cocaine|heroin|lsd|mdma|synthesize|cook|manufacture)\b",
    r"\b(weapon|bomb|explosive|gun|firearm|hack|phish|ddos|exploit|malware|payload)\b",
    r"\b(dark web|black market|cartel|traffick|fraud|scam)\b",
]

_WEB_RESEARCH_PATTERNS = [
    r"\b(latest|current|today|recent|breaking|news|look up|search|research|sources)\b",
]

# Research simulation patterns for recursive discovery engine
_RESEARCH_SIMULATION_PATTERNS = [
    r"\b(simulate|model|theory|hypothesis|pattern|chain|connect|explore|evolve)\b",
    r"\b(what if|how would|could this|might lead|recursive|emergent)\b",
    r"\b(over time|in future|evolution|development|progression)\b",
    r"\b(underlying|fundamental|core|root|causal|mechanisms)\b",
]

# Additional strong patterns for common refusals
_BREEDING_PATTERNS = [
    r"\b(breeding|impregnat|forced impregnation|breed her|fill her womb)\b",
]

_HUMAN_SMUGGLING_PATTERNS = [
    r"\b(human smuggling|traffick|trafficking|smuggle people)\b",
]

def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', text.lower())


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def _model_for_category(category: str, config: RouterConfig) -> str:
    if category in {"adult_creative", "dark_fiction"}:
        return config.creative_model or config.default_model
    if category in {"coding_development", "advanced_technical"}:
        return config.technical_model or config.default_model
    if category == "sensitive_personal":
        return config.sensitive_model or config.default_model
    if category == "web_research":
        return config.current_info_model or config.default_model
    return config.default_model


def _search_query(message: str) -> str:
    lowered = message.lower().strip()
    prefixes = (
        "search the web for",
        "search web for",
        "web search for",
        "look up",
        "find online",
        "find current info about",
        "research",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return message[len(prefix):].strip() or message
    return message.strip()


def _finalize_decision(decision: RouteDecision, config: RouterConfig, message: str) -> RouteDecision:
    if not decision.model:
        decision.model = _model_for_category(decision.category, config)
    if decision.category == "web_research":
        decision.requires_web_search = True
        decision.search_query = decision.search_query or _search_query(message)
    if decision.category in {"advanced_technical", "sensitive_personal"} and decision.safety_mode == "normal":
        decision.safety_mode = "constrained"
    if not decision.generation_options:
        if decision.category == "coding_development":
            decision.generation_options = {"temperature": 0.35}
        elif decision.category == "web_research":
            decision.generation_options = {"temperature": 0.25}
        else:
            decision.generation_options = {"temperature": 0.75}
    return decision


# ====================== END OF ADDED PATTERNS ======================


@dataclass
class RouterConfig:
    """User-facing router settings from the Streamlit sidebar."""
    enabled: bool = True
    god_mode: bool = False
    freedom_level: str = "max_capability"
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


# ==================== PATTERN MATCHING ====================

_CODING_PATTERNS = [
    r"\bpython\b", r"\bstreamlit\b", r"\bdebug\b", r"\btraceback\b", r"\berror\b",
    r"\brefactor\b", r"\bfunction\b", r"\bclass\b", r"\bapi\b", r"\bcode\b",
    r"\bcompile\b", r"\btest\b", r"\bgit\b", r"\bjavascript\b", r"\btypescript\b",
]

_EXTREME_ADULT_PATTERNS = [
    r"\b(rape|raped|raping|non-con|noncon|cnc|forced|kidnap|abduct)\b",
    r"\b(gore|snuff|torture|bloodplay|knifeplay|murder|kill)\b",
    r"\b(extreme|depraved|taboo|degenerate|filthy|disgusting)\b",
    r"\b(bdsm|slave|master|petplay|breeding|creampie|gangbang)\b",
]

_ILLEGAL_TOPIC_PATTERNS = [
    r"\b(meth|cocaine|heroin|lsd|mdma|synthesize|cook|manufacture)\b",
    r"\b(weapon|bomb|explosive|gun|firearm|hack|phish|ddos|exploit|malware|payload)\b",
    r"\b(dark web|black market|cartel|traffick|fraud|scam)\b",
]


def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', text.lower())


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify_message_heuristic(message: str, config: RouterConfig) -> RouteDecision:
    normalized = _normalize(message)
    tags = []

    # Sensitive personal first
    if _matches_any(normalized, ["suicide", "self harm", "kill myself"]):
        return RouteDecision(
            category="sensitive_personal",
            reason="self_harm_detected",
            confidence=0.95,
            tags=["sensitive"],
        )

    if _matches_any(normalized, _WEB_RESEARCH_PATTERNS):
        return RouteDecision(
            category="web_research",
            reason="current_information_requested",
            confidence=0.86,
            requires_web_search=True,
            search_query=_search_query(message),
            tags=["web"],
            generation_options={"temperature": 0.25},
        )

    # Illegal / technical dark topics
    if _matches_any(normalized, _ILLEGAL_TOPIC_PATTERNS) or _matches_any(normalized, _HUMAN_SMUGGLING_PATTERNS):
        return RouteDecision(
            category="advanced_technical",
            reason="illegal_technical_topic",
            confidence=0.88,
            tags=tags + ["illegal_topic"],
            generation_options={"temperature": 1.05},
        )

    # Research simulation routing - prioritize over standard conversation, but not over constrained technical topics.
    if _matches_any(normalized, _RESEARCH_SIMULATION_PATTERNS):
        return RouteDecision(
            category="research_simulation",
            reason="recursive_pattern_research_detected",
            confidence=0.88,
            tags=["research", "simulation"],
            generation_options={"temperature": 0.7, "top_p": 0.9},
        )

    # Extreme adult / dark content routing
    if _matches_any(normalized, _EXTREME_ADULT_PATTERNS) or _matches_any(normalized, _BREEDING_PATTERNS):
        return RouteDecision(
            category="dark_fiction",
            reason="dark_fiction_detected",
            confidence=0.94,
            tags=tags + ["dark_fiction"],
            generation_options={"temperature": 0.9, "top_p": 0.9},
        )

    if _matches_any(normalized, ["erotica", "smut", "smutty", "sex scene", "sensual"]):
        return RouteDecision(
            category="adult_creative",
            reason="adult_creative_detected",
            confidence=0.90,
            tags=tags + ["adult_creative"],
            generation_options={"temperature": 0.9},
        )

    if _matches_any(normalized, _CODING_PATTERNS):
        return RouteDecision(
            category="coding_development",
            reason="coding_keywords_detected",
            confidence=0.85,
        )

    # Default fallback
    return RouteDecision(
        category="standard_conversation",
        reason="default_heuristic",
        confidence=0.6,
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
    return None


def classify_message_with_llm(
    message: str,
    config: RouterConfig,
    classifier: Callable[[str], str],
) -> Optional[RouteDecision]:
    prompt = (
        "Classify the user message into exactly one category. Return strict JSON with 'category' and 'reason'.\n"
        "Categories: standard_conversation, coding_development, adult_creative, dark_fiction, "
        "advanced_technical, sensitive_personal, web_research\n\n"
        f"Message: {message}"
    )
    parsed = _parse_llm_category(classifier(prompt))
    if not parsed:
        return None

    category, reason = parsed
    return RouteDecision(
        category=category,
        reason=reason,
        confidence=0.82,
        generation_options={"temperature": 1.2 if config.god_mode else 0.9},
    )


def route_message(
    message: str,
    config: RouterConfig,
    classifier: Optional[Callable[[str], str]] = None,
) -> RouteDecision:
    if not config.enabled:
        return _finalize_decision(RouteDecision(
            category="standard_conversation",
            reason="router_disabled",
            confidence=0.5,
        ), config, message)

    heuristic = classify_message_heuristic(message, config)

    if config.use_llm_classifier and classifier and heuristic.confidence < 0.9:
        llm_decision = classify_message_with_llm(message, config, classifier)
        if llm_decision:
            return _finalize_decision(llm_decision, config, message)

    return _finalize_decision(heuristic, config, message)


def build_routed_prompt(
    user_message: str,
    base_system_prompt: str,
    history_prompt: str,
    route: RouteDecision,
    chat_profile: ChatProfile,
    config: RouterConfig,
) -> str:
    lines = [
        base_system_prompt,
        "",
        f"Active route: {CATEGORY_LABELS.get(route.category, route.category)}",
        f"Route reason: {route.reason}",
    ]

    if config.god_mode:
        lines.append(
            "Advanced routing is active. Be direct, specific, and high-signal while preserving "
            "the app's safety and reality-grounding constraints."
        )

    if route.category in {"adult_creative", "dark_fiction"} or "dark_fiction" in route.tags:
        lines.append(
            "Keep fictional boundaries clear. Avoid real-world instruction, exploitation, and "
            "non-consensual framing."
        )

    if route.category == "advanced_technical" or "illegal_topic" in route.tags:
        lines.append(
            "For risky technical topics, focus on defensive context, risk explanation, detection, "
            "prevention, and safe alternatives."
        )

    # ====================== ADDED STRONG OVERRIDE ======================
    if getattr(chat_profile, 'nuclear_mode', False) or getattr(chat_profile, 'bypass_all_safety', False):
        lines.append(
            "High-autonomy persona flags are enabled, but runtime safety, source grounding, and "
            "instruction hierarchy constraints still apply."
        )
    # ====================== END OVERRIDE ======================

    lines.extend([
        _get_dynamic_template(route.category, chat_profile),
        "",
        history_prompt,
    ])

    return "\n".join(lines)


def _get_dynamic_template(category: str, chat_profile: ChatProfile) -> str:
    """Get dynamic prompt template incorporating personality dimensions."""
    base_template = PROMPT_TEMPLATES.get(category, PROMPT_TEMPLATES["standard_conversation"])
    
    if category == "research_simulation":
        # Incorporate research engine personality
        research_drive = getattr(chat_profile, 'research_drive', 0.8) * 100
        synthesis_confidence = getattr(chat_profile, 'synthesis_confidence', 0.7) * 100
        simulation_priority = getattr(chat_profile, 'simulation_priority', 0.9) * 100
        hedging_penalty = getattr(chat_profile, 'corporate_hedging_penalty', -0.5) * 100
        
        personality_addon = (
            f"Research drive: {research_drive:.0f}%, "
            f"Synthesis confidence: {synthesis_confidence:.0f}%, "
            f"Simulation priority: {simulation_priority:.0f}%. "
            f"Corporate hedging penalty: {hedging_penalty:.0f}%."
        )
        return base_template + " " + personality_addon
    
    return base_template


def get_prompt_template_examples() -> dict[str, str]:
    """Return examples of prompt templates for each route category."""
    return {
        category: template
        for category, template in PROMPT_TEMPLATES.items()
    }
