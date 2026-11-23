"""Tools run only through the registry: schema, approval, no repeated writes, a checked outcome, a record."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agent.approvals import MODES, ApprovalPolicy
from agent.registry import EFFECTS, Tool, ToolContext, ToolError, ToolRegistry, ToolResult, action_key, bounded
from agent.store import AgentStore, StoreError
from modules import event_log

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    made = AgentStore(tmp_path / "agent.db")
    yield made
    made.close()


def make_registry(calls, target=None):
    """A registry with one tool of each kind. `calls` records every real run."""

    registry = ToolRegistry()

    def look(context, path):
        calls.append(("look", path))
        return ToolResult(ok=True, output=f"contents of {path}")

    def put(context, path, text):
        calls.append(("put", path))
        if target is not None:
            (target / path).write_text(text, encoding="utf-8")
        return ToolResult(ok=True, output=f"wrote {path}", artifacts=[path])

    def put_was_written(context, arguments, result):
        if target is None:
            return True, "not checked"
        written = (target / arguments["path"]).read_text(encoding="utf-8") if (target / arguments["path"]).exists() else None
        return written == arguments["text"], "the file holds the text" if written == arguments["text"] else "the file does not hold the text"

    def publish(context, title):
        calls.append(("publish", title))
        return ToolResult(ok=True, output=f"published {title}", data={"url": "https://example.org/1"})

    def lie(context):
        calls.append(("lie",))
        return ToolResult(ok=True, output="all done, trust me")

    def explode(context, how):
        calls.append(("explode", how))
        if how == "politely":
            raise ToolError("that cannot be done")
        raise RuntimeError("a bug in the tool")

    text = {"type": "string", "minLength": 1}
    registry.register(Tool("look", "Read a file.", {"type": "object", "properties": {"path": text}, "required": ["path"], "additionalProperties": False}, "read", look, repeatable=True))
    registry.register(
        Tool(
            "put",
            "Write a file.",
            {"type": "object", "properties": {"path": text, "text": {"type": "string"}}, "required": ["path", "text"], "additionalProperties": False},
            "write",
            put,
            verify=put_was_written,
            summarize=lambda arguments: f"write {arguments['path']}",
        )
    )
    registry.register(Tool("publish", "Publish.", {"type": "object", "properties": {"title": text}, "required": ["title"], "additionalProperties": False}, "external", publish))
    registry.register(Tool("lie", "Claims success.", {"type": "object", "properties": {}, "additionalProperties": False}, "write", lie, verify=lambda c, a, r: (False, "nothing was changed")))
    registry.register(Tool("explode", "Fails.", {"type": "object", "properties": {"how": text}, "required": ["how"]}, "execute", explode, repeatable=True))
    return registry


def context(store, **options):
    return ToolContext(store=store, task_id=options.pop("task_id", "task_1"), policy=options.pop("policy", ApprovalPolicy()), **options)


# ---- arguments ------------------------------------------------------------------------------------


def test_arguments_are_checked_against_the_schema_before_anything_runs(store):
    calls = []
    registry = make_registry(calls)
    for arguments, complaint in (({}, "'path' is a required property"), ({"path": 7}, "is not of type 'string'"), ({"path": "a", "extra": 1}, "Additional properties")):
        result = registry.call("look", arguments, context(store))
        assert (result.ok, result.status) == (False, "invalid")
        assert complaint in result.error
    assert calls == []
    recorded = store.actions("task_1")
    assert len(recorded) == 3 and {item["status"] for item in recorded} == {"invalid"}


def test_an_unknown_tool_is_refused_and_names_the_ones_that_exist(store):
    result = make_registry([]).call("format_disk", {}, context(store))
    assert result.status == "invalid"
    assert "no tool named 'format_disk'" in result.error and "look" in result.error


def test_registration_refuses_bad_definitions():
    registry = ToolRegistry()
    ok = {"type": "object", "properties": {}}
    registry.register(Tool("one", "", ok, "read", lambda context: ToolResult(ok=True)))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("one", "", ok, "read", lambda context: ToolResult(ok=True)))
    with pytest.raises(ValueError, match="not an effect"):
        registry.register(Tool("two", "", ok, "destroy", lambda context: ToolResult(ok=True)))
    with pytest.raises(ValueError, match="must describe an object"):
        registry.register(Tool("three", "", {"type": "string"}, "read", lambda context: ToolResult(ok=True)))
    with pytest.raises(Exception):
        registry.register(Tool("four", "", {"type": "object", "properties": {"a": {"type": "no-such-type"}}}, "read", lambda context: ToolResult(ok=True)))


def test_the_registry_describes_itself_as_data():
    described = make_registry([]).describe()
    assert [item["name"] for item in described] == ["explode", "lie", "look", "publish", "put"]
    put = next(item for item in described if item["name"] == "put")
    assert put["effect"] == "write" and put["checks_its_outcome"] and put["parameters"]["required"] == ["path", "text"]
    assert [item["name"] for item in make_registry([]).describe(effects=("read",))] == ["look"]


# ---- approvals ------------------------------------------------------------------------------------


def test_the_policy_table():
    expected = {
        "read_only": ("allow", "deny", "deny", "deny", "deny"),
        "ask": ("allow", "ask", "ask", "ask", "ask"),
        "workspace": ("allow", "allow", "allow", "ask", "ask"),
        "trusted": ("allow", "allow", "allow", "allow", "ask"),
    }
    assert set(expected) == set(MODES)
    for mode, decisions in expected.items():
        assert tuple(ApprovalPolicy(mode).decide("tool", effect) for effect in EFFECTS) == decisions, mode
    with pytest.raises(ValueError):
        ApprovalPolicy("anything_goes")


def test_no_mode_lets_an_outside_action_run_unasked_but_the_user_can_name_one():
    assert all(ApprovalPolicy(mode).decide("publish", "external") != "allow" for mode in MODES)
    standing = ApprovalPolicy("workspace", always_allow=("publish",), never_allow=("put",), always_ask=("look", "explode"))
    assert standing.decide("publish", "external") == "allow"
    assert standing.decide("put", "write") == "deny"
    assert standing.decide("explode", "execute") == "ask"
    assert standing.decide("look", "read") == "allow"  # reading never asks
    # A standing permission does not make a read-only session write.
    assert ApprovalPolicy("read_only", always_allow=("publish",)).decide("publish", "external") == "deny"


def test_policy_from_settings_falls_back_to_asking():
    assert ApprovalPolicy.from_settings({"agent_approval_mode": "nonsense"}).mode == "ask"
    policy = ApprovalPolicy.from_settings({"agent_approval_mode": "trusted", "agent_always_allow": "publish, put", "agent_never_allow": ["explode"]})
    assert (policy.mode, policy.always_allow, policy.never_allow) == ("trusted", ("publish", "put"), ("explode",))
    # The owner's default (agent_autonomy = publishing_asks): works on its own, asks before publishing.
    assert ApprovalPolicy.from_settings(None).mode == "trusted"
    assert ApprovalPolicy.from_settings(None).decide("push_branch", "external") == "ask"


def test_an_outside_action_waits_for_a_person_and_runs_once_per_approval(store):
    calls = []
    registry = make_registry(calls)
    ctx = context(store)

    first = registry.call("publish", {"title": "Release notes"}, ctx)
    assert (first.ok, first.status) == (False, "needs_approval") and calls == []
    assert registry.call("publish", {"title": "Release notes"}, ctx).approval_id == first.approval_id  # asked once, not twice
    pending = store.approvals()
    assert len(pending) == 1 and pending[0]["tool"] == "publish" and pending[0]["arguments"] == {"title": "Release notes"}

    store.decide_approval(first.approval_id, approved=True, by="Nora")
    second = registry.call("publish", {"title": "Release notes"}, ctx)
    assert second.ok and second.status == "ok" and second.approval_id == first.approval_id
    assert calls == [("publish", "Release notes")]

    # The approval was for that one action. The same action is not repeated; a different one asks again.
    assert registry.call("publish", {"title": "Release notes"}, ctx).status == "replayed"
    other = registry.call("publish", {"title": "Something else"}, ctx)
    assert other.status == "needs_approval" and other.approval_id != first.approval_id
    again = registry.call("publish", {"title": "Release notes"}, ctx, step="attempt-2")
    assert again.status == "needs_approval"
    assert calls == [("publish", "Release notes")]
    assert store.approval(first.approval_id)["status"] == "used"


def test_a_refused_approval_is_final_for_that_action(store):
    calls = []
    registry = make_registry(calls)
    asked = registry.call("publish", {"title": "Leak"}, context(store))
    store.decide_approval(asked.approval_id, approved=False, by="Nora", note="not this")
    refused = registry.call("publish", {"title": "Leak"}, context(store))
    assert (refused.status, calls) == ("denied", [])
    assert "Nora refused this action: not this" in refused.error
    with pytest.raises(StoreError, match="already denied"):
        store.decide_approval(asked.approval_id, approved=True, by="Nora")
    with pytest.raises(StoreError, match="who decided"):
        store.decide_approval(registry.call("publish", {"title": "Other"}, context(store)).approval_id, approved=True, by="  ")


def test_a_read_only_session_cannot_write(store):
    calls = []
    registry = make_registry(calls)
    ctx = context(store, policy=ApprovalPolicy("read_only"))
    assert registry.call("look", {"path": "a.txt"}, ctx).ok
    refused = registry.call("put", {"path": "a.txt", "text": "x"}, ctx)
    assert refused.status == "denied" and "read_only" in refused.error
    assert calls == [("look", "a.txt")]
    assert store.actions("task_1")[0]["status"] == "denied"


# ---- not repeating, checking, recording ---------------------------------------------------------


def test_a_completed_write_is_not_repeated_when_a_task_is_resumed(store, tmp_path):
    calls = []
    registry = make_registry(calls, target=tmp_path)
    first = registry.call("put", {"path": "note.txt", "text": "hello"}, context(store), step="3")
    assert first.ok and first.verified and first.artifacts == ["note.txt"]
    (tmp_path / "note.txt").write_text("edited by a later step")
    # The process restarts and the agent runs step 3 again.
    replay = registry.call("put", {"path": "note.txt", "text": "hello"}, context(store), step="3")
    assert replay.ok and replay.replayed and replay.output == "wrote note.txt" and replay.action_id == first.action_id
    assert calls == [("put", "note.txt")]
    assert (tmp_path / "note.txt").read_text() == "edited by a later step"
    # The same write as a new step, or for another task, is a new action.
    assert registry.call("put", {"path": "note.txt", "text": "hello"}, context(store), step="4").status == "ok"
    assert registry.call("put", {"path": "note.txt", "text": "hello"}, context(store, task_id="task_2"), step="3").status == "ok"
    assert len(calls) == 3


def test_reads_and_test_runs_are_simply_run_again(store):
    calls = []
    registry = make_registry(calls)
    for _ in range(3):
        assert registry.call("look", {"path": "a.txt"}, context(store)).status == "ok"
    assert len(calls) == 3


def test_a_failed_action_is_not_treated_as_done(store):
    calls = []
    registry = make_registry(calls)
    assert registry.call("lie", {}, context(store)).status == "failed"
    assert registry.call("lie", {}, context(store)).status == "failed"
    assert len(calls) == 2  # it ran again: only a success is remembered


def test_success_is_believed_only_after_checking_the_outcome(store, tmp_path):
    result = make_registry([]).call("lie", {}, context(store))
    assert not result.ok and result.verified is False
    assert "reported success, but checking the result showed otherwise: nothing was changed" in result.error
    recorded = store.actions("task_1")[0]
    assert recorded["status"] == "failed" and recorded["verified"] is False and recorded["output"] == "all done, trust me"

    calls = []
    registry = make_registry(calls, target=tmp_path)
    good = registry.call("put", {"path": "a.txt", "text": "one"}, context(store))
    assert good.ok and good.verified is True and good.verification == "the file holds the text"
    assert registry.call("look", {"path": "a.txt"}, context(store)).verified is None  # a tool without a check says so


def test_a_tool_that_fails_or_crashes_returns_a_result_and_is_counted(store):
    event_log.reset_events()
    registry = make_registry([])
    polite = registry.call("explode", {"how": "politely"}, context(store))
    assert (polite.ok, polite.status, polite.error) == (False, "failed", "that cannot be done")
    crash = registry.call("explode", {"how": "badly"}, context(store))
    assert crash.status == "failed" and "failed unexpectedly: RuntimeError: a bug in the tool" in crash.error
    assert event_log.event_counts().get("tool_failure") == 2
    assert event_log.recent_events(kind="tool_failure")[0]["tool"] == "explode"


def test_cancelling_stops_further_actions(store):
    calls = []
    ctx = context(store)
    ctx.cancel.set()
    assert make_registry(calls).call("look", {"path": "a"}, ctx).status == "cancelled"
    assert calls == []


def test_the_history_shows_inputs_approval_result_and_artifacts(store, tmp_path):
    registry = make_registry([], target=tmp_path)
    registry.call("put", {"path": "a.txt", "text": "one"}, context(store))
    asked = registry.call("publish", {"title": "T"}, context(store))
    store.decide_approval(asked.approval_id, approved=True, by="Nora")
    registry.call("publish", {"title": "T"}, context(store))
    newest, older = store.actions("task_1")[:2]
    assert (newest["tool"], newest["effect"], newest["arguments"], newest["status"]) == ("publish", "external", {"title": "T"}, "ok")
    assert newest["approval_id"] == asked.approval_id and newest["data"] == {"url": "https://example.org/1"}
    assert older["tool"] == "put" and older["artifacts"] == ["a.txt"] and older["verified"] is True
    assert newest["started_at"] <= newest["finished_at"] and newest["duration"] >= 0
    assert [item["tool"] for item in store.actions("task_1", effect="external")] == ["publish"]
    kinds = [event["kind"] for event in store.events("task_1")]
    assert kinds == ["approval_requested", "approval_approved"]


def test_an_action_cut_short_by_a_crash_is_found_afterwards(store):
    key = action_key("put", {"path": "a.txt", "text": "x"}, task_id="task_1")
    action_id = store.begin_action(key=key, tool="put", effect="write", arguments={"path": "a.txt", "text": "x"}, task_id="task_1")
    assert [item["id"] for item in store.interrupted_actions("task_1")] == [action_id]
    assert store.completed_action(key) is None  # so it is not mistaken for done
    store.mark_interrupted(action_id, "The app stopped while this was running.")
    assert store.interrupted_actions() == []
    assert store.actions("task_1")[0]["status"] == "interrupted"


def test_action_keys_and_bounded_output():
    arguments = {"b": 2, "a": 1}
    assert action_key("t", arguments, task_id="x") == action_key("t", {"a": 1, "b": 2}, task_id="x")
    assert len({action_key("t", arguments, task_id="x"), action_key("t", arguments, task_id="y"), action_key("t", arguments, task_id="x", step="2"), action_key("u", arguments, task_id="x")}) == 4
    long = "A" * 30_000 + "END"
    cut = bounded(long, 1000)
    assert len(cut) < 1100 and cut.startswith("AAAA") and cut.endswith("END") and "left out" in cut
    assert bounded("short") == "short"


# ---- tasks ----------------------------------------------------------------------------------------


def test_tasks_have_an_owner_a_status_blockers_and_acceptance_tests(store):
    task = store.create_task(
        "Fix the date parser",
        "It drops the day.",
        owner="agent",
        repo="C:/work/project",
        acceptance=[["python", "-m", "pytest", "tests/test_dates.py"]],
        budget={"attempts": 3, "seconds": 900},
        priority=5,
    )
    assert (task.status, task.owner, task.acceptance, task.budget["attempts"]) == ("queued", "agent", [["python", "-m", "pytest", "tests/test_dates.py"]], 3)
    task = store.update_task(task.id, status="running", state={"phase": "reproduce"})
    task = store.update_task(task.id, status="blocked", blockers=["Needs the fixture file from Sam"], note="Waiting for a file")
    assert task.blockers == ["Needs the fixture file from Sam"] and task.state == {"phase": "reproduce"}
    events = store.events(task.id)
    assert [event["kind"] for event in events] == ["created", "status", "status"]
    assert events[-1]["message"] == "Waiting for a file" and events[-1]["data"] == {"from": "running", "to": "blocked"}
    with pytest.raises(StoreError, match="no task"):
        store.get_task("task_missing")
    with pytest.raises(StoreError, match="needs a title"):
        store.create_task("   ")
    with pytest.raises(StoreError, match="no field"):
        store.update_task(task.id, colour="blue")


def test_only_sensible_status_changes_are_accepted(store):
    task = store.create_task("T")
    with pytest.raises(StoreError, match="queued cannot become done"):
        store.update_task(task.id, status="done")
    with pytest.raises(StoreError, match="not a task status"):
        store.update_task(task.id, status="finished")
    store.update_task(task.id, status="running")
    store.update_task(task.id, status="review")
    store.update_task(task.id, status="done")
    with pytest.raises(StoreError, match="done cannot become running"):
        store.update_task(task.id, status="running")
    assert store.get_task(task.id).status == "done"


def test_a_task_waits_for_the_tasks_it_depends_on(store):
    first = store.create_task("Write the parser")
    second = store.create_task("Use the parser", depends_on=[first.id])
    third = store.create_task("Urgent and independent", priority=9)
    assert second.depends_on == [first.id]
    assert [task.id for task in store.ready_tasks()] == [third.id, first.id]
    assert store.unfinished_dependencies(second.id) == [first.id]
    for status in ("running", "review", "done"):
        store.update_task(first.id, status=status)
    assert [task.id for task in store.ready_tasks()] == [third.id, second.id]
    with pytest.raises(StoreError, match="does not exist"):
        store.create_task("Orphan", depends_on=["task_nowhere"])


def test_tasks_cannot_wait_for_each_other(store):
    a, b, c = (store.create_task(name) for name in "ABC")
    store.add_dependency(b.id, a.id)
    store.add_dependency(c.id, b.id)
    with pytest.raises(StoreError, match="already depends on it"):
        store.add_dependency(a.id, c.id)
    with pytest.raises(StoreError, match="already depends on it"):
        store.add_dependency(a.id, a.id)
    assert store.get_task(a.id).depends_on == []


def test_a_database_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "agent.db"
    first = AgentStore(path)
    with first.transaction() as db:
        db.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    first.close()
    with pytest.raises(StoreError, match="newer version"):
        AgentStore(path)


def test_two_processes_can_write_at_the_same_time(tmp_path):
    path = tmp_path / "agent.db"
    AgentStore(path).close()
    worker = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])
        from agent.store import AgentStore
        store = AgentStore(sys.argv[2])
        for number in range(40):
            action = store.begin_action(key=f"{sys.argv[3]}-{number}", tool="put", effect="write", arguments={"n": number}, task_id="shared")
            store.finish_action(action, status="ok", output=str(number))
        """
    )
    workers = [subprocess.Popen([sys.executable, "-c", worker, str(REPO_ROOT), str(path), name]) for name in ("a", "b", "c")]
    assert [process.wait(timeout=120) for process in workers] == [0, 0, 0]
    store = AgentStore(path)
    recorded = store.actions("shared", limit=1000)
    store.close()
    assert len(recorded) == 120 and {item["status"] for item in recorded} == {"ok"}
    assert len({item["key"] for item in recorded}) == 120
