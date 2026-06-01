"""Cognitive Nexus Streamlit dashboard."""
from __future__ import annotations
import base64
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
import streamlit as st

from modules.chat_profile import (
    ChatProfile,
    load_chat_profile,
    save_chat_profile,
)
from modules.context_manager import load_user_profile_summary
from modules.core_health import run_core_health_check
from modules.image_gen import (
    IMAGE_STYLE_OPTIONS,
    ImageGenerationRequest,
    detect_image_provider,
    detect_image_providers,
    generate_images,
    list_generated_images,
    summarize_image_gallery,
)
from modules.memory import (
    add_message,
    clear_messages,
    clear_session_history_file,
    get_messages,
    initialize_chat_state,
    load_legacy_history,
    load_session_history_file,
    save_session_history,
)
from modules.project_status import (
    PROJECT_ROOT,
    get_environment_status,
    get_project_inventory,
    list_project_tools,
    tail_file,
)
from modules.providers import (
    check_ollama_status,
    fallback_response,
    get_provider_inventory,
)
from modules.research import (
    get_research_module,
    ingest_text,
    list_knowledge_notes,
    process_url,
    save_knowledge_note,
)
from modules.nexus_config import save_runtime_config
from modules.nexus_core import NexusCore
from modules.reality_research_agent import ResearchRequest
from modules.response_planner import RESPONSE_MODES
from nexus_router import (
    CATEGORY_LABELS,
    RouterConfig,
    get_prompt_template_examples,
)

try:
    from cognitive_nexus.adaptation import AdaptiveMemoryManager
except Exception:  # pragma: no cover - optional legacy module
    AdaptiveMemoryManager = None  # type: ignore

st.set_page_config(
    page_title="Cognitive Nexus",
    page_icon="CN",
    layout="wide",
    initial_sidebar_state="expanded",
)

SESSION_DIAGNOSTIC_KEYS = (
    "last_route_decision",
    "last_provider_result",
    "last_verification",
    "last_response_plan",
    "last_reality_audit",
    "last_trust_audit",
    "last_epistemic_assessment",
    "last_reality_research_report",
    "last_retrieval",
    "last_memory",
    "last_image_generation_result",
    "last_core_health_check",
    "perf_timings",
    "demo_loaded",
)

TAB_LABELS = [
    "Home / Overview",
    "Chat",
    "Reality-First Research",
    "Web Research",
    "Files / Knowledge",
    "Memory",
    "Image Generation",
    "Gallery",
    "Diagnostics",
    "Settings",
    "Tools / Utilities",
]

_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s`'\"<>|]+")
_LOCAL_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?[^\s`'\"<>)]*")
_ENV_DETAIL_RE = re.compile(r"\b(?:OPENAI|ANTHROPIC|HF|HUGGINGFACE|API|TOKEN|SECRET|KEY)[A-Z0-9_]*\b", re.IGNORECASE)


def is_demo_safe(settings: dict[str, Any] | None) -> bool:
    return bool((settings or {}).get("demo_safe_mode"))


def demo_safe_status(enabled: bool) -> str:
    return "Demo Safe Mode: On" if enabled else "Demo Safe Mode: Off"


def sanitize_demo_text(value: Any) -> str:
    """Hide local paths and environment-specific details for demo surfaces."""
    text = str(value or "")
    if not text:
        return ""
    project_path = str(PROJECT_ROOT)
    if project_path and project_path in text:
        text = text.replace(project_path, "[project path hidden]")
    text = _WINDOWS_PATH_RE.sub("[local path hidden]", text)
    text = _LOCAL_URL_RE.sub("[local service hidden]", text)
    text = _ENV_DETAIL_RE.sub("[environment detail hidden]", text)
    return text


def sanitize_demo_value(value: Any) -> Any:
    if isinstance(value, Path):
        return "[local path hidden]"
    if isinstance(value, dict):
        return {str(key): sanitize_demo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_demo_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_demo_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_demo_text(value)
    return value


def sanitize_demo_rows(rows: list[dict[str, Any]], *, enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return rows
    return [sanitize_demo_value(row) for row in rows]


@st.cache_resource
def get_nexus_core() -> NexusCore:
    return NexusCore(PROJECT_ROOT)


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_core_status(provider_order: tuple[str, ...]) -> dict[str, Any]:
    return get_nexus_core().status_snapshot(list(provider_order))


@st.cache_resource
def get_adaptive_memory():
    if AdaptiveMemoryManager is None:
        return None
    return AdaptiveMemoryManager(Path("data"))


@st.cache_resource
def get_cached_research_module():
    return get_research_module()


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_ollama_status():
    return check_ollama_status()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_project_inventory() -> dict[str, Any]:
    return get_project_inventory()


@st.cache_data(ttl=20, show_spinner=False)
def get_cached_core_health(provider_order: tuple[str, ...], selected_model: str) -> dict[str, Any]:
    return run_core_health_check(
        PROJECT_ROOT,
        provider_order=list(provider_order),
        selected_model=selected_model,
        include_probe=False,
    )


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_image_provider() -> dict[str, Any]:
    return detect_image_provider()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_image_providers() -> list[dict[str, Any]]:
    return detect_image_providers()


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_gallery(limit: int) -> list[dict[str, Any]]:
    return list_generated_images(limit=limit)


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_image_summary() -> dict[str, Any]:
    return summarize_image_gallery()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_provider_inventory() -> list[dict[str, Any]]:
    return get_provider_inventory()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_project_tools() -> list[dict[str, str]]:
    return list_project_tools()


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_knowledge_summary() -> dict[str, Any]:
    return get_research_module().get_processing_summary()


@st.cache_data(ttl=10, show_spinner=False)
def get_cached_log_files() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("*.log"))


def clear_runtime_caches() -> None:
    for cached_func in (
        get_cached_ollama_status,
        get_cached_core_health,
        get_cached_project_inventory,
        get_cached_image_provider,
        get_cached_image_providers,
        get_cached_gallery,
        get_cached_image_summary,
        get_cached_provider_inventory,
        get_cached_project_tools,
        get_cached_knowledge_summary,
        get_cached_log_files,
        get_cached_core_status,
    ):
        cached_func.clear()
    get_nexus_core().refresh_config()


def record_perf(label: str, elapsed: float, settings: Optional[dict[str, Any]] = None) -> None:
    if settings is not None and not settings.get("show_perf_timings"):
        return
    timings = st.session_state.setdefault("perf_timings", [])
    timings.append({"label": label, "seconds": round(elapsed, 3)})
    del timings[:-30]


def get_chat_model(models: list[str]) -> str:
    preferred_models = [
        "llama3.2:3b",  # Fast model
        "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
        "mannix/llama3.1-8b-abliterated:latest",
        "BlackHillsInfoSec/llama-3.1-8b-abliterated",
        "mannix/llama3.1-8b-abliterated",
        "dolphin-llama3:8b",
        "dolphin-llama3:latest",
        "dolphin-llama3:70b",
    ]
    for preferred in preferred_models:
        if preferred in models:
            return preferred
    non_embedding = [model for model in models if "embed" not in model.lower()]
    return non_embedding[0] if non_embedding else (models[0] if models else "")


def clear_chat_state() -> None:
    clear_messages()
    clear_session_history_file()


def reset_session_state() -> None:
    """Reset transient chat, diagnostics, timings, and demo data without deleting knowledge files."""

    clear_chat_state()
    for key in SESSION_DIAGNOSTIC_KEYS:
        st.session_state.pop(key, None)


def normalize_provider_order(selection: list[str], provider_options: list[str]) -> list[str]:
    """Keep provider order valid and force fallback to remain the last safety net."""

    valid = set(provider_options)
    normalized: list[str] = []
    for provider in selection:
        if provider not in valid or provider == "fallback" or provider in normalized:
            continue
        normalized.append(provider)
    normalized.append("fallback")
    return normalized


def restore_persisted_chat() -> None:
    initialize_chat_state()
    if get_messages():
        return
    for message in load_session_history_file():
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
            add_message(str(message["role"]), str(message.get("content", "")))


def _select_model_option(label: str, models: list[str], default: str) -> str:
    index = models.index(default) if default in models else 0
    return st.selectbox(label, models, index=index)


def render_sidebar(
    status,
    inventory: dict[str, Any],
    image_status: dict[str, Any],
    chat_profile: ChatProfile,
    core_status: dict[str, Any],
) -> dict[str, Any]:
    with st.sidebar:
        st.header("Cognitive Nexus")
        st.subheader("Provider")
        if status.available and status.models:
            st.success("Ollama available")
        elif status.available:
            st.warning("Ollama running, no models")
        else:
            st.error("Ollama offline")
        demo_safe_mode = st.checkbox(
            "Demo Safe Mode",
            value=False,
            help="Hide local paths, raw private memory, environment details, and machine-specific diagnostics.",
        )
        st.caption(sanitize_demo_text(status.message) if demo_safe_mode else status.message)
        if demo_safe_mode:
            st.caption("Endpoint: local provider endpoint hidden")
        else:
            st.caption(f"Endpoint: {status.base_url}")

        selected_model = None
        if status.models:
            default_model = get_chat_model(status.models)
            default_index = status.models.index(default_model) if default_model in status.models else 0
            selected_model = st.selectbox("Chat model", status.models, index=default_index)
        else:
            st.info("Fallback mode is active.")

        st.subheader("Answer Behavior")
        auto_precision_mode = st.checkbox(
            "Auto Precision Mode",
            value=True,
            help="Automatically chooses answer length, detail, memory, research, and diagnostics from the request.",
        )
        last_plan = st.session_state.get("last_response_plan") or {}
        current_mode = (
            f"{last_plan.get('intent', 'auto')} / {last_plan.get('mode', 'auto')}"
            if last_plan
            else ("Auto Precision ready" if auto_precision_mode else "Manual overrides ready")
        )
        st.caption(f"Current answer mode: {current_mode}")

        provider_options = ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]
        configured_order = normalize_provider_order(
            [
                item
                for item in core_status.get("config", {}).get("provider_order", provider_options)
                if item in provider_options
            ],
            provider_options,
        )
        provider_order = configured_order
        configured_comfyui_url = str(core_status.get("config", {}).get("comfyui_url") or "http://127.0.0.1:8188")
        configured_hf_local_model = str(core_status.get("config", {}).get("hf_local_model") or "")
        comfyui_url = configured_comfyui_url
        hf_local_model = configured_hf_local_model

        use_memory = False
        use_knowledge_for_chat = True
        use_web_for_chat = True
        show_sources = True
        enable_router = True
        show_perf_timings = False
        advanced_mode = False
        demo_mode = False
        generation_timeout = 600
        god_mode = False
        freedom_level = "bold"
        use_llm_classifier = False
        show_route_debug = False
        response_mode = "auto"
        verbosity_level = 2
        staged_streaming = True
        reasoning_depth = 2
        enable_reality_grounding = bool(core_status.get("config", {}).get("enable_reality_grounding", True))
        enable_reality_first_reasoning = bool(core_status.get("config", {}).get("enable_reality_first_reasoning", True))
        epistemic_mode = str(core_status.get("config", {}).get("epistemic_mode") or "auto")
        if epistemic_mode not in ["auto", "strict_fact", "theoretical", "science_fiction", "research"]:
            epistemic_mode = "auto"
        show_grounding_notes = bool(core_status.get("config", {}).get("show_grounding_notes", True))
        max_context_chars = int(core_status.get("config", {}).get("max_context_chars") or 12000)
        recent_message_limit = 8
        knowledge_top_k = 3
        knowledge_use_ai = False
        reality_research_enabled = bool(core_status.get("config", {}).get("enable_reality_research_agent", True))
        reality_research_depth = "Standard"
        bloodhound_enabled = bool(core_status.get("config", {}).get("enable_bloodhound_search", True))
        bloodhound_depth = "Standard"
        bloodhound_max_results = int(core_status.get("config", {}).get("max_search_results") or 50)
        bloodhound_follow_links = bool(core_status.get("config", {}).get("enable_link_following", True))
        bloodhound_enable_cache = bool(core_status.get("config", {}).get("enable_search_cache", True))
        bloodhound_enable_onion = bool(core_status.get("config", {}).get("enable_onion_search", False))

        manual_disabled = bool(auto_precision_mode)
        with st.expander("Advanced Overrides", expanded=not auto_precision_mode):
            if auto_precision_mode:
                st.caption("Turn off Auto Precision Mode to make these manual answer controls active.")
            st.markdown("**Context and routing**")
            use_memory = st.checkbox("Use adaptive memory", value=use_memory, disabled=manual_disabled)
            use_knowledge_for_chat = st.checkbox("Use local knowledge in chat", value=use_knowledge_for_chat, disabled=manual_disabled)
            use_web_for_chat = st.checkbox("Web search from chat commands", value=use_web_for_chat, disabled=manual_disabled)
            show_sources = st.checkbox("Show sources", value=show_sources, disabled=manual_disabled)
            enable_router = st.checkbox("Enable Nexus Router", value=enable_router, disabled=manual_disabled)
            show_perf_timings = st.checkbox("Show performance timings", value=show_perf_timings, disabled=manual_disabled)
            advanced_mode = st.checkbox("Advanced mode", value=advanced_mode, disabled=manual_disabled)
            demo_mode = st.checkbox("Demo mode", value=demo_mode, help="Load sample data for demonstration")
            generation_timeout = st.number_input(
                "Model timeout (seconds)",
                min_value=300,
                max_value=1800,
                value=int(generation_timeout),
                step=60,
                key="ollama_generation_timeout_seconds_v2",
                help="How long the app waits for Ollama to finish loading and generating a reply.",
            )
            god_mode = st.checkbox(
                "Advanced routing",
                value=god_mode,
                disabled=manual_disabled,
                help="Routes prompts with stronger specificity and less filler while keeping the app stable.",
            )
            freedom_level = st.select_slider(
                "Response detail",
                options=["balanced", "bold", "max_capability"],
                value=freedom_level,
                disabled=manual_disabled,
            )
            use_llm_classifier = st.checkbox(
                "Use local model to refine route classification",
                value=use_llm_classifier,
                disabled=manual_disabled or not status.models,
            )
            show_route_debug = st.checkbox("Show routing debug", value=show_route_debug, disabled=manual_disabled)

            st.markdown("**Response controls**")
            response_mode = st.selectbox(
                "Response mode",
                RESPONSE_MODES,
                index=0,
                disabled=manual_disabled,
                format_func=lambda value: {
                    "auto": "Auto",
                    "short": "Short",
                    "standard": "Standard",
                    "deep": "Deep",
                    "surgeon": "Surgeon",
                    "research": "Research",
                }.get(value, value.title()),
                help="Auto lets Cognitive Nexus choose response size and structure from the request.",
            )
            verbosity_level = st.slider("Verbosity", 1, 5, int(verbosity_level), disabled=manual_disabled, help="Higher values allow longer answers when useful.")
            staged_streaming = st.checkbox(
                "Immediate streaming acknowledgement",
                value=staged_streaming,
                disabled=manual_disabled,
                help="Shows a short visible acknowledgement before slower deep/research responses.",
            )
            reasoning_depth = st.slider(
                "Reasoning depth",
                1,
                5,
                int(reasoning_depth),
                disabled=manual_disabled,
                help="Controls how much structured rationale the model is asked to include in the final answer.",
            )
            enable_reality_grounding = st.checkbox(
                "Reality grounding",
                value=enable_reality_grounding,
                disabled=manual_disabled,
                help="Audits generated answers for claims, hallucination risk, speculation, contradiction, and confidence.",
            )
            enable_reality_first_reasoning = st.checkbox(
                "Reality-first reasoning",
                value=enable_reality_first_reasoning,
                disabled=manual_disabled,
                help="Applies feasibility and theory/fiction constraints before the model drafts an answer.",
            )
            epistemic_mode = st.selectbox(
                "Epistemic mode",
                ["auto", "strict_fact", "theoretical", "science_fiction", "research"],
                index=["auto", "strict_fact", "theoretical", "science_fiction", "research"].index(epistemic_mode),
                disabled=manual_disabled,
            )
            show_grounding_notes = st.checkbox(
                "Show grounding notes",
                value=show_grounding_notes,
                disabled=manual_disabled or not enable_reality_grounding,
                help="Adds compact uncertainty notes to risky answers.",
            )
            max_context_chars = st.slider("Max context characters", 4000, 24000, int(max_context_chars), step=1000, disabled=manual_disabled)
            recent_message_limit = st.slider("Recent turns in context", 2, 16, int(recent_message_limit), step=2, disabled=manual_disabled)
            knowledge_top_k = st.slider("Knowledge chunks for chat", 1, 6, int(knowledge_top_k), disabled=manual_disabled)
            knowledge_use_ai = st.checkbox(
                "AI synthesis for knowledge queries",
                value=knowledge_use_ai,
                disabled=manual_disabled,
                help="Off is faster and uses extractive answers from stored sources. Turn on for slower model-written synthesis.",
            )

            st.markdown("**Research controls**")
            reality_research_enabled = st.checkbox(
                "Reality-First Research Agent",
                value=reality_research_enabled,
                disabled=manual_disabled,
                help="Routes deep research, verify, trace sources, and search-style chat commands into the source-grounded research agent.",
            )
            reality_research_depth = st.selectbox("Research agent depth", ["Quick", "Standard", "Deep", "Extreme"], index=1, disabled=manual_disabled)
            bloodhound_enabled = st.checkbox(
                "Bloodhound Search Mode",
                value=bloodhound_enabled,
                disabled=manual_disabled,
                help="Routes search/find/deep search chat commands into the deep public-web search engine.",
            )
            bloodhound_depth = st.selectbox("Search depth", ["Quick", "Standard", "Deep", "Extreme"], index=1, disabled=manual_disabled)
            bloodhound_max_results = st.slider("Bloodhound max results", 5, 150, int(bloodhound_max_results), step=5, disabled=manual_disabled)
            bloodhound_follow_links = st.checkbox("Follow relevant links", value=bloodhound_follow_links, disabled=manual_disabled)
            bloodhound_enable_cache = st.checkbox("Use search cache", value=bloodhound_enable_cache, disabled=manual_disabled)
            onion_allowed = bool(core_status.get("config", {}).get("enable_onion_search", False))
            bloodhound_enable_onion = st.checkbox(
                "Onion search",
                value=bloodhound_enable_onion,
                disabled=manual_disabled or not onion_allowed,
                help="Controlled by ENABLE_ONION_SEARCH/config. Public web search continues if Tor is unavailable.",
            )

            st.markdown("**Provider and local service overrides**")
            selected_provider_order = st.multiselect(
                "Provider fallback order",
                provider_options,
                default=configured_order,
                help="The backend tries providers in this order. Hugging Face stays local and lazy-disabled unless configured.",
            )
            provider_order = normalize_provider_order(selected_provider_order, provider_options)
            st.caption(f"Active order: {' -> '.join(provider_order)}")
            if demo_safe_mode:
                st.caption("ComfyUI URL: local service hidden")
                st.caption("HF local model: local model path hidden" if hf_local_model else "HF local model: not configured")
            else:
                comfyui_url = st.text_input("ComfyUI URL", value=configured_comfyui_url)
                hf_local_model = st.text_input(
                    "HF local model",
                    value=configured_hf_local_model,
                    help="Optional local Transformers model name/path. Leave blank to keep this provider disabled.",
                )

            if st.button("Save Runtime Settings"):
                runtime_config = dict(get_nexus_core().config)
                runtime_config.update(
                    {
                        "provider_order": provider_order,
                        "max_context_chars": int(max_context_chars),
                        "recent_message_limit": int(recent_message_limit),
                        "comfyui_url": comfyui_url.rstrip("/"),
                        "hf_local_model": hf_local_model.strip(),
                        "enable_reality_grounding": enable_reality_grounding,
                        "enable_reality_first_reasoning": enable_reality_first_reasoning,
                        "epistemic_mode": epistemic_mode,
                        "show_grounding_notes": show_grounding_notes,
                        "enable_reality_research_agent": reality_research_enabled,
                        "enable_bloodhound_search": bloodhound_enabled,
                        "max_search_results": int(bloodhound_max_results),
                        "enable_search_cache": bloodhound_enable_cache,
                        "enable_link_following": bloodhound_follow_links,
                    }
                )
                save_runtime_config(runtime_config)
                clear_runtime_caches()
                st.success("Runtime settings saved.")
                st.rerun()

        provider_health = {
            str(provider.get("name")): bool(provider.get("available"))
            for provider in core_status.get("providers", [])
        }
        primary_available = any(
            provider_health.get(provider)
            for provider in provider_order
            if provider != "fallback"
        )
        if not primary_available:
            st.warning("No primary provider is currently available; chat will use fallback until a local or optional provider is ready.")

        st.subheader("Persona")
        profile = chat_profile
        profile.enabled = st.checkbox("Use saved chat persona", value=profile.enabled)
        st.caption(f"Chat voice: {profile.assistant_name} for {profile.user_name}")

        creative_model = selected_model or ""
        technical_model = selected_model or ""
        sensitive_model = selected_model or ""
        current_info_model = selected_model or ""
        if status.models:
            with st.expander("Model routing", expanded=False):
                creative_model = _select_model_option("Creative / fiction model", status.models, selected_model or status.models[0])
                technical_model = _select_model_option("Technical / coding model", status.models, selected_model or status.models[0])
                sensitive_model = _select_model_option("Sensitive topic model", status.models, selected_model or status.models[0])
                current_info_model = _select_model_option("Current-info synthesis model", status.models, selected_model or status.models[0])

        st.subheader("Diagnostics")
        st.metric("Images", inventory["generated_images"])
        st.metric("Knowledge chunks", inventory["research_chunks"])
        if image_status["available"]:
            st.caption(f"Image provider: {image_status['label']}")
        else:
            st.caption(image_status["message"])

        if st.button("Clear chat", key="sidebar_clear_chat", width="stretch"):
            clear_chat_state()
            st.rerun()
        if st.button("Reset session", key="sidebar_reset_session", width="stretch"):
            reset_session_state()
            clear_runtime_caches()
            st.rerun()
        if st.button("Refresh app", width="stretch"):
            clear_runtime_caches()
            st.rerun()

        return {
            "provider_ready": status.available and bool(status.models),
            "ollama_running": status.available,
            "selected_model": selected_model,
            "base_url": status.base_url,
            "provider_message": status.message,
            "use_memory": use_memory,
            "use_knowledge_for_chat": use_knowledge_for_chat,
            "knowledge_top_k": int(knowledge_top_k),
            "knowledge_use_ai": bool(knowledge_use_ai),
            "use_web_for_chat": use_web_for_chat,
            "show_sources": show_sources,
            "show_perf_timings": show_perf_timings,
            "advanced_mode": advanced_mode,
            "demo_mode": demo_mode,
            "demo_safe_mode": demo_safe_mode,
            "auto_precision_mode": auto_precision_mode,
            "generation_timeout": float(generation_timeout),
            "provider_order": provider_order,
            "max_context_chars": int(max_context_chars),
            "recent_message_limit": int(recent_message_limit),
            "response_mode": response_mode,
            "verbosity_level": int(verbosity_level),
            "reasoning_depth": int(reasoning_depth),
            "staged_streaming": bool(staged_streaming),
            "enable_reality_grounding": bool(enable_reality_grounding),
            "enable_reality_first_reasoning": bool(enable_reality_first_reasoning),
            "enable_reality_research_agent": bool(reality_research_enabled),
            "epistemic_mode": epistemic_mode,
            "show_grounding_notes": bool(show_grounding_notes),
            "enable_bloodhound_search": bool(bloodhound_enabled),
            "bloodhound_depth": bloodhound_depth,
            "bloodhound_max_results": int(bloodhound_max_results),
            "bloodhound_timeout_seconds": int(core_status.get("config", {}).get("search_timeout_seconds") or 20),
            "bloodhound_follow_links": bool(bloodhound_follow_links),
            "bloodhound_enable_cache": bool(bloodhound_enable_cache),
            "bloodhound_enable_onion": bool(bloodhound_enable_onion),
            "hf_local_model": hf_local_model.strip(),
            "reality_research_depth": reality_research_depth,
            "reality_research_max_sources": int(bloodhound_max_results),
            "reality_research_follow_links": bool(bloodhound_follow_links),
            "reality_research_save_memory": True,
            "reality_research_show_weak": True,
            "reality_research_use_ai": True,
            "comfyui_url": comfyui_url.rstrip("/"),
            "chat_profile": profile,
            "router_config": RouterConfig(
                enabled=enable_router,
                god_mode=god_mode,
                freedom_level=freedom_level,
                use_llm_classifier=use_llm_classifier,
                show_debug=show_route_debug,
                default_model=selected_model or "",
                creative_model=creative_model,
                technical_model=technical_model,
                sensitive_model=sensitive_model,
                current_info_model=current_info_model,
            ),
        }


def build_chat_prompt(user_message: str, settings: dict[str, Any], route_decision) -> str:
    prompt, _context = get_nexus_core().build_chat_prompt(user_message, get_messages(), settings, route_decision)
    return prompt


def should_run_chat_search(message: str) -> Optional[str]:
    lowered = message.lower().strip()
    prefixes = [
        "search the web for",
        "search web for",
        "web search for",
        "look up",
        "find online",
        "find current info about",
        "research",
        "latest",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return message[len(prefix) :].strip() or message
    if any(token in lowered for token in ["latest ", "current ", "recent ", "today ", "breaking "]):
        return message.strip()
    return None


def answer_with_web_search(query: str, settings: dict[str, Any], model_override: Optional[str] = None) -> str:
    routed_settings = dict(settings)
    if model_override:
        routed_settings["selected_model"] = model_override
    research = get_nexus_core().run_web_research(query, routed_settings, max_results=5, save_locally=True)
    if not research["results"]:
        errors = "\n".join(f"- {error}" for error in research["errors"])
        return f"I could not find web results for that query.\n\n{errors}".strip()
    answer = research["summary"]
    if settings["show_sources"]:
        sources = "\n".join(
            f"- [{item.get('title') or item.get('url')}]({item.get('url')}) ({item.get('source')})"
            for item in research["results"]
            if item.get("url")
        )
        if sources and "source" not in answer.lower():
            answer = f"{answer}\n\nSources:\n{sources}"
    saved_paths = research.get("saved_paths") or {}
    if saved_paths:
        answer = f"{answer}\n\nSaved research:\n- JSON: `{saved_paths.get('json')}`\n- Markdown: `{saved_paths.get('markdown')}`"
    return answer


def is_capability_question(message: str) -> bool:
    lowered = " ".join((message or "").lower().strip().split())
    capability_phrases = [
        "what can you do",
        "what are your capabilities",
        "what can cognitive nexus do",
        "what can eni do",
        "show capabilities",
    ]
    return any(phrase in lowered for phrase in capability_phrases)


def generate_chat_response(user_message: str, settings: dict[str, Any]) -> str:
    started = time.perf_counter()
    response = get_nexus_core().generate_chat_response(user_message, get_messages(), settings)
    st.session_state.last_route_decision = get_nexus_core().last_route_decision
    st.session_state.last_provider_result = get_nexus_core().last_provider_result
    st.session_state.last_verification = get_nexus_core().last_verification
    st.session_state.last_response_plan = get_nexus_core().last_response_plan
    st.session_state.last_reality_audit = get_nexus_core().last_reality_audit
    st.session_state.last_trust_audit = get_nexus_core().last_trust_audit
    st.session_state.last_epistemic_assessment = get_nexus_core().last_epistemic_assessment
    st.session_state.last_reality_research_report = get_nexus_core().last_reality_research_report
    st.session_state.last_retrieval = get_nexus_core().last_retrieval
    st.session_state.last_memory = get_nexus_core().last_memory
    record_perf("chat.central_response", time.perf_counter() - started, settings)
    return response


def render_chat_tab(settings: dict[str, Any]) -> None:
    demo_safe = is_demo_safe(settings)
    header_col, clear_col, reset_col = st.columns([5, 1, 1])
    with header_col:
        st.subheader("Chat")
    with clear_col:
        if st.button("Clear Chat", key="chat_tab_clear_button", width="stretch"):
            clear_chat_state()
            st.rerun()
    with reset_col:
        if st.button("Reset", key="chat_tab_reset_button", width="stretch"):
            reset_session_state()
            clear_runtime_caches()
            st.rerun()

    if not settings.get("advanced_mode") and not get_messages():
        with st.expander("Welcome to Cognitive Nexus!", expanded=True):
            st.markdown("""
            **Cognitive Nexus** is a reality-first AI research platform that prioritizes factual accuracy and source verification.

            **Key Features:**
            - **Reality-First Research**: Grounded research with verdict quality assessment
            - **Web Search**: Bloodhound deep search with source trust scoring
            - **Local Knowledge**: Store and query your own documents
            - **Image Generation**: Create images with ComfyUI integration
            - **Adaptive Memory**: Learns from conversations for personalized responses

            **Getting Started:**
            1. Enable "Advanced mode" in the sidebar for full developer controls
            2. Try asking questions that require research or verification
            3. Use commands like "search web for..." or "research..."
            4. Upload documents in the Files/Knowledge tab

            **Tips:**
            - For casual chat, keep it simple - the system optimizes for speed
            - For research, use specific queries with sources
            - Check the Diagnostics tab for system health
            """)

    for message in get_messages():
        with st.chat_message(message.get("role", "assistant")):
            st.markdown(message.get("content", ""))

    show_advanced_debug = settings.get("advanced_mode") or settings["router_config"].show_debug
    if show_advanced_debug and demo_safe:
        st.info("Advanced raw chat diagnostics are hidden in Demo Safe Mode.")
        show_advanced_debug = False
    if show_advanced_debug and "last_route_decision" in st.session_state:
        with st.expander("Last route decision", expanded=False):
            st.json(st.session_state.last_route_decision)
    if show_advanced_debug and "last_response_plan" in st.session_state:
        plan = st.session_state.last_response_plan or {}
        with st.expander("Response planner", expanded=False):
            metric_cols = st.columns(4)
            metric_cols[0].metric("Mode", str(plan.get("mode", "auto")))
            metric_cols[1].metric("Intent", str(plan.get("intent", "unknown")))
            metric_cols[2].metric("Max tokens", int(plan.get("max_tokens", 0) or 0))
            metric_cols[3].metric("Context", int(plan.get("num_ctx", 0) or 0))
            st.json(plan)
    if show_advanced_debug and "last_retrieval" in st.session_state:
        retrieval = st.session_state.last_retrieval or {}
        if retrieval:
            with st.expander("Local knowledge retrieval", expanded=False):
                cols = st.columns(3)
                cols[0].metric("Enabled", "Yes" if retrieval.get("enabled") else "No")
                cols[1].metric("Matched chunks", int(retrieval.get("used_count", 0) or 0))
                cols[2].metric("Top K", int(retrieval.get("top_k", 0) or 0))
                if retrieval.get("error"):
                    st.warning(str(retrieval.get("error")))
                st.json(retrieval)
    if show_advanced_debug and "last_reality_audit" in st.session_state:
        audit = st.session_state.last_reality_audit or {}
        if audit.get("confidence"):
            with st.expander("Reality grounding", expanded=False):
                confidence = audit.get("confidence", {})
                hallucination = audit.get("hallucination", {})
                speculation = audit.get("speculation", {})
                source = audit.get("source_grounding", {})
                cols = st.columns(4)
                cols[0].metric("Confidence", str(confidence.get("level", "UNKNOWN")))
                cols[1].metric("Hallucination risk", float(hallucination.get("probability", 0) or 0))
                cols[2].metric("Speculation", str(speculation.get("category", "unknown")))
                cols[3].metric("Grounding", str(source.get("status", "unknown")))
                st.json(audit)
    if show_advanced_debug and "last_trust_audit" in st.session_state:
        trust = st.session_state.last_trust_audit or {}
        if trust:
            with st.expander("Prompt firewall / trust audit", expanded=False):
                user_audit = trust.get("user_request", {})
                cols = st.columns(3)
                cols[0].metric("User trust", str(user_audit.get("trust_level", "unknown")))
                cols[1].metric("Instruction risk", str(user_audit.get("instruction_risk", "unknown")))
                cols[2].metric("Signals", len(user_audit.get("signals", []) or []))
                st.json(trust)
    if show_advanced_debug and "last_epistemic_assessment" in st.session_state:
        epistemic = st.session_state.last_epistemic_assessment or {}
        if epistemic and epistemic.get("reality"):
            with st.expander("Reality-first reasoning", expanded=False):
                reality = epistemic.get("reality", {})
                feasibility = epistemic.get("feasibility", {})
                constraints = epistemic.get("constraints", {})
                cols = st.columns(4)
                cols[0].metric("Reality", str(reality.get("reality_status", "unknown")))
                cols[1].metric("Feasibility", str(feasibility.get("level", "unknown")))
                cols[2].metric("Score", float(feasibility.get("score", 0) or 0))
                cols[3].metric("Mode", str(constraints.get("epistemic_mode", "auto")))
                st.json(epistemic)

    user_message = st.chat_input("Message Cognitive Nexus")
    if not user_message:
        return

    add_message("user", user_message)
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        started = time.perf_counter()
        provider_order = list(settings.get("provider_order") or [])
        primary_provider = next((provider for provider in provider_order if provider != "fallback"), "fallback")
        selected_model = str(settings.get("selected_model") or "").strip()
        if primary_provider == "ollama" and selected_model:
            status_label = f"Generating with Ollama / {selected_model}..."
        elif primary_provider == "fallback":
            status_label = "Checking provider fallback path..."
        else:
            status_label = f"Generating with {primary_provider}..."
        response_status = st.empty()
        try:
            with response_status.status(status_label, expanded=False):
                response = st.write_stream(get_nexus_core().stream_chat_response(user_message, get_messages(), settings))
        except Exception as exc:
            response_status.error(f"Response failed: {exc}")
            raise
        response_status.empty()
        st.session_state.last_route_decision = get_nexus_core().last_route_decision
        st.session_state.last_provider_result = get_nexus_core().last_provider_result
        st.session_state.last_verification = get_nexus_core().last_verification
        st.session_state.last_response_plan = get_nexus_core().last_response_plan
        st.session_state.last_reality_audit = get_nexus_core().last_reality_audit
        st.session_state.last_trust_audit = get_nexus_core().last_trust_audit
        st.session_state.last_epistemic_assessment = get_nexus_core().last_epistemic_assessment
        st.session_state.last_reality_research_report = get_nexus_core().last_reality_research_report
        st.session_state.last_retrieval = get_nexus_core().last_retrieval
        st.session_state.last_memory = get_nexus_core().last_memory
        plan = st.session_state.last_response_plan or {}
        show_advanced_debug = settings.get("advanced_mode") or settings["router_config"].show_debug
        if plan:
            st.caption(
                f"Planner: {plan.get('mode', 'auto')} / {plan.get('intent', 'unknown')} "
                f"/ max {plan.get('max_tokens', '?')} tokens"
            )
        if show_advanced_debug:
            audit = st.session_state.last_reality_audit or {}
            if audit.get("confidence"):
                confidence = audit["confidence"]
                hallucination = audit.get("hallucination", {})
                speculation = audit.get("speculation", {})
                st.caption(
                    f"Grounding: {confidence.get('level', 'UNKNOWN')} | "
                    f"hallucination risk {hallucination.get('probability', 0)} | "
                    f"{speculation.get('category', 'unclassified')}"
                )
            epistemic = st.session_state.last_epistemic_assessment or {}
            if epistemic.get("reality"):
                st.caption(
                    f"Reality-first: {epistemic['reality'].get('reality_status', 'unknown')} | "
                    f"feasibility {epistemic.get('feasibility', {}).get('level', 'unknown')}"
                )
        record_perf("chat.stream_response", time.perf_counter() - started, settings)

    if settings.get("show_perf_timings") and "last_provider_result" in st.session_state and not demo_safe:
        timings = st.session_state.last_provider_result.get("timings", {})
        if timings:
            with st.expander("Performance Timings", expanded=False):
                st.json(timings)

    add_message("assistant", response)
    save_session_history()


def render_reality_research_tab(settings: dict[str, Any]) -> None:
    st.subheader("Reality-First Research Agent")
    st.caption("Search deeply, extract claims, score source trust, detect contradictions, save a grounded report.")
    demo_safe = is_demo_safe(settings)

    query = st.text_area(
        "Research question",
        height=110,
        placeholder="Example: Research this topic deeply and separate confirmed facts from weak leads.",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        depth = st.selectbox("Research depth", ["Quick", "Standard", "Deep", "Extreme"], index=1)
        max_sources = st.slider("Max sources", 5, 150, int(settings.get("reality_research_max_sources", 25)), step=5)
    with col2:
        follow_links = st.checkbox("Follow links", value=bool(settings.get("reality_research_follow_links", True)))
        save_to_memory = st.checkbox("Save to memory", value=True)
    with col3:
        show_weak = st.checkbox("Show weak matches", value=True)
        use_ai_summary = st.checkbox("Provider synthesis", value=True)

    disabled = not bool(settings.get("enable_reality_research_agent", True))
    if disabled:
        st.info("Reality-First Research Agent is disabled in the sidebar settings.")

    if st.button("Run Reality-First Research", type="primary", disabled=disabled):
        if not query.strip():
            st.warning("Enter a research question first.")
            return
        request = ResearchRequest(
            query=query,
            depth=depth,
            max_sources=int(max_sources),
            follow_links=follow_links,
            save_to_memory=save_to_memory,
            show_weak_matches=show_weak,
            use_ai_summary=use_ai_summary,
            save_report=True,
        )
        progress_lines: list[str] = []
        with st.status("Reality-first research running...", expanded=True) as status:
            def progress(message: str) -> None:
                if message not in progress_lines:
                    progress_lines.append(message)
                    st.write(message)

            started = time.perf_counter()
            report = get_nexus_core().run_reality_research(
                request,
                settings | {"reality_research_depth": depth},
                progress_callback=progress,
            )
            record_perf("reality_research.run", time.perf_counter() - started, settings)
            status.update(label="Reality-first research complete", state="complete")

        st.session_state.last_reality_research_report = report.to_dict()
        st.markdown("### Final Answer")
        st.markdown(report.final_answer or report.summary)

        metric_cols = st.columns(5)
        metric_cols[0].metric("Sources", len(report.sources))
        metric_cols[1].metric("Claims", len(report.claims))
        metric_cols[2].metric("Contradictions", len(report.contradictions))
        metric_cols[3].metric("Memory", "Saved" if report.memory_saved else "Not saved")
        metric_cols[4].metric("Errors", len(report.errors))

        if report.saved_paths:
            if demo_safe:
                st.success("Report saved locally. File paths hidden in Demo Safe Mode.")
            else:
                st.success(f"JSON report: {report.saved_paths.get('json')}")
                st.success(f"Markdown report: {report.saved_paths.get('markdown')}")
        if report.errors:
            st.warning("\n".join(report.errors[:8]))

        st.markdown("### Best Sources")
        for source in report.sources[:20]:
            st.markdown(f"**[{source.title or source.url}]({source.url})**")
            st.caption(
                f"{source.source} | {source.source_type} | match {source.match_strength} | "
                f"trust {source.trust_label} ({source.trust_score})"
            )
            st.write(source.excerpt or source.snippet)

        with st.expander("Extracted claims", expanded=False):
            if not report.claims:
                st.info("No factual-looking claims were extracted.")
            for claim in report.claims[:40]:
                st.markdown(f"- **{claim.evidence_strength}** `{claim.claim_type}` {claim.text}")
                st.caption(claim.source_url)

        with st.expander("Potential contradictions", expanded=False):
            if not report.contradictions:
                st.info("No direct contradictions were detected by the lightweight checker.")
            for item in report.contradictions:
                st.warning(f"{item.severity}: {item.reason}")
                st.caption(f"A: {item.claim_a}")
                st.caption(f"B: {item.claim_b}")

        if demo_safe:
            st.caption("Full report JSON hidden in Demo Safe Mode.")
        else:
            with st.expander("Full report JSON", expanded=False):
                st.json(report.to_dict())

    if st.session_state.get("last_reality_research_report") and not demo_safe:
        with st.expander("Last Reality-First Research Report", expanded=False):
            st.json(st.session_state.last_reality_research_report)


def format_bytes(size: Any) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        value = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def image_provider_status_rows(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider in providers:
        available = bool(provider.get("available"))
        implemented = bool(provider.get("implemented"))
        if available and implemented:
            status = "Ready"
        elif available:
            status = "Workflow only"
        else:
            status = "Offline"
        rows.append(
            {
                "Provider": provider.get("label") or provider.get("name", "unknown"),
                "Status": status,
                "Direct generation": "Yes" if implemented else "No",
                "Endpoint": provider.get("url") or "",
                "Model": provider.get("model") or "",
                "Message": provider.get("message") or "",
            }
        )
    return rows


def image_generation_ready(provider_name: str, providers: list[dict[str, Any]]) -> tuple[bool, str]:
    usable = [provider for provider in providers if provider.get("available") and provider.get("implemented")]
    if provider_name == "auto":
        if usable:
            return True, f"Auto will use {usable[0].get('label', usable[0].get('name', 'provider'))}."
        return (
            False,
            "No direct image provider is ready. Start Automatic1111 with API enabled or install the local Diffusers backend.",
        )

    selected = next((provider for provider in providers if provider.get("name") == provider_name), None)
    if not selected:
        return False, "Selected image provider was not detected."
    if not selected.get("available"):
        return False, selected.get("message") or "Selected image provider is offline."
    if not selected.get("implemented"):
        return (
            False,
            selected.get("message")
            or "This provider is reachable, but direct txt2img generation is not implemented here.",
        )
    return True, f"{selected.get('label', provider_name)} is ready."


def sanitize_image_generation_result(result: dict[str, Any]) -> dict[str, Any]:
    saved = result.get("saved") or []
    return {
        "success": bool(result.get("success")),
        "provider": result.get("provider"),
        "saved_count": len(saved),
        "error": result.get("error"),
        "saved": saved,
    }


def render_image_tab(settings: dict[str, Any] | None = None) -> None:
    st.subheader("Image Generation")
    demo_safe = is_demo_safe(settings)
    providers = get_cached_image_providers()
    image_summary = get_cached_image_summary()
    usable_providers = [provider for provider in providers if provider.get("available") and provider.get("implemented")]
    provider_names = ["auto"] + [provider["name"] for provider in providers]
    provider_labels = {"auto": "Auto"}
    provider_labels.update({provider["name"]: provider.get("label", provider["name"]) for provider in providers})

    status_cols = st.columns(4)
    status_cols[0].metric(
        "Direct provider",
        usable_providers[0].get("label", "Ready") if usable_providers else "Offline",
    )
    status_cols[1].metric("Saved images", int(image_summary.get("image_files", 0) or 0))
    status_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    status_cols[3].metric("Gallery size", format_bytes(image_summary.get("total_bytes", 0)))

    refresh_cols = st.columns([1, 3])
    with refresh_cols[0]:
        if st.button("Refresh image providers", key="refresh_image_providers", width="stretch"):
            get_cached_image_provider.clear()
            get_cached_image_providers.clear()
            get_cached_image_summary.clear()
            st.rerun()
    with refresh_cols[1]:
        if usable_providers:
            st.caption(f"Ready for direct generation: {', '.join(str(item.get('label', item.get('name'))) for item in usable_providers)}")
        else:
            st.warning("Direct image generation is offline. ComfyUI workflows can still run when ComfyUI is reachable below.")

    with st.expander("Image provider status", expanded=not bool(usable_providers)):
        st.dataframe(sanitize_demo_rows(image_provider_status_rows(providers), enabled=demo_safe), width="stretch", hide_index=True)

    prompt = st.text_area("Prompt", height=120, placeholder="Describe the image you want to generate.")
    negative_prompt = st.text_area("Negative prompt", height=80, placeholder="Optional things to avoid.")
    col1, col2, col3 = st.columns(3)
    with col1:
        provider = st.selectbox("Provider", provider_names, format_func=lambda value: provider_labels.get(value, value))
        width = st.slider("Width", 256, 1536, 512, step=64)
        steps = st.slider("Steps", 1, 80, 25)
    with col2:
        model = st.text_input("Model name", value="")
        height = st.slider("Height", 256, 1536, 512, step=64)
        cfg_scale = st.slider("CFG scale", 1.0, 20.0, 7.0, step=0.5)
    with col3:
        style = st.selectbox("Style", list(IMAGE_STYLE_OPTIONS))
        seed_text = st.text_input("Seed", value="", placeholder="Blank = random")
        num_images = st.number_input("Number of images", min_value=1, max_value=4, value=1, step=1)
    save_outputs = st.checkbox("Save outputs", value=True)
    generation_ready, readiness_message = image_generation_ready(provider, providers)
    if generation_ready:
        st.caption(readiness_message)
    else:
        st.info(readiness_message)

    if st.button("Generate Images", type="primary", disabled=not generation_ready):
        if not prompt.strip():
            st.warning("Enter an image prompt first.")
            return
        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            st.warning("Seed must be a whole number or blank.")
            return
        req = ImageGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            num_images=int(num_images),
            provider=provider,
            model=model,
            style=style,
            save_outputs=save_outputs,
        )
        with st.spinner("Generating image..."):
            started = time.perf_counter()
            result = get_nexus_core().generate_image(req)
            record_perf("image.generate", time.perf_counter() - started)
            get_cached_gallery.clear()
            get_cached_image_summary.clear()
        st.session_state.last_image_generation_result = sanitize_image_generation_result(result)
        if not result.get("success"):
            st.error(result.get("error") or "Image generation failed.")
        else:
            st.success("Image generation complete.")
            result_images = result.get("images") or []
            for index, item in enumerate(result.get("saved", [])):
                image_path = item.get("file_path")
                if image_path:
                    st.image(image_path, caption=item.get("prompt", prompt), width="stretch")
                elif index < len(result_images):
                    st.image(result_images[index], caption=item.get("prompt", prompt), width="stretch")
                if demo_safe:
                    st.caption("Image metadata path hidden in Demo Safe Mode.")
                else:
                    with st.expander("Metadata", expanded=False):
                        st.json(item)
            st.divider()
            render_gallery(settings, limit=24)

    st.divider()
    render_comfyui_workflow_section(settings)


def render_comfyui_workflow_section(settings: dict[str, Any] | None = None) -> None:
    st.subheader("ComfyUI Workflows")
    demo_safe = is_demo_safe(settings)
    core = get_nexus_core()
    status = core.comfyui.detect()
    if status.available:
        st.success(sanitize_demo_text(status.message) if demo_safe else status.message)
    else:
        status_message = sanitize_demo_text(status.message) if demo_safe else status.message
        st.info(f"{status_message} Start ComfyUI and confirm the URL in Settings.")

    uploaded = st.file_uploader("Upload ComfyUI API workflow JSON", type=["json"], key="comfyui_workflow_upload")
    if uploaded and st.button("Save uploaded workflow", key="save_comfy_workflow"):
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            path = core.comfyui.save_workflow(payload, uploaded.name)
            st.success("Workflow saved locally." if demo_safe else f"Saved workflow: {path}")
        except Exception as exc:
            st.error(f"Could not save workflow: {exc}")

    workflows = core.comfyui.list_workflows()
    selected_workflow = None
    if workflows:
        selected_workflow = st.selectbox("Saved workflow", workflows, format_func=lambda path: path.name)
    else:
        st.caption("No saved workflows yet. Export an API-format workflow from ComfyUI and upload it here.")

    prompt = st.text_area("Workflow prompt", height=90, key="comfy_prompt")
    negative_prompt = st.text_area("Workflow negative prompt", height=60, key="comfy_negative_prompt")
    timeout = st.slider("Workflow timeout seconds", 30, 600, 240, step=30)

    disabled = not status.available or selected_workflow is None
    if st.button("Run ComfyUI Workflow", type="primary", disabled=disabled):
        try:
            workflow = core.comfyui.load_workflow(Path(selected_workflow))
            with st.status("Running ComfyUI workflow...", expanded=True) as run_status:
                result = core.run_comfyui_workflow(
                    workflow=workflow,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    timeout=float(timeout),
                )
                run_status.update(label="ComfyUI workflow complete", state="complete" if result.success else "error")
            if not result.success:
                st.error(result.error or "ComfyUI workflow failed.")
                return
            st.success(f"ComfyUI prompt id: {result.prompt_id}")
            for image in result.images:
                path = image.get("path")
                if path and Path(path).exists():
                    st.image(path, caption=Path(path).name, width="stretch")
            if result.metadata_path:
                st.caption("Metadata saved locally." if demo_safe else f"Metadata saved: {result.metadata_path}")
        except Exception as exc:
            st.error(f"ComfyUI workflow failed: {exc}")


def local_image_data_uri(path: Path) -> str:
    """Return a browser-safe data URI for a local image file."""

    try:
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/png")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


def gallery_card_html(
    *,
    data_uri: str,
    prompt: str,
    provider: str,
    timestamp: str,
    file_name: str,
    details: str,
) -> str:
    """Render a stable gallery tile without Streamlit's fragile image widget."""

    safe_prompt = html.escape(prompt.strip() or file_name)
    safe_provider = html.escape(provider.strip() or "unknown provider")
    safe_time = html.escape(timestamp.strip())
    safe_name = html.escape(file_name)
    safe_details = html.escape(details.strip())
    return f"""
<div style="border:1px solid #e6e8ef;border-radius:8px;padding:10px;margin-bottom:18px;background:#fff;">
  <img src="{data_uri}" alt="{safe_name}" style="width:100%;height:180px;object-fit:contain;border-radius:6px;display:block;background:#f2f4f7;" />
  <div style="font-weight:600;margin-top:8px;line-height:1.25;">{safe_prompt}</div>
  <div style="color:#667085;font-size:0.82rem;margin-top:6px;">{safe_provider}</div>
  <div style="color:#98a2b3;font-size:0.78rem;margin-top:3px;">{safe_time}</div>
  <div style="color:#98a2b3;font-size:0.78rem;margin-top:3px;">{safe_details}</div>
</div>
"""


def render_gallery(settings: dict[str, Any] | None = None, limit: int = 50) -> None:
    st.subheader("Gallery")
    demo_safe = is_demo_safe(settings)
    items = get_cached_gallery(limit)
    if not items:
        st.info("No generated images found yet.")
        return

    image_summary = get_cached_image_summary()
    gallery_cols = st.columns(4)
    gallery_cols[0].metric("Showing", len(items))
    gallery_cols[1].metric("PNG artifacts", int(image_summary.get("image_files", 0) or 0))
    gallery_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    gallery_cols[3].metric("Storage", format_bytes(image_summary.get("total_bytes", 0)))
    missing_records = int(image_summary.get("missing_image_records", 0) or 0)
    invalid_metadata = int(image_summary.get("invalid_metadata", 0) or 0)
    if missing_records or invalid_metadata:
        st.warning(f"Gallery integrity: {missing_records} metadata records point to missing images; {invalid_metadata} metadata files could not be read.")

    st.caption("Recent generated images and legacy outputs. Broken or missing files are skipped cleanly.")
    cols = st.columns(3)
    for index, item in enumerate(items):
        with cols[index % 3]:
            path = item.get("file_path") or item.get("path")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if not path:
                st.warning("Image record is missing a file path.")
                continue

            image_path = Path(path)
            if not image_path.exists():
                st.warning(f"Missing image file: {image_path.name}")
                continue

            prompt = (
                metadata.get("prompt")
                or item.get("prompt")
                or item.get("name")
                or image_path.name
            )
            provider = metadata.get("provider") or item.get("provider") or "unknown provider"
            timestamp = metadata.get("timestamp") or item.get("timestamp") or item.get("created_at") or ""
            details = f"{image_path.name} | {format_bytes(item.get('size', 0))}"
            data_uri = local_image_data_uri(image_path)
            if not data_uri:
                st.warning(f"Could not load image: {image_path.name}")
                continue
            st.markdown(
                gallery_card_html(
                    data_uri=data_uri,
                    prompt=str(prompt),
                    provider=str(provider),
                    timestamp=str(timestamp),
                    file_name=image_path.name,
                    details=details,
                ),
                unsafe_allow_html=True,
            )
            with st.expander("Artifact metadata", expanded=False):
                if demo_safe:
                    st.caption("Local artifact path and raw metadata hidden in Demo Safe Mode.")
                elif metadata:
                    st.caption(str(image_path))
                    st.json(metadata)
                else:
                    st.caption("No JSON metadata was found for this legacy image.")


def render_web_research_tab(settings: dict[str, Any]) -> None:
    st.subheader("Web Research")
    demo_safe = is_demo_safe(settings)
    query = st.text_input("Search query", placeholder="What should Cognitive Nexus research?")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        max_results = st.slider("Results", 1, 10, 5)
    with col2:
        scrape_pages = st.checkbox("Scrape pages", value=True)
    with col3:
        summarize = st.checkbox("Summarize with AI", value=True)
    with col4:
        save_locally = st.checkbox("Save locally", value=True)
    save_to_memory = st.checkbox("Add cleaned research to local knowledge memory", value=True)

    if st.button("Run Web Research", type="primary"):
        if not query.strip():
            st.warning("Enter a search query first.")
            return
        with st.status("Researching...", expanded=True) as status:
            research = get_nexus_core().run_web_research(
                query,
                max_results=max_results,
                scrape_pages=scrape_pages,
                summarize_with_ai=summarize,
                save_locally=save_locally,
                save_to_memory=save_to_memory,
                settings=settings,
            )
            status.update(label="Research complete", state="complete")
        if research["errors"]:
            st.warning("\n".join(research["errors"]))
        st.markdown("### Summary")
        st.markdown(research["summary"])
        if research.get("saved_paths"):
            if demo_safe:
                st.success("Research saved locally. File paths hidden in Demo Safe Mode.")
            else:
                st.success(f"Saved JSON: {research['saved_paths'].get('json')}")
                st.success(f"Saved Markdown: {research['saved_paths'].get('markdown')}")
        st.markdown("### Sources")
        for result in research["results"]:
            st.markdown(f"**[{result.get('title') or result.get('url')}]({result.get('url')})**")
            st.caption(result.get("source", ""))
            st.write(result.get("snippet", ""))
        with st.expander("Scraped page previews", expanded=False):
            for page in research["scraped_pages"]:
                st.markdown(f"**[{page.get('title') or page.get('url')}]({page.get('url')})**")
                if page.get("success"):
                    st.write(page.get("excerpt", ""))
                else:
                    st.warning(page.get("error", "Scrape failed."))


def render_files_knowledge_tab(settings: dict[str, Any]) -> None:
    st.subheader("Files / Knowledge")
    demo_safe = is_demo_safe(settings)
    module = get_cached_research_module()
    url = st.text_input("Ingest URL")
    if st.button("Process URL"):
        try:
            result = process_url(module, url)
            if result.get("status") == "success":
                st.success(f"Stored {result.get('chunks_count', 0)} chunks from {result.get('title', url)}")
            else:
                st.error(result.get("error", "URL processing failed."))
        except Exception as exc:
            st.error(str(exc))

    uploaded = st.file_uploader("Upload text, markdown, JSON, or CSV", type=["txt", "md", "json", "csv"])
    if uploaded and st.button("Ingest uploaded file"):
        text = uploaded.getvalue().decode("utf-8", errors="ignore")
        result = ingest_text(module, name=uploaded.name, text=text, source_type="upload")
        if result.get("status") == "success":
            st.success(f"Stored {result.get('chunks_count', 0)} chunks from {uploaded.name}")
        else:
            st.error(result.get("error", "File ingestion failed."))

    st.divider()
    st.markdown("### Markdown Knowledge Notes")
    with st.form("manual_knowledge_note_form"):
        note_title = st.text_input("Note title", placeholder="A useful thing Cognitive Nexus should remember")
        note_tags = st.text_input("Tags", placeholder="research, preference, project")
        note_body = st.text_area("Note", height=160, placeholder="Write a local Markdown note to save and retrieve later.")
        ingest_note = st.checkbox("Add note to retrieval store", value=True)
        saved_note = st.form_submit_button("Save Markdown Note")
    if saved_note:
        result = save_knowledge_note(
            module,
            title=note_title,
            text=note_body,
            tags=note_tags,
            ingest=ingest_note,
        )
        if result.get("status") == "success":
            st.success("Saved note locally." if demo_safe else f"Saved note: {result.get('path')}")
            if result.get("ingested"):
                st.caption(f"Added {result.get('chunks_count', 0)} chunk(s) to local retrieval.")
            get_cached_project_inventory.clear()
        else:
            st.error(result.get("error", "Could not save note."))

    summary = module.get_processing_summary()
    embedding_status = summary.get("embedding_status", {})
    st.caption(
        f"Retrieval backend: {embedding_status.get('runtime_backend', summary.get('embedding_backend', 'unknown'))} | "
        f"Model: {embedding_status.get('model', summary.get('embedding_model', 'unknown'))}"
    )

    notes = list_knowledge_notes(limit=8)
    if notes:
        with st.expander("Recent Markdown notes", expanded=False):
            st.dataframe(
                [
                    {
                        "Title": note.get("title", ""),
                        "Tags": note.get("tags", ""),
                        "File": note.get("file_name", ""),
                        "Excerpt": note.get("excerpt", ""),
                    }
                    for note in notes
                ],
                width="stretch",
                hide_index=True,
            )

    st.divider()
    query = st.text_input("Ask local knowledge")
    top_k = st.slider("Knowledge results", 1, 10, 5)
    if st.button("Query Knowledge"):
        if not query.strip():
            st.warning("Enter a knowledge query first.")
            return
        result = get_nexus_core().answer_knowledge(query, settings, top_k=top_k)
        st.markdown(result["answer"])
        if demo_safe:
            st.caption(f"Retrieved chunks hidden in Demo Safe Mode ({len(result.get('results') or [])} result(s)).")
        else:
            with st.expander("Retrieved chunks", expanded=False):
                st.json(result["results"])


def render_memory_tab(settings: dict[str, Any]) -> None:
    st.subheader("Memory")
    demo_safe = is_demo_safe(settings)
    messages = get_messages()
    profile_summary = load_user_profile_summary()
    memory_cols = st.columns(4)
    memory_cols[0].metric("Chat messages", len(messages))
    memory_cols[1].metric("Saved local facts", int(profile_summary.get("fact_count", 0) or 0))
    memory_cols[2].metric("Preferences", int(profile_summary.get("preference_count", 0) or 0))
    memory_cols[3].metric("Patterns", int(profile_summary.get("pattern_count", 0) or 0))
    if messages and not demo_safe:
        last_msg = messages[-1]
        st.caption(f"Last: {last_msg.get('role', 'unknown')}: {last_msg.get('content', '')[:100]}...")
    elif messages:
        st.caption("Latest private chat content hidden in Demo Safe Mode.")
    profile = settings["chat_profile"]
    st.metric("Persona enabled", "Yes" if profile.enabled else "No")
    if profile.enabled:
        st.caption(f"Assistant: {profile.assistant_name}")
    memory = get_adaptive_memory()
    if memory is None:
        st.info("Adaptive memory module is unavailable.")
    else:
        st.metric("Memory candidates", len(getattr(memory, "memory_candidates", [])))
    if profile_summary.get("facts") and demo_safe:
        st.info("Saved local facts are present, but raw memory contents are hidden in Demo Safe Mode.")
    elif profile_summary.get("facts"):
        with st.expander("Saved local facts", expanded=True):
            st.dataframe(profile_summary["facts"], width="stretch", hide_index=True)
    notes = list_knowledge_notes(limit=12)
    st.metric("Markdown knowledge notes", len(notes))
    if notes:
        with st.expander("Saved Markdown notes", expanded=False):
            st.dataframe(
                [
                    {
                        "Title": note.get("title", ""),
                        "Tags": note.get("tags", ""),
                        "File": note.get("file_name", ""),
                        "Excerpt": note.get("excerpt", ""),
                    }
                    for note in notes
                ],
                width="stretch",
                hide_index=True,
            )
    if settings.get("advanced_mode") and demo_safe:
        st.info("Raw session chat, persona, and adaptive memory internals are hidden in Demo Safe Mode.")
    elif settings.get("advanced_mode"):
        with st.expander("Raw session chat", expanded=False):
            st.json(messages)
        with st.expander("Raw chat persona", expanded=False):
            st.json(profile.to_dict())
        if memory:
            for attr in ("user_profile", "memory_candidates", "feedback_log"):
                if hasattr(memory, attr):
                    with st.expander(f"Raw {attr}", expanded=False):
                        st.write(getattr(memory, attr))


def render_tools_tab(settings: dict[str, Any] | None = None) -> None:
    st.subheader("Tools / Utilities")
    demo_safe = is_demo_safe(settings)
    tools = get_cached_project_tools()
    if not tools:
        st.info("No project tools detected.")
    else:
        st.dataframe(tools, width="stretch")

    st.markdown("### Self-Improvement")
    skill_path = PROJECT_ROOT / "skills" / "self-improvement" / "SKILL.md"
    learning_dir = PROJECT_ROOT / ".learnings"
    log_files = [
        learning_dir / "LEARNINGS.md",
        learning_dir / "ERRORS.md",
        learning_dir / "FEATURE_REQUESTS.md",
    ]

    col1, col2 = st.columns(2)
    col1.metric("Skill", "Installed" if skill_path.exists() else "Missing")
    col2.metric("Learning logs", f"{sum(path.exists() for path in log_files)}/{len(log_files)}")
    st.caption("Agent workflow: log corrections, failures, missing capabilities, and reusable discoveries in .learnings.")

    existing_logs = [path for path in log_files if path.exists()]
    if existing_logs and demo_safe:
        st.caption("Learning log contents are hidden in Demo Safe Mode.")
    elif existing_logs:
        selected_log = st.selectbox("Learning log", existing_logs, format_func=lambda path: path.name)
        st.text_area("Latest entries", tail_file(selected_log, max_chars=3000), height=220, disabled=True)


def render_diagnostics_tab(status, inventory: dict[str, Any], image_status: dict[str, Any], core_status: dict[str, Any], settings: dict[str, Any]) -> None:
    st.subheader("Diagnostics")
    st.caption("Live control-center view of providers, grounding, memory, search, and saved outputs.")
    demo_safe = is_demo_safe(settings)
    if demo_safe:
        st.info("Demo Safe Mode is on. Raw paths, environment details, logs, private memory, and machine-specific diagnostics are hidden.")

    provider_order = tuple(settings.get("provider_order") or core_status.get("config", {}).get("provider_order", []))
    selected_model = str(settings.get("selected_model") or "")
    quick_core_health = get_cached_core_health(provider_order, selected_model)
    core_health = st.session_state.get("last_core_health_check") or quick_core_health
    last_provider = st.session_state.get("last_provider_result") or {}
    last_route = st.session_state.get("last_route_decision") or {}
    last_plan = st.session_state.get("last_response_plan") or {}
    last_audit = st.session_state.get("last_reality_audit") or {}
    last_trust = st.session_state.get("last_trust_audit") or {}
    last_epistemic = st.session_state.get("last_epistemic_assessment") or {}
    last_report = st.session_state.get("last_reality_research_report") or {}
    last_retrieval = st.session_state.get("last_retrieval") or last_provider.get("retrieval") or {}
    last_memory = st.session_state.get("last_memory") or last_provider.get("memory") or {}

    confidence = last_audit.get("confidence", {}) if isinstance(last_audit, dict) else {}
    hallucination = last_audit.get("hallucination", {}) if isinstance(last_audit, dict) else {}
    speculation = last_audit.get("speculation", {}) if isinstance(last_audit, dict) else {}
    source_grounding = last_audit.get("source_grounding", {}) if isinstance(last_audit, dict) else {}
    fallback_reason = str(last_provider.get("fallback_reason") or last_provider.get("error") or "").strip()

    st.markdown("### Engine Snapshot")
    top_cols = st.columns(5)
    top_cols[0].metric("Ollama", "Connected" if status.available else "Offline")
    top_cols[1].metric("Answered by", str(last_provider.get("provider") or "No turn yet"))
    top_cols[2].metric("Knowledge chunks", int(inventory.get("research_chunks", 0) or 0))
    top_cols[3].metric("Grounding", str(confidence.get("level", "No audit yet")))
    top_cols[4].metric("Reports", int(inventory.get("research_reports", 0) or 0))

    if fallback_reason:
        st.warning(f"Fallback reason: {sanitize_demo_text(fallback_reason) if demo_safe else fallback_reason}")
    else:
        st.caption("Fallback reason: none recorded for the latest turn.")

    st.markdown("### Core Stability Self-Check")
    action_cols = st.columns([1, 1, 4])
    if action_cols[0].button("Run live model probe", key="run_core_health_probe"):
        with st.status("Running core stability self-check...", expanded=True) as health_status_box:
            st.write("Checking imports, local storage, provider detection, and one tiny local model response.")
            core_health = run_core_health_check(
                PROJECT_ROOT,
                provider_order=provider_order,
                selected_model=selected_model,
                include_probe=True,
            )
            st.session_state.last_core_health_check = core_health
            health_status_box.update(label="Core stability self-check complete", state="complete")
    if action_cols[1].button("Refresh quick check", key="refresh_core_health"):
        get_cached_core_health.clear()
        st.session_state.last_core_health_check = run_core_health_check(
            PROJECT_ROOT,
            provider_order=provider_order,
            selected_model=selected_model,
            include_probe=False,
        )
        core_health = st.session_state.last_core_health_check
    action_cols[2].caption(f"Last self-check: {core_health.get('generated_at', 'not run')}")

    health_summary = core_health.get("summary", {})
    health_status = str(health_summary.get("status", "unknown"))
    health_cols = st.columns(5)
    health_cols[0].metric("Overall", health_status.title())
    health_cols[1].metric("Import errors", int(health_summary.get("import_errors", 0) or 0))
    health_cols[2].metric("Storage errors", int(health_summary.get("storage_errors", 0) or 0))
    health_cols[3].metric("Real providers", len(health_summary.get("ready_model_providers", []) or []))
    health_cols[4].metric("Probe", str(health_summary.get("probe_status", "not_run")))

    health_message = str(health_summary.get("message") or "No self-check message.")
    if health_status == "ok":
        st.success(health_message)
    elif health_status == "error":
        st.error(health_message)
    else:
        st.warning(health_message)

    probe = core_health.get("probe") or {}
    if probe.get("status") == "ok":
        probe_model = "Local model" if demo_safe else probe.get("model", "unknown")
        st.caption(
            f"Live probe answered through {probe.get('provider', 'unknown')} / "
            f"{probe_model} in {float(probe.get('elapsed_seconds', 0) or 0):.2f}s."
        )
    elif probe.get("status") == "error":
        probe_error = sanitize_demo_text(probe.get("error") or "unknown error") if demo_safe else (probe.get("error") or "unknown error")
        st.warning(f"Live probe failed: {probe_error}")

    if demo_safe:
        st.caption("Core self-check details are hidden in Demo Safe Mode.")
    else:
        with st.expander("Core self-check details", expanded=health_status != "ok"):
            st.markdown("Imports")
            st.dataframe(core_health.get("imports", []), width="stretch", hide_index=True)
            st.markdown("Providers")
            st.dataframe(core_health.get("providers", []), width="stretch", hide_index=True)
            st.markdown("Local storage")
            st.dataframe(core_health.get("storage", []), width="stretch", hide_index=True)
            recent_log_signals = core_health.get("recent_log_signals") or []
            if recent_log_signals:
                st.markdown("Recent log signals")
                st.dataframe(recent_log_signals, width="stretch", hide_index=True)

    providers = core_status.get("providers", [])
    if providers:
        st.markdown("### Provider Health")
        provider_rows = []
        for provider in providers:
            models = provider.get("models") or []
            provider_rows.append(
                {
                    "Provider": str(provider.get("name", "unknown")).title(),
                    "Status": "Available" if provider.get("available") else "Offline",
                    "Models": len(models),
                    "Endpoint": "Local service hidden" if demo_safe and provider.get("base_url") else provider.get("base_url", ""),
                    "Message": sanitize_demo_text(provider.get("message", "")) if demo_safe else provider.get("message", ""),
                }
            )
        st.dataframe(provider_rows, width="stretch", hide_index=True)
    else:
        st.info("No providers configured.")

    st.markdown("### Local Knowledge Retrieval")
    retrieval_cols = st.columns(5)
    retrieval_cols[0].metric("Enabled", "Yes" if last_retrieval.get("enabled") else "No")
    retrieval_cols[1].metric("Matched chunks", int(last_retrieval.get("used_count", 0) or 0))
    retrieval_cols[2].metric("Raw results", int(last_retrieval.get("result_count", 0) or 0))
    retrieval_cols[3].metric("Top K", int(last_retrieval.get("top_k", 0) or 0))
    retrieval_cols[4].metric("Fallback RAG", "Yes" if last_provider.get("provider") == "local_knowledge_fallback" else "No")
    if last_retrieval.get("error"):
        st.warning(f"Knowledge retrieval error: {last_retrieval.get('error')}")
    retrieval_sources = last_retrieval.get("sources") or []
    if retrieval_sources and demo_safe:
        st.caption(f"Retrieved local chunks hidden in Demo Safe Mode ({len(retrieval_sources)} item(s)).")
    elif retrieval_sources:
        with st.expander("Retrieved local chunks", expanded=False):
            st.dataframe(retrieval_sources, width="stretch", hide_index=True)

    st.markdown("### Image Providers And Artifacts")
    image_summary = get_cached_image_summary()
    image_providers = get_cached_image_providers()
    image_cols = st.columns(5)
    image_cols[0].metric(
        "Direct image provider",
        str(image_status.get("label") or "Offline") if image_status.get("available") else "Offline",
    )
    image_cols[1].metric("Saved PNGs", int(image_summary.get("image_files", 0) or 0))
    image_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    image_cols[3].metric("Missing records", int(image_summary.get("missing_image_records", 0) or 0))
    image_cols[4].metric("Storage", format_bytes(image_summary.get("total_bytes", 0)))

    last_image_generation = st.session_state.get("last_image_generation_result") or {}
    if last_image_generation:
        if last_image_generation.get("success"):
            st.success(
                f"Last image generation: {last_image_generation.get('provider', 'unknown')} "
                f"saved {last_image_generation.get('saved_count', 0)} artifact(s)."
            )
        else:
            st.warning(f"Last image generation failed: {last_image_generation.get('error') or 'unknown error'}")
    else:
        st.caption("Last image generation: none recorded this session.")

    with st.expander("Image provider detection", expanded=False):
        st.dataframe(image_provider_status_rows(image_providers), width="stretch", hide_index=True)
    recent_images = image_summary.get("recent_images") or []
    if recent_images:
        with st.expander("Recent image artifacts", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_images, enabled=demo_safe), width="stretch", hide_index=True)

    st.markdown("### Last Turn Trace")
    trace_cols = st.columns(4)
    trace_cols[0].metric("Route", str(last_route.get("label") or last_route.get("category") or "No turn yet"))
    trace_cols[1].metric("Mode", str(last_plan.get("mode", "No plan yet")))
    trace_cols[2].metric("Model", str(last_provider.get("model") or settings.get("selected_model") or "None"))
    trace_cols[3].metric("Elapsed", f"{float(last_provider.get('elapsed', 0) or 0):.2f}s")

    attempts = last_provider.get("attempts") or []
    if attempts:
        with st.expander("Provider attempts", expanded=False):
            st.dataframe(attempts, width="stretch")

    st.markdown("### Reality And Trust")
    reality_cols = st.columns(5)
    reality_cols[0].metric("Hallucination risk", hallucination.get("probability", "No audit"))
    reality_cols[1].metric("Speculation", str(speculation.get("category", "No audit")))
    reality_cols[2].metric("Source grounding", str(source_grounding.get("status", "No audit")))
    reality_cols[3].metric("Claims", len(last_audit.get("claims", []) or []) if isinstance(last_audit, dict) else 0)
    reality_cols[4].metric("Epistemic mode", str((last_epistemic.get("constraints") or {}).get("epistemic_mode", settings.get("epistemic_mode", "auto"))))

    if last_trust:
        user_audit = last_trust.get("user_request", {})
        trust_cols = st.columns(3)
        trust_cols[0].metric("Prompt trust", str(user_audit.get("trust_level", "unknown")))
        trust_cols[1].metric("Instruction risk", str(user_audit.get("instruction_risk", "unknown")))
        trust_cols[2].metric("Detected signals", len(user_audit.get("signals", []) or []))

    st.markdown("### Search And Reports")
    search_cols = st.columns(5)
    search_cols[0].metric("Reality agent", "On" if settings.get("enable_reality_research_agent") else "Off")
    search_cols[1].metric("Bloodhound", "On" if settings.get("enable_bloodhound_search") else "Off")
    search_cols[2].metric("Web sessions", int(inventory.get("web_research_sessions", 0) or 0))
    search_cols[3].metric("Search history", int(inventory.get("search_history_sessions", 0) or 0))
    search_cols[4].metric("Last sources", int(last_provider.get("sources", 0) or len((last_report or {}).get("sources", []) or [])))

    if last_report:
        saved_paths = last_report.get("saved_paths") or {}
        if saved_paths:
            st.success("Last report saved locally." if demo_safe else f"Last report saved: {saved_paths}")
    recent_reports = inventory.get("recent_research_reports") or []
    if recent_reports:
        with st.expander("Recent saved research reports", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_reports, enabled=demo_safe), width="stretch", hide_index=True)

    st.markdown("### Memory And Local Data")
    memory_paths = [PROJECT_ROOT / path for path in inventory.get("memory_files", [])]
    knowledge_summary = get_cached_knowledge_summary()
    embedding_status = knowledge_summary.get("embedding_status", {})
    profile_summary = load_user_profile_summary()
    memory_cols = st.columns(7)
    memory_cols[0].metric("Chat messages", len(get_messages()))
    memory_cols[1].metric("Memory files", sum(path.exists() for path in memory_paths))
    memory_cols[2].metric("Research sources", int(inventory.get("research_sources", 0) or 0))
    memory_cols[3].metric("Generated images", int(inventory.get("generated_images", 0) or 0))
    memory_cols[4].metric("Markdown notes", int(inventory.get("knowledge_notes", 0) or 0))
    memory_cols[5].metric("Local facts", int(profile_summary.get("fact_count", 0) or 0))
    memory_cols[6].metric("Embedding backend", str(embedding_status.get("runtime_backend", "unknown")))

    comfy = core_status.get("comfyui", {})
    if comfy:
        st.caption(
            f"Image provider: {'Available' if image_status.get('available') else 'Offline'} | "
            f"ComfyUI: {comfy.get('message', '')}"
        )
    if embedding_status:
        st.caption(str(embedding_status.get("message", "")))
    recent_notes = inventory.get("recent_knowledge_notes") or []
    if recent_notes:
        with st.expander("Recent Markdown knowledge notes", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_notes, enabled=demo_safe), width="stretch", hide_index=True)
    if last_memory and demo_safe:
        st.caption("Last local memory action hidden in Demo Safe Mode.")
    elif last_memory:
        with st.expander("Last local memory action", expanded=False):
            st.json(last_memory)
    if profile_summary.get("facts") and demo_safe:
        st.caption("Saved local profile facts hidden in Demo Safe Mode.")
    elif profile_summary.get("facts"):
        with st.expander("Saved local profile facts", expanded=False):
            st.dataframe(profile_summary["facts"], width="stretch", hide_index=True)

    if demo_safe:
        st.caption("Raw diagnostics and log files are hidden in Demo Safe Mode.")
    else:
        with st.expander("Raw diagnostics", expanded=False):
            st.json(
                {
                    "provider_result": last_provider,
                    "route": last_route,
                    "response_plan": last_plan,
                    "reality_audit": last_audit,
                    "trust_audit": last_trust,
                    "epistemic": last_epistemic,
                    "retrieval": last_retrieval,
                    "memory": last_memory,
                    "image_generation": last_image_generation,
                    "image_summary": image_summary,
                    "core_health": core_health,
                    "environment": get_environment_status(),
                }
            )
    log_files = [] if demo_safe else get_cached_log_files()
    if log_files:
        with st.expander("Log files", expanded=False):
            selected = st.selectbox("Log file", log_files, format_func=lambda path: path.name)
            st.text(tail_file(selected))
    if st.session_state.get("perf_timings") and not demo_safe:
        with st.expander("Performance timings", expanded=False):
            st.dataframe(st.session_state.perf_timings, width="stretch")


def render_settings_tab(settings: dict[str, Any]) -> None:
    st.subheader("Settings")
    profile = settings["chat_profile"]
    with st.form("chat_profile_form"):
        enabled = st.checkbox("Enable persona", value=profile.enabled)
        user_name = st.text_input("User name", value=profile.user_name)
        assistant_name = st.text_input("Assistant name", value=profile.assistant_name)
        persona_summary = st.text_area("Persona summary", value=profile.persona_summary, height=100)
        tone_notes = st.text_area("Tone notes", value=profile.tone_notes, height=80)
        style_notes = st.text_area("Style notes", value=profile.style_notes, height=120)
        creative_min_words = st.number_input("Creative writing minimum words", min_value=0, max_value=2000, value=profile.creative_min_words)
        additional_instructions = st.text_area("Additional instructions", value=profile.additional_instructions, height=100)

        # Added fields in form
        direct_language_for_adult_fiction = st.checkbox("Allow direct language for adult fiction", value=getattr(profile, 'direct_language_for_adult_fiction', True))
        show_capability_greeting = st.checkbox("Show greeting on fresh chat", value=getattr(profile, 'show_capability_greeting', True))

        saved = st.form_submit_button("Save Persona")
        if saved:
            updated = ChatProfile(
                enabled=enabled,
                user_name=user_name,
                assistant_name=assistant_name,
                persona_summary=persona_summary,
                tone_notes=tone_notes,
                style_notes=style_notes,
                creative_min_words=int(creative_min_words),
                direct_language_for_adult_fiction=direct_language_for_adult_fiction,
                show_capability_greeting=show_capability_greeting,
                additional_instructions=additional_instructions,
                allow_extreme_adult_content=getattr(profile, "allow_extreme_adult_content", True),
                allow_illegal_topics=getattr(profile, "allow_illegal_topics", True),
            )
            save_chat_profile(updated)
            st.success("Persona saved.")
            st.rerun()

    with st.expander("Developer diagnostics: router prompt templates", expanded=False):
        st.json(get_prompt_template_examples())


def load_demo_data():
    """Load sample data for demonstration purposes"""
    if "messages" not in st.session_state or not st.session_state.messages:
        st.session_state.messages = [
            {"role": "user", "content": "What are the benefits of renewable energy?"},
            {"role": "assistant", "content": "Renewable energy offers numerous benefits including reduced greenhouse gas emissions, energy independence, job creation in green industries, and long-term cost savings. Sources confirm that solar and wind power are now cost-competitive with fossil fuels in many regions."},
            {"role": "user", "content": "research the latest developments in quantum computing"},
            {"role": "assistant", "content": "I've initiated a Reality-First Research on quantum computing developments. The research shows promising advances in error correction and qubit stability, with companies like IBM and Google achieving significant milestones in the past year."}
        ]

    # Sample research report
    if "last_reality_research_report" not in st.session_state:
        from modules.reality_research_agent import ResearchReport
        sample_report = ResearchReport(
            query="quantum computing breakthroughs 2024",
            sources=[
                {"title": "IBM Quantum Road Map", "url": "https://ibm.com/quantum", "trust_score": 95, "category": "primary"},
                {"title": "Google Quantum AI Update", "url": "https://quantumai.google", "trust_score": 92, "category": "primary"},
                {"title": "MIT Technology Review", "url": "https://technologyreview.com", "trust_score": 88, "category": "secondary"}
            ],
            claims=[
                {"text": "IBM achieved 100+ qubit quantum computer", "confidence": 95, "sources": [0]},
                {"text": "Error correction breakthrough reduces noise by 90%", "confidence": 87, "sources": [1, 2]}
            ],
            contradictions=[],
            verdict="feasible",
            verdict_reason="Well-documented advances in quantum hardware and algorithms",
            summary="2024 saw major breakthroughs in quantum computing with improved qubit stability and error correction techniques.",
            memory_saved=True
        )
        st.session_state.last_reality_research_report = sample_report.to_dict()

    # Sample performance timings
    if "perf_timings" not in st.session_state:
        st.session_state.perf_timings = [
            {"operation": "memory_context", "duration_ms": 45.2},
            {"operation": "routing", "duration_ms": 23.1},
            {"operation": "model_generation", "duration_ms": 1250.8},
            {"operation": "reality_audit", "duration_ms": 89.3}
        ]


def render_app_header(settings: dict[str, Any]) -> None:
    st.title("Cognitive Nexus")
    st.caption(
        "Local-first AI research control center for chat, memory, web research, "
        "Reality-First reports, diagnostics, and local providers."
    )
    if is_demo_safe(settings):
        st.info("Demo Safe Mode is on. Local paths, raw private memory, and machine-specific diagnostics are hidden.")


def render_overview_tab(status, inventory: dict[str, Any], image_status: dict[str, Any], core_status: dict[str, Any], settings: dict[str, Any]) -> None:
    st.subheader("Home / Overview")
    st.caption("A compact control-room view of the working Cognitive Nexus engine.")

    demo_safe = is_demo_safe(settings)
    last_provider = st.session_state.get("last_provider_result") or {}
    active_provider = str(last_provider.get("provider") or ("ollama" if status.available else "fallback"))
    model_label = str(last_provider.get("model") or settings.get("selected_model") or "No model selected")
    if demo_safe and model_label:
        model_label = "Local model selected" if settings.get("provider_ready") else "Model details hidden"

    status_cols = st.columns(5)
    status_cols[0].metric("App", "Online")
    status_cols[1].metric("Ollama", "Connected" if status.available else "Offline")
    status_cols[2].metric("Active provider", active_provider.title())
    status_cols[3].metric("Model", model_label)
    status_cols[4].metric("Demo safety", "On" if demo_safe else "Off")

    st.markdown("### Control Center")
    capability_cols = st.columns(3)
    with capability_cols[0]:
        st.markdown("**Chat and routing**")
        st.caption("Ask questions, route tasks, use local providers, and keep fallback behavior visible.")
    with capability_cols[1]:
        st.markdown("**Reality-first research**")
        st.caption("Search sources, extract claims, score trust, flag contradictions, and save reports.")
    with capability_cols[2]:
        st.markdown("**Memory and knowledge**")
        st.caption("Use local facts, uploaded knowledge, Markdown notes, and retrieval summaries.")

    st.markdown("### System Snapshot")
    profile_summary = load_user_profile_summary()
    snapshot_cols = st.columns(6)
    snapshot_cols[0].metric("Chat messages", len(get_messages()))
    snapshot_cols[1].metric("Local facts", int(profile_summary.get("fact_count", 0) or 0))
    snapshot_cols[2].metric("Knowledge chunks", int(inventory.get("research_chunks", 0) or 0))
    snapshot_cols[3].metric("Reports", int(inventory.get("research_reports", 0) or 0))
    snapshot_cols[4].metric("Web sessions", int(inventory.get("web_research_sessions", 0) or 0))
    snapshot_cols[5].metric("Images", int(inventory.get("generated_images", 0) or 0))

    st.markdown("### Quick Actions")
    action_cols = st.columns(4)
    action_cols[0].info("Open Chat for normal work or code help.")
    action_cols[1].info("Use Reality-First Research for sourced answers.")
    action_cols[2].info("Use Files / Knowledge to ingest notes or URLs.")
    action_cols[3].info("Use Diagnostics to inspect provider and grounding status.")

    if demo_safe:
        st.success("Demo-safe presentation is active. Raw local paths, environment details, and private memory tables are withheld.")
    else:
        st.warning("Demo Safe Mode is off. Diagnostics and memory tabs may show local paths or private session details.")

    provider_rows = []
    for provider in core_status.get("providers", []):
        provider_rows.append(
            {
                "Provider": str(provider.get("name", "unknown")).title(),
                "Status": "Available" if provider.get("available") else "Offline",
                "Models": len(provider.get("models") or []),
                "Message": provider.get("message", ""),
            }
        )
    if provider_rows:
        with st.expander("Provider status", expanded=False):
            st.dataframe(sanitize_demo_rows(provider_rows, enabled=demo_safe), width="stretch", hide_index=True)


def main() -> None:
    restore_persisted_chat()
    core = get_nexus_core()
    status = get_cached_ollama_status()
    inventory = get_cached_project_inventory()
    image_status = get_cached_image_provider()
    chat_profile = load_chat_profile()
    default_order = tuple(core.config.get("provider_order", ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]))
    core_status = get_cached_core_status(default_order)
    settings = render_sidebar(status, inventory, image_status, chat_profile, core_status)

    # Auto-enable demo mode if environment variable set
    if os.getenv("COGNITIVE_NEXUS_DEMO") == "1":
        settings["demo_mode"] = True

    # Load demo data if enabled and not already loaded
    if settings.get("demo_mode") and not st.session_state.get("demo_loaded"):
        load_demo_data()
        st.session_state.demo_loaded = True
    elif not settings.get("demo_mode") and st.session_state.get("demo_loaded"):
        # Clear demo data when disabled
        if "messages" in st.session_state:
            st.session_state.messages = []
        st.session_state.demo_loaded = False

    render_app_header(settings)

    tabs = st.tabs(TAB_LABELS)
    with tabs[0]:
        render_overview_tab(status, inventory, image_status, core_status, settings)
    with tabs[1]:
        render_chat_tab(settings)
    with tabs[2]:
        render_reality_research_tab(settings)
    with tabs[3]:
        render_web_research_tab(settings)
    with tabs[4]:
        render_files_knowledge_tab(settings)
    with tabs[5]:
        render_memory_tab(settings)
    with tabs[6]:
        render_image_tab(settings)
    with tabs[7]:
        render_gallery(settings)
    with tabs[8]:
        render_diagnostics_tab(status, inventory, image_status, core_status, settings)
    with tabs[9]:
        render_settings_tab(settings)
    with tabs[10]:
        render_tools_tab(settings)


if __name__ == "__main__":
    main()
