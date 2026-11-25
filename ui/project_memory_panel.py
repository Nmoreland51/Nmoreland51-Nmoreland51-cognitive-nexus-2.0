"""The Agent tab's project memory: what is known about each project, and a way to write it down (item 048)."""

from __future__ import annotations

import streamlit as st

from agent.project_memory import KINDS, OWNER_KINDS, TITLES, ProjectMemory, project_key
from agent.store import AgentStore, StoreError

KIND_NAMES = {"objective": "Objective", "decision": "Decision", "bug": "Known bug"}
NOTICE_KEY = "project_memory_notice"


def render_project_memory(store: AgentStore, *, read_only: bool = False, repos: list[str] | None = None) -> None:
    memory = ProjectMemory(store)
    known = sorted(set(memory.projects()) | {project_key(repo) for repo in repos or [] if repo})
    with st.expander("What is known about each project", expanded=False):
        st.caption(
            "Objectives, decisions and known bugs you write down, and the last test results and repository state the agent records "
            "as it works. The agent is shown them before every attempt, your notes marked as yours. Closing a note keeps it in the history."
        )
        notice = st.session_state.pop(NOTICE_KEY, "")
        if notice:
            st.success(notice)
        chosen = st.selectbox("Project", known, key="project_memory_project") if known else ""
        typed = st.text_input("Or another repository (a folder)", key="project_memory_other", disabled=read_only)
        project = typed.strip() or chosen
        if not project:
            st.caption("No project yet: give the agent a task, or name a repository above.")
            return
        notes = memory.notes(project)
        if not notes:
            st.caption("Nothing is written down about this project yet.")
        for kind in KINDS:
            found = [row for row in notes if row["kind"] == kind]
            if not found:
                continue
            st.markdown(f"**{TITLES[kind]}**")
            for row in found:
                text_col, close_col = st.columns([6, 1])
                text_col.write(f"{row['text']}  \n_{row['source']}, {row['updated_at'][:16].replace('T', ' ')} UTC_")
                if kind in OWNER_KINDS and not read_only and close_col.button("Close", key=f"project_note_close_{row['id']}"):
                    memory.close(row["id"], by="owner")
                    st.session_state[NOTICE_KEY] = "Closed. It stays in the history."
                    st.rerun()
        if read_only:
            return
        with st.form("project_memory_add", clear_on_submit=True):
            kind = st.selectbox("Kind", OWNER_KINDS, format_func=lambda item: KIND_NAMES[item])
            text = st.text_area("Note", height=80)
            if st.form_submit_button("Write it down"):
                try:
                    memory.add(project, kind, text, source="owner")
                except StoreError as exc:
                    st.warning(str(exc))
                else:
                    st.session_state[NOTICE_KEY] = f"Written down for {project_key(project)}."
                    st.rerun()
