"""Cognitive Nexus Streamlit dashboard."""
from __future__ import annotations
import os
import threading
import streamlit as st

from modules.chat_profile import (
    load_chat_profile,
)
from modules.memory import (
    add_message,
    get_messages,
    initialize_chat_state,
    load_session_history_file,
)
from modules.research import (
    get_research_module,
)
from ui.data_panel import start_daily_snapshot

# Each tab is drawn by its own module under ui/ (audit item 120). The helpers marked "kept here"
# are imported back so that `app.<name>` keeps working for code that used it before the move.
from ui.chat_tab import render_chat_tab
from ui.chat_tab import empty_assistant_response_message, merge_chat_timing_trace, normalize_assistant_response, persist_assistant_response, should_show_plan_caption  # noqa: F401  kept here
from ui.diagnostics_tab import render_diagnostics_tab
from ui.diagnostics_tab import context_window_caption  # noqa: F401  kept here
from ui.images_tab import render_gallery, render_image_tab
from ui.images_tab import image_generation_notes  # noqa: F401  kept here
from ui.knowledge_tabs import render_files_knowledge_tab, render_memory_tab, render_tools_tab
from ui.overview_tab import load_demo_data, render_app_header, render_overview_tab
from ui.research_tabs import render_reality_research_tab, render_web_research_tab
from ui.settings_tab import render_agent_tab, render_settings_tab
from ui.shared import get_cached_core_status, get_cached_image_provider, get_cached_ollama_status, get_cached_project_inventory, get_nexus_core
from ui.shared import is_demo_safe, sanitize_demo_text  # noqa: F401  kept here
from ui.sidebar import render_sidebar
from ui.sidebar import data_locality_caption, get_chat_model, model_check_caption, normalize_provider_order  # noqa: F401  kept here


st.set_page_config(
    page_title="Cognitive Nexus",
    page_icon="CN",
    layout="wide",
    initial_sidebar_state="expanded",
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
    "Agent",
]


def restore_persisted_chat() -> None:
    initialize_chat_state()
    if get_messages():
        return
    for message in load_session_history_file():
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
            saved_meta = message.get("meta")
            add_message(
                str(message["role"]),
                str(message.get("content", "")),
                meta=saved_meta if isinstance(saved_meta, dict) else None,
            )


@st.cache_resource(show_spinner=False)
def run_startup_tasks() -> bool:
    """Housekeeping done once per app start, in the background."""

    start_daily_snapshot()

    def prepare_knowledge() -> None:
        # After the embedding model changed, or documents were saved while it was not running,
        # some passages have no vector yet. They are found by keyword until this finishes.
        try:
            module = get_research_module()
            if module.store.embedder.semantic and module.store.waiting_for_vectors():
                module.reembed()
        except Exception as exc:
            from modules.event_log import record_event

            record_event("error", "Preparing knowledge passages for search by meaning failed", error=str(exc))

    threading.Thread(target=prepare_knowledge, daemon=True).start()
    return True


def main() -> None:
    run_startup_tasks()
    restore_persisted_chat()
    core = get_nexus_core()
    status = get_cached_ollama_status()
    inventory = get_cached_project_inventory()
    image_status = get_cached_image_provider()
    chat_profile = load_chat_profile()
    default_order = tuple(core.config.get("provider_order", ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]))
    core_status = get_cached_core_status(default_order)
    settings = render_sidebar(status, inventory, image_status, chat_profile, core_status)

    if os.getenv("COGNITIVE_NEXUS_DEMO") == "1":
        settings["demo_mode"] = True

    if settings.get("demo_mode") and not st.session_state.get("demo_loaded"):
        load_demo_data()
        st.session_state.demo_loaded = True
    elif not settings.get("demo_mode") and st.session_state.get("demo_loaded"):
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
    with tabs[11]:
        render_agent_tab(settings)


if __name__ == "__main__":
    main()
