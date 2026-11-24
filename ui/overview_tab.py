"""The Home / Overview tab, the page header and the demo data it shows.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from modules.context_manager import load_user_profile_summary
from modules.memory import (
    get_messages,
)
from ui.shared import is_demo_safe, sanitize_demo_rows


def load_demo_data():
    if "messages" not in st.session_state or not st.session_state.messages:
        st.session_state.messages = [
            {"role": "user", "content": "What are the benefits of renewable energy?"},
            {"role": "assistant", "content": "Renewable energy offers numerous benefits including reduced greenhouse gas emissions, energy independence, job creation in green industries, and long-term cost savings. Sources confirm that solar and wind power are now cost-competitive with fossil fuels in many regions."},
            {"role": "user", "content": "research the latest developments in quantum computing"},
            {"role": "assistant", "content": "I've initiated a Reality-First Research on quantum computing developments. The research shows promising advances in error correction and qubit stability, with companies like IBM and Google achieving significant milestones in the past year."}
        ]

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
