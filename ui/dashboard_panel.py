"""The project dashboard at the top of the Agent tab (item 140): milestones, build, bugs, progress, time and recent changes."""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from agent.store import AgentStore
from modules import project_dashboard as dashboard

BUILD_KEY = "project_dashboard_build"
BUILD_SECONDS = 120.0


def _github_token() -> str:
    """The linked GitHub account's token, if one is linked with permission to read; GitHub answers without one for public repositories."""

    try:
        from modules import accounts

        return accounts.credential("github", "read")
    except Exception:
        return ""


def render_project_dashboard(store: AgentStore, project_root: str | Path, *, read_only: bool = False) -> None:
    with st.expander("Project dashboard: milestones, build, bugs, progress, recent changes", expanded=True):
        if read_only:  # demo-safe mode: no local path on screen
            root = Path(project_root)
        else:
            project = st.text_input("Project (a repository folder)", value=str(project_root), key="dashboard_project").strip()
            root = Path(project or project_root)
        progress = dashboard.agent_progress(store, str(root))
        counts = progress["by_status"]
        first, second, third, fourth = st.columns(4)
        first.metric("Agent tasks open", len(progress["open"]))
        second.metric("Waiting for your review", counts.get("review", 0))
        third.metric("Waiting for approval", counts.get("waiting_approval", 0))
        fourth.metric("Failed or handed back", counts.get("failed", 0) + counts.get("escalated", 0))

        st.markdown("**Milestones**")
        found = dashboard.milestones(root)
        if found is None:
            st.caption("This project has no milestone list (docs/backlog/items.json and status.json).")
        else:
            totals = found["totals"]
            st.caption(
                f"The {totals['items']}-item audit, one milestone per section: {totals['complete']} complete, {totals['partial']} partial, "
                f"{totals['missing']} missing, {totals['not_applicable']} not applicable. From docs/backlog, item by item in docs/AUDIT_146_PROGRESS.md."
            )
            st.dataframe(
                [
                    {
                        "Milestone": f"{row['number']}. {row['title']}",
                        "Priority": row["priority"],
                        "Done": round(row["done"] * 100),
                        "Complete": row["complete"],
                        "Partial": row["partial"],
                        "Missing": row["missing"],
                    }
                    for row in found["sections"]
                ],
                hide_index=True,
                width="stretch",
                column_config={"Done": st.column_config.ProgressColumn("Done", min_value=0, max_value=100, format="%d%%")},
            )

        st.markdown("**Build**")
        slug, branch = dashboard.github_slug(root), dashboard.current_branch(root)
        tests = dashboard.last_test_results(store, str(root))
        if tests:
            st.caption("The last test runs the agent recorded:")
            st.dataframe(tests, hide_index=True, width="stretch")
        if read_only:
            st.caption("The build on GitHub is not looked up in demo-safe mode.")
        elif not slug:
            st.caption("No GitHub remote, so the build is only what the agent's test runs show.")
        elif st.toggle(f"Show the build on GitHub ({slug}, branch {branch})", key="dashboard_show_build"):
            # Asked for only while the switch is on, and at most every two minutes.
            build = st.session_state.get(BUILD_KEY) or {}
            if build.get("for") != f"{slug}@{branch}" or time.time() - float(build.get("at", 0)) > BUILD_SECONDS:
                token = _github_token()
                build = {
                    "for": f"{slug}@{branch}",
                    "at": time.time(),
                    **dashboard.ci_runs(slug, branch, token=token),
                    "pushed": dashboard.github_commits(slug, branch, token=token),
                }
                st.session_state[BUILD_KEY] = build
            if build["runs"]:
                st.dataframe(build["runs"], hide_index=True, width="stretch", column_config={"url": st.column_config.LinkColumn("On GitHub")})
            if build["error"]:
                st.caption(build["error"])
            pushed = build.get("pushed") or {}
            if pushed.get("commits"):
                st.caption(f"Newest commits on GitHub for {branch} (what was pushed, by anyone):")
                st.dataframe(pushed["commits"], hide_index=True, width="stretch")
            elif pushed.get("error"):
                st.caption(pushed["error"])

        st.markdown("**Active bugs**")
        bugs = dashboard.active_bugs(store, str(root))
        if bugs:
            st.dataframe(bugs, hide_index=True, width="stretch")
        else:
            st.caption("None written down, and no task of the agent's on this project has failed. Add a known bug under 'What is known about each project'.")

        st.markdown("**Agent progress and time**")
        estimate = progress["estimate"]
        if progress["open"]:
            st.dataframe(progress["open"], hide_index=True, width="stretch")
        else:
            st.caption("No open task on this project.")
        st.caption(
            f"A task has taken {estimate['minutes_per_task']} minutes here (the middle of {estimate['from_tasks']} finished task(s)); a new one may differ."
            if estimate["from_tasks"]
            else "No time estimate yet: no task on this project has finished."
        )

        st.markdown("**Recent changes**")
        commits = dashboard.recent_commits(root)
        if commits:
            st.caption(f"Branch {branch}, newest first.")
            st.dataframe(commits, hide_index=True, width="stretch")
        else:
            st.caption("Not a Git repository, or no commits yet.")
