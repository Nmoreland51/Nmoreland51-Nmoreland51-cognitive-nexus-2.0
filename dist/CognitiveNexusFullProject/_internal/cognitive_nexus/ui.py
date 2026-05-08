"""Shared UI helpers used by the main Streamlit app."""

from __future__ import annotations

from typing import Callable, List, Optional

import streamlit as st

from cognitive_nexus.runtime import provider_display_name


def render_sidebar(
    *,
    provider: str,
    dependency_checker: Callable[[str], bool],
    feature_status_items: Optional[List[str]] = None,
    web_search_available: bool,
    health_report: dict,
) -> dict:
    with st.sidebar:
        enable_image_generation = bool(st.session_state.get("enable_image_generation", False))
        show_reasoning = bool(st.session_state.get("show_reasoning", False))

        st.markdown("## Cognitive Nexus AI")
        st.markdown("### AI Provider")
        st.info(f"Active: {provider_display_name(provider)}")

        st.markdown("### Settings")
        show_sources = st.checkbox("Show Sources", value=True)
        enable_learning = st.checkbox("Learning Mode", value=True)
        enable_search = st.checkbox("Web Search", value=True)
        st.session_state.enable_image_generation = st.checkbox(
            "Image Generation",
            value=enable_image_generation,
        )
        st.session_state.show_reasoning = st.checkbox(
            "Show Reasoning",
            value=show_reasoning,
            help="Display the internal reasoning expander for chat responses.",
        )

        st.markdown("### System Status")
        status_items: List[str] = list(feature_status_items or [])
        if not status_items:
            if dependency_checker("openchat"):
                status_items.append("OpenChat")
            if dependency_checker("ollama"):
                status_items.append("Ollama")
            if web_search_available:
                status_items.append("Web Search")
            if dependency_checker("content_extraction"):
                status_items.append("Content Extraction")
            if dependency_checker("image_generation"):
                status_items.append("Image Generation")

        if status_items:
            st.success("Available: " + " | ".join(status_items))
        else:
            st.warning("No optional features detected yet.")

        st.markdown("### Self-Healing")
        error_counts = health_report.get("error_counts", {})
        if error_counts:
            st.warning(f"Errors handled: {sum(error_counts.values())}")
        else:
            st.success("Status: healthy")

    return {
        "show_sources": show_sources,
        "enable_learning": enable_learning,
        "enable_search": enable_search,
        "enable_image_generation": bool(st.session_state.enable_image_generation),
        "show_reasoning": bool(st.session_state.show_reasoning),
    }
