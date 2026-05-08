"""Shared runtime helpers for Streamlit and app state."""

from __future__ import annotations

import time
from typing import Dict

import streamlit as st

from cognitive_nexus.config import get_settings


PROVIDER_NAMES: Dict[str, str] = {
    "openchat": "OpenChat-v3.5 (Local)",
    "ollama": "Ollama (Local)",
    "anthropic": "Anthropic (Cloud)",
    "fallback": "Pattern-based",
}


def configure_page() -> None:
    settings = get_settings()
    st.set_page_config(
        page_title=settings.app_title,
        page_icon=settings.page_icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )


def initialize_session_state(enable_image_generation_default: bool) -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"session_{int(time.time())}"
    if "detected_provider" not in st.session_state:
        st.session_state.detected_provider = "fallback"
    if "enable_image_generation" not in st.session_state:
        st.session_state.enable_image_generation = bool(enable_image_generation_default)
    if "image_generation_history" not in st.session_state:
        st.session_state.image_generation_history = []
    if "show_reasoning" not in st.session_state:
        st.session_state.show_reasoning = False
    if "web_research_history" not in st.session_state:
        st.session_state.web_research_history = []


def provider_display_name(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider)
