"""The Files / Knowledge, Memory and Tools tabs.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from modules.context_manager import load_user_profile_summary
from modules.answer_meta import describe_answer
from modules.memory import (
    get_messages,
)
from modules.project_status import (
    PROJECT_ROOT,
    tail_file,
)
from modules.ingest import UPLOAD_TYPES
from modules.research import (
    ingest_file,
    list_knowledge_notes,
    process_url,
    save_knowledge_note,
)
from modules.behavior_policy import ContentRuleBlocked
from ui.data_panel import render_data_panel
from ui.shared import get_adaptive_memory, get_cached_project_inventory, get_cached_project_tools, get_cached_research_module, get_nexus_core, is_demo_safe


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

    uploaded = st.file_uploader(
        "Upload a document: text, Markdown, PDF, Word (.docx), HTML, CSV, JSON, a notebook or source code",
        type=UPLOAD_TYPES,
    )
    if uploaded and st.button("Ingest uploaded file"):
        with st.spinner(f"Reading {uploaded.name}..."):
            result = ingest_file(module, name=uploaded.name, data=uploaded.getvalue())
        if result.get("status") == "success":
            what = f"{result.get('language')} source file" if result.get("kind") == "code" else "document"
            if result.get("unchanged"):
                st.info(f"{uploaded.name} is already stored and has not changed.")
            else:
                st.success(f"Stored {result.get('chunks_count', 0)} passage(s) from the {what} {uploaded.name}.")
            for warning in result.get("warnings") or []:
                st.warning(warning)
            get_cached_project_inventory.clear()
        else:
            st.error(result.get("error", "The file could not be read."))

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
        f"{summary.get('total_urls', 0)} document(s), {summary.get('total_chunks', 0)} passage(s). "
        f"{embedding_status.get('message', '')}"
    )
    if embedding_status.get("degraded"):
        st.warning(
            "Search is matching words only. For search by meaning, install a small embedding model "
            "(45 MB): run `ollama pull all-minilm`, then restart the app."
        )
    if summary.get("waiting_for_vectors") and not embedding_status.get("degraded"):
        if st.button(f"Prepare {summary['waiting_for_vectors']} passage(s) for search by meaning", key="knowledge_reembed"):
            with st.spinner("Embedding passages..."):
                outcome = module.reembed()
            if outcome.get("error"):
                st.error(outcome["error"])
            else:
                st.success(f"Prepared {outcome.get('embedded', 0)} passage(s).")

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
        try:
            result = get_nexus_core().answer_knowledge(query, settings, top_k=top_k)
        except ContentRuleBlocked as stopped:
            st.warning(stopped.reply)
            return
        st.markdown(result["answer"])
        knowledge_label = "" if demo_safe else describe_answer(result.get("produced_by"))
        if knowledge_label:
            st.caption(knowledge_label)
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
    render_data_panel(demo_safe)
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
