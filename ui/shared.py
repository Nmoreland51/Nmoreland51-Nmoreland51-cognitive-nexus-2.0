"""State the app's tabs share: the one NexusCore, cached look-ups, demo-safe display, timings and session resets.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Optional
import streamlit as st

from modules.core_health import run_core_health_check
from modules.data_stores import DATA_ROOT, SEED_KNOWLEDGE_DIR
from modules.image_gen import (
    detect_image_provider,
    detect_image_providers,
    list_generated_images,
    summarize_image_gallery,
)
from modules.memory import (
    clear_messages,
    clear_session_history_file,
)
from modules.project_status import (
    PROJECT_ROOT,
    get_project_inventory,
    list_project_tools,
)
from modules.providers import (
    check_ollama_status,
    forget_ollama_tags,
    get_provider_inventory,
)
from modules.research import (
    get_research_module,
)
from modules.nexus_core import NexusCore


try:
    from cognitive_nexus.adaptation import AdaptiveMemoryManager
except Exception:  # pragma: no cover - optional legacy module
    AdaptiveMemoryManager = None  # type: ignore


SESSION_DIAGNOSTIC_KEYS = (
    "last_route_decision",
    "last_provider_result",
    "last_verification",
    "last_response_plan",
    "last_response_critic",
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


_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s`'\"<>|]+")


_LOCAL_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?[^\s`'\"<>)]*")


_ENV_DETAIL_RE = re.compile(r"\b(?:OPENAI|ANTHROPIC|HF|HUGGINGFACE|API|TOKEN|SECRET|KEY)[A-Z0-9_]*\b", re.IGNORECASE)


def is_demo_safe(settings: dict[str, Any] | None) -> bool:
    return bool((settings or {}).get("demo_safe_mode"))


def demo_safe_status(enabled: bool) -> str:
    return "Demo Safe Mode: On" if enabled else "Demo Safe Mode: Off"


def sanitize_demo_text(value: Any) -> str:
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


def sync_core_diagnostics(core: NexusCore | None = None) -> None:
    """Copy core diagnostics into session state, tolerating cached older core objects."""

    core = core or get_nexus_core()
    st.session_state.last_route_decision = getattr(core, "last_route_decision", {})
    st.session_state.last_provider_result = getattr(core, "last_provider_result", {})
    st.session_state.last_verification = getattr(core, "last_verification", {})
    st.session_state.last_response_plan = getattr(core, "last_response_plan", {})
    st.session_state.last_response_critic = getattr(core, "last_response_critic", {})
    st.session_state.last_reality_audit = getattr(core, "last_reality_audit", {})
    st.session_state.last_trust_audit = getattr(core, "last_trust_audit", {})
    st.session_state.last_epistemic_assessment = getattr(core, "last_epistemic_assessment", {})
    st.session_state.last_reality_research_report = getattr(core, "last_reality_research_report", {})
    st.session_state.last_retrieval = getattr(core, "last_retrieval", {})
    st.session_state.last_memory = getattr(core, "last_memory", {})


@st.cache_resource(show_spinner=False)
def warm_chat_model(model: str) -> bool:
    """Once per model, in the background: load the chat model in Ollama and ask it for a few
    words. That saves the first message ~7s of loading and proves the model really answers,
    which being listed by Ollama does not."""

    threading.Thread(target=get_nexus_core().provider_router.verify_ollama, args=(model,), daemon=True).start()
    return True


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_core_status(provider_order: tuple[str, ...]) -> dict[str, Any]:
    return get_nexus_core().status_snapshot(list(provider_order))


@st.cache_resource
def get_adaptive_memory():
    if AdaptiveMemoryManager is None:
        return None
    return AdaptiveMemoryManager(DATA_ROOT, seed_knowledge_dir=SEED_KNOWLEDGE_DIR)


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
    # From the same detection as the list, instead of asking every server a second time.
    return detect_image_provider(get_cached_image_providers())


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
    forget_ollama_tags()
    get_nexus_core().comfyui.forget_status()
    get_nexus_core().refresh_config()


def record_perf(label: str, elapsed: float, settings: Optional[dict[str, Any]] = None) -> None:
    if settings is not None and not settings.get("show_perf_timings"):
        return
    timings = st.session_state.setdefault("perf_timings", [])
    timings.append({"label": label, "seconds": round(elapsed, 3)})
    del timings[:-30]


def clear_chat_state() -> None:
    clear_messages()
    clear_session_history_file()


def reset_session_state() -> None:
    clear_chat_state()
    for key in SESSION_DIAGNOSTIC_KEYS:
        st.session_state.pop(key, None)


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
