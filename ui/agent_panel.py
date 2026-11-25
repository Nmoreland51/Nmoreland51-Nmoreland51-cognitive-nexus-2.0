"""The Agent tab: give the coding agent a task, see what it did, decide what waits for you.

Everything shown here comes from the agent's own records (agent/store.py): tasks, every action
with its inputs, approval and result, and background jobs. Nothing is summarised by a model.
The same things can be done from a terminal with `python -m agent`.
"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from agent import sandbox
from agent.capabilities import catalogue
from agent.coder import CodingAgent, changes_this_app, describe
from agent.jobs import JobQueue, Worker
from agent.store import AgentStore, StoreError, Task
from modules.project_status import PROJECT_ROOT
from ui.dashboard_panel import render_project_dashboard
from ui.project_memory_panel import render_project_memory
from agent.workspace import WorkspaceError

NOTICE_KEY = "agent_notice"
CATALOGUE_KEY = "agent_catalogue"
CATALOGUE_SECONDS = 60.0  # looking for apps contacts the model server; not on every redraw
OWNER = "owner"
WAITING_STATES = ("review", "escalated", "waiting_approval", "failed")
MEASUREMENT_PARTS = (
    ("Worse", "worse"),
    ("Better", "better"),
    ("The evaluations themselves were changed", "evaluations_changed"),
    ("Saved measurements to run again", "saved_measurements_out_of_date"),
    ("Could not be measured", "could_not_be_measured"),
)


def _notice(text: str) -> None:
    st.session_state[NOTICE_KEY] = text


def new_task(store: AgentStore, repo: str, title: str, description: str, tests: str, attempts: int, minutes: int) -> tuple[Task | None, str]:
    """Create a task from the form. Returns (task, problem)."""

    folder = Path(repo.strip()).expanduser()
    if not title.strip():
        return None, "Give the task a title."
    if not folder.is_dir() or not (folder / ".git").exists():
        return None, f"{folder} is not a Git repository on this machine."
    try:
        commands = [shlex.split(line) for line in tests.splitlines() if line.strip()]
    except ValueError as exc:
        return None, f"A test command could not be read: {exc}"
    task = store.create_task(
        title.strip(),
        description.strip(),
        repo=str(folder.resolve()),
        acceptance=commands,
        budget={"attempts": int(attempts), "seconds": float(minutes) * 60},
    )
    return task, ""


def task_rows(tasks: list[Task]) -> list[dict[str, Any]]:
    return [
        {
            "Task": task.id,
            "Status": task.status,
            "Title": task.title,
            "Where it stands": describe(task),
            "Used": f"{int((task.spent or {}).get('attempts', 0))} attempt(s), {float((task.spent or {}).get('seconds', 0)):.0f} s",
        }
        for task in tasks
    ]


def action_rows(actions: list[dict[str, Any]], store: AgentStore | None = None) -> list[dict[str, Any]]:
    """The action history as a table: what was done, with what input, who allowed it, how it ended, what it made."""

    rows = []
    for action in actions:
        checked = "" if action["verified"] is None else ("checked" if action["verified"] else "CHECK FAILED")
        approval = "not needed"
        if action.get("approval_id"):
            approval = f"request {action['approval_id']}"
            if store is not None:
                try:
                    decided = store.approval(action["approval_id"])
                    approval = f"{'allowed' if decided['status'] in {'approved', 'used'} else decided['status']} by {decided.get('decided_by') or 'nobody yet'}"
                except StoreError:
                    pass
        elif action["status"] == "denied":
            approval = "refused"
        rows.append(
            {
                "When": str(action["started_at"])[:19].replace("T", " "),
                "Task": action.get("task_id") or "",
                "Tool": action["tool"],
                "Can affect": action["effect"],
                "Approval": approval,
                "Result": action["status"],
                "Outcome": checked,
                "Input": str(action["arguments"])[:120],
                "Produced": ", ".join(str(item) for item in (action.get("artifacts") or []))[:160],
            }
        )
    return rows


def capability_tables(listing: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """The capability list as three tables for a person: tools, apps, accounts."""

    return {
        "tools": [
            {
                "Tool": tool["name"],
                "Group": tool["adapter"],
                "Can affect": tool["effect"],
                "Usable now": "yes" if tool["usable"] else "no: " + "; ".join(tool["missing"]),
                "Checks its outcome": "yes" if tool["checks_its_outcome"] else "",
                "What it does": tool["description"],
            }
            for tool in listing["tools"]
        ],
        "apps": [{"App": app["name"], "Found": "yes" if app["found"] else "no", "Detail": app["detail"], "Used for": app["used_for"]} for app in listing["apps"]],
        "accounts": [
            {
                "Service": entry["name"],
                "Linked": f"yes ({entry['how']})" if entry["linked"] else "no",
                "May be used for": ", ".join(entry["permissions"]) or ("nothing" if entry["linked"] else ""),
                "Used by": ", ".join(entry["used_by_tools"]) or entry["used_for"],
            }
            for entry in listing["accounts"]
        ],
    }


def _catalogue(agent: CodingAgent) -> dict[str, list[dict[str, Any]]]:
    kept = st.session_state.get(CATALOGUE_KEY)
    if kept and time.monotonic() - kept[0] < CATALOGUE_SECONDS:
        return kept[1]
    listing = catalogue(agent.registry, dict(agent.settings), look_for_image_backends=False)
    st.session_state[CATALOGUE_KEY] = (time.monotonic(), listing)
    return listing


def _diff_of(agent: CodingAgent, task: Task) -> str:
    try:
        return agent.workspaces.diff(agent.workspaces.open(task.id, task.repo, task.workspace, task.branch, task.base_ref))
    except (WorkspaceError, StoreError, OSError) as exc:
        return f"The diff cannot be shown: {exc}"


def render_agent_panel(
    store: AgentStore | None = None,
    build: Callable[[], CodingAgent] | None = None,
    *,
    read_only: bool = False,
    make_worker: Callable[[JobQueue], Worker] | None = None,
) -> None:
    """Draw the tab. `build` makes the coding agent (it loads the model settings, so it is only called when needed)."""

    store = store or AgentStore()
    queue = JobQueue(store)
    if build is None:
        from agent.cli import build_agent

        def build() -> CodingAgent:
            return build_agent(store)

    st.subheader("Coding agent")
    st.caption(
        "Give it a repository and a test that fails. It works in a checkout of its own: reproduces the failure, edits, runs the tests "
        "in a sandbox, has the change reviewed and commits to a branch of its own. A task is done only when you accept it. "
        "It is the selected model working in a loop, no cleverer than that model: of nine small seeded bugs it had never been tried on, "
        "the local 8B model fixed 4."
    )
    notice = st.session_state.pop(NOTICE_KEY, "")
    if notice:
        st.success(notice)
    render_project_dashboard(store, PROJECT_ROOT, read_only=read_only)

    tasks = store.list_tasks()
    approvals = store.approvals()

    # ---- what waits for the owner ----------------------------------------------------------------
    waiting = [task for task in tasks if task.status in WAITING_STATES]
    st.markdown(f"**Waiting for you: {len(approvals) + len(waiting)}**")
    tasks_by_id = {task.id: task for task in tasks}
    for request in approvals:
        st.write(f"The agent asks to **{request['summary']}** (can affect: {request['effect']}; task {request['task_id'] or 'none'}).")
        with st.expander("Exactly what it would do", expanded=False):
            st.caption(f"Tool {request['tool']}, with these arguments:")
            st.json(request.get("arguments") or {})
            asking_task = tasks_by_id.get(request.get("task_id") or "")
            if asking_task is not None:
                st.caption(f"The changes on its branch ({asking_task.branch or 'none yet'}), which this would act on:")
                st.code(_diff_of(build(), asking_task) or "(no changes)", language="diff")
        if not read_only:
            allow, refuse = st.columns(2)
            if allow.button("Allow this once", key=f"agent_allow_{request['id']}"):
                store.decide_approval(request["id"], approved=True, by=OWNER, note="allowed in the app")
                _notice("Allowed. Start the task again and it continues from where it stopped.")
                st.rerun()
            if refuse.button("Refuse", key=f"agent_refuse_{request['id']}"):
                store.decide_approval(request["id"], approved=False, by=OWNER, note="refused in the app")
                _notice("Refused. The task will be handed back to you when it next runs.")
                st.rerun()
    for task in waiting:
        with st.expander(f"{task.title}: {describe(task)}", expanded=task.status == "review"):
            st.caption(f"Task {task.id} · branch {task.branch or '(none yet)'} · {task.repo}")
            if task.result.get("what_a_person_can_do"):
                st.info(str(task.result["what_a_person_can_do"]))
            if task.status == "review":
                st.code(_diff_of(build(), task) or "(no changes)", language="diff")
                own_code = changes_this_app(task.repo)
                why = ""
                if own_code:
                    measured = task.result.get("evaluation") or {}
                    state = f"The last measurement said: {measured['verdict']}{' (quick comparison only)' if measured.get('quick') else ''}." if measured.get("verdict") else "It has not been measured yet."
                    st.info(f"This change is to the assistant's own code. It is accepted only after it was measured against what it replaces and found not worse. {state}")
                    for title, key in MEASUREMENT_PARTS:
                        for line in measured.get(key, []):
                            st.write(f"{title}: {line}")
                    if not read_only:
                        if st.button("Measure this change against what it replaces (minutes)", key=f"agent_measure_{task.id}"):
                            with st.spinner("Measuring both versions. This page waits until it is done."):
                                found = build().evaluate(task.id)
                            _notice(f"Measured: {found['verdict']}.")
                            st.rerun()
                        why = st.text_input("To accept without a passing measurement, say why", key=f"agent_despite_{task.id}")
                if not read_only:
                    if st.button("Accept this change", type="primary", key=f"agent_accept_{task.id}"):
                        try:
                            build().accept(task.id, OWNER, despite_evaluation=why)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            _notice(f"Accepted. The commit is on branch {task.branch} in your repository; nothing was merged or pushed.")
                            st.rerun()
                    feedback = st.text_input("Or say what should be different", key=f"agent_feedback_{task.id}")
                    if st.button("Send it back", key=f"agent_back_{task.id}") and feedback.strip():
                        build().request_changes(task.id, OWNER, feedback.strip())
                        _notice("Sent back. Start the task again to have it try with your note.")
                        st.rerun()
    if not approvals and not waiting:
        st.caption("Nothing is waiting.")

    # ---- a new task ------------------------------------------------------------------------------
    if not read_only:
        with st.expander("Give it a task", expanded=not tasks):
            with st.form("agent_new_task"):
                repo = st.text_input("Repository folder", key="agent_new_repo", help="A Git repository on this machine. The agent works in a separate checkout; your files are not touched.")
                title = st.text_input("What is wrong, in a line", key="agent_new_title")
                description = st.text_area("Details (optional)", key="agent_new_description", height=80)
                tests = st.text_area(
                    "A command that fails now and must pass when it is done (one per line)",
                    key="agent_new_tests",
                    height=70,
                    placeholder="python -m pytest tests/test_dates.py",
                    help="Without one the agent cannot tell when it is done and hands the task straight back.",
                )
                columns = st.columns(2)
                attempts = columns[0].number_input("Attempts", min_value=1, max_value=10, value=3, key="agent_new_attempts")
                minutes = columns[1].number_input("Minutes", min_value=1, max_value=240, value=30, key="agent_new_minutes")
                if st.form_submit_button("Add the task"):
                    made, problem = new_task(store, repo, title, description, tests, int(attempts), int(minutes))
                    if made is None:
                        st.error(problem)
                    else:
                        _notice(f"Added task {made.id}. Choose it below and start it." + ("" if made.acceptance else " It has no test, so the agent will hand it straight back."))
                        st.rerun()

    # ---- the tasks ---------------------------------------------------------------------------------
    st.markdown("**Tasks**")
    if not tasks:
        st.caption("No tasks yet.")
    else:
        st.dataframe(task_rows(tasks), hide_index=True, width="stretch")
        chosen_id = st.selectbox("Task", [task.id for task in tasks], format_func=lambda item: f"{item}  {next(t.title for t in tasks if t.id == item)[:60]}", key="agent_chosen_task")
        chosen = next(task for task in tasks if task.id == chosen_id)
        st.caption(f"{describe(chosen)} · tests: {'; '.join(' '.join(command) for command in chosen.acceptance) or '(none)'}")
        if not read_only:
            run_now, hand_over, cancel = st.columns(3)
            if run_now.button("Work on it now", key="agent_run_now", help="Runs here and now with the selected model. On a CPU this takes minutes."):
                with st.spinner("The agent is working. This page waits until it stops."):
                    done = build().run(chosen.id)
                _notice(f"The agent stopped: {describe(done)}")
                st.rerun()
            if hand_over.button("Hand to the background worker", key="agent_queue", help="Needs a worker: `python -m agent worker`, or the button under Background work."):
                try:
                    queue.enqueue("coding_task", {"task_id": chosen.id}, timeout_seconds=7200, max_attempts=2, idempotency_key=f"coding:{chosen.id}:{chosen.updated_at}")
                    _notice("Queued for the background worker.")
                except StoreError as exc:  # the queue is full (agent/jobs.py QUEUE_LIMITS)
                    _notice(f"Not queued: {exc}")
                st.rerun()
            if chosen.status not in {"done", "cancelled"} and cancel.button("Cancel the task", key="agent_cancel"):
                store.update_task(chosen.id, status="cancelled", note="Cancelled in the app")
                _notice("Cancelled. Its branch and commits, if any, are still in the repository.")
                st.rerun()
        with st.expander("What happened, step by step", expanded=False):
            for event in store.events(chosen.id)[-40:]:
                st.write(f"{str(event['at'])[11:19]}  {event['message']}")
            for attempt in chosen.state.get("attempts", []):
                st.caption(f"Attempt {attempt['number']}: {(attempt.get('problem') or 'worked').splitlines()[0][:200]}")

    render_project_memory(store, read_only=read_only, repos=[task.repo for task in tasks])

    # ---- everything it did ---------------------------------------------------------------------------
    with st.expander("Every action taken (inputs, approval, result)", expanded=False):
        actions = store.actions(limit=60)
        if actions:
            st.dataframe(action_rows(actions, store), hide_index=True, width="stretch")
            st.caption("'checked' means the result was confirmed by looking at the files, the branch or the remote, not taken from the tool's word.")
        else:
            st.caption("Nothing yet.")

    # ---- background work -------------------------------------------------------------------------------
    with st.expander("Background work: jobs, schedules, notices", expanded=False):
        jobs = queue.jobs(limit=20)
        if jobs:
            st.dataframe(
                [{"Job": job.id, "Kind": job.kind, "Status": job.status, "Try": f"{job.attempts}/{job.max_attempts}", "Note": job.progress_note or job.error[:100]} for job in jobs],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No jobs.")
        for schedule in queue.schedules():
            how = f"every {schedule['every_seconds']} s" if schedule["every_seconds"] else f"daily at {schedule['daily_at']}"
            st.write(f"{'On' if schedule['enabled'] else 'Off'}: {schedule['name']} ({how}; next {str(schedule['next_run'])[:19]})")
        for item in queue.notices(limit=10):
            st.write(f"{'New: ' if not item['seen'] else ''}{item['title']} ({str(item['at'])[:19]})")
        st.caption("Jobs run while a worker is running: `python -m agent worker` in a terminal keeps one going.")
        if not read_only and make_worker is not None and st.button("Run waiting jobs now", key="agent_worker_once"):
            with st.spinner("Running waiting jobs. This page waits until they finish."):
                worker = make_worker(queue)
                queue.recover()
                queue.tick()
                started = worker.run_once()
                worker.wait(7200)
            _notice(f"Ran {started} job(s).")
            st.rerun()

    # ---- what it can do, and what holds it -----------------------------------------------------------
    with st.expander("What it can do: every tool, app and linked account", expanded=False):
        agent = build()
        tables = capability_tables(_catalogue(agent))
        st.dataframe(tables["tools"], hide_index=True, width="stretch")
        st.caption("What runs unasked and what waits for you is set in Settings, Behaviour, under Coding agent. This list describes; it grants nothing.")
        st.markdown("**Apps the tools rely on**")
        st.dataframe(tables["apps"], hide_index=True, width="stretch")
        st.markdown("**Linked accounts**")
        st.dataframe(tables["accounts"], hide_index=True, width="stretch")
        st.caption("Accounts are linked, narrowed and unlinked in Settings, Linked accounts.")
        router = getattr(agent.model, "router", None)
        if router is not None:
            from modules.model_capabilities import rows

            order = [name for name in (agent.settings.get("provider_order") or []) if name != "fallback"]
            provider = order[0] if order else "ollama"
            model = str(getattr(agent.model, "model", "") or agent.settings.get("selected_model") or agent.settings.get(f"{provider}_model") or "")
            if not model and provider == "ollama":
                model = next(iter(router.detect_provider("ollama").models), "")
            found = router.capabilities(provider, model)
            st.markdown(f"**What the model can do** ({provider}: {model or 'none selected'}; {found.source})")
            st.dataframe(rows(found), hide_index=True, width="stretch")
            for note in found.notes:
                st.caption(note)
    with st.expander("What the sandbox enforces on this machine", expanded=False):
        for key, value in sandbox.isolation_report().items():
            st.write(f"**{key}**: {value}")
