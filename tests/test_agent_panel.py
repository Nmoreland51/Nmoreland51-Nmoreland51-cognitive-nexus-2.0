"""The Agent tab, driven through the real interface, with the real loop behind it and a scripted model."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent.store import AgentStore
from ui import agent_panel

ACCEPTANCE = "python -m pytest -q -p no:cacheprovider test_calc.py"


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    monkeypatch.setenv("CN_TEST_AGENT_DB", str(tmp_path / "agent.db"))
    monkeypatch.setenv("CN_TEST_AGENT_WS", str(tmp_path / "ws"))
    monkeypatch.delenv("CN_TEST_AGENT_READ_ONLY", raising=False)
    return {"repo": repo, "db": tmp_path / "agent.db"}


def _panel_app():
    import os

    from agent.coder import default_agent
    from agent.model import ScriptedModel
    from agent.store import AgentStore
    from agent.workspace import WorkspaceManager
    from ui.agent_panel import render_agent_panel

    store = AgentStore(os.environ["CN_TEST_AGENT_DB"])
    fix = "The function subtracts instead of adding.\n\nFILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"

    def build():
        return default_agent(store, ScriptedModel([fix]), model_review=False, workspaces=WorkspaceManager(os.environ["CN_TEST_AGENT_WS"]))

    render_agent_panel(store, build, read_only=os.environ.get("CN_TEST_AGENT_READ_ONLY") == "1")


def shown(app) -> str:
    return "\n".join([item.value for item in app.markdown] + [item.value for item in app.caption] + [item.value for item in app.success] + [item.value for item in app.info])


def test_the_form_checks_what_it_is_given(world, tmp_path):
    store = AgentStore(world["db"])

    assert agent_panel.new_task(store, str(world["repo"]), "", "", ACCEPTANCE, 3, 30) == (None, "Give the task a title.")
    made, problem = agent_panel.new_task(store, str(tmp_path / "nowhere"), "Fix add", "", ACCEPTANCE, 3, 30)
    assert made is None and "is not a Git repository" in problem
    made, problem = agent_panel.new_task(store, str(world["repo"]), "Fix add", "it subtracts", ACCEPTANCE + "\n\npython -m ruff check .", 2, 10)
    assert problem == "" and made.acceptance == [ACCEPTANCE.split(), ["python", "-m", "ruff", "check", "."]]
    assert made.budget == {"attempts": 2, "seconds": 600.0} and Path(made.repo) == world["repo"].resolve()


def test_an_empty_tab_explains_itself_and_offers_the_form(world):
    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    assert not app.exception
    text = shown(app)
    # No claim beyond the model, and the number quoted is the one from tasks the harness was not tuned on.
    saved = json.loads((Path(__file__).resolve().parents[1] / "docs" / "benchmarks" / "agent_heldout_dolphin3-8b.json").read_text(encoding="utf-8"))
    assert (saved["summary"]["solved"], saved["summary"]["solvable"]) == (4, 9)
    assert "of nine small seeded bugs it had never been tried on" in text and "fixed 4." in text and "no cleverer than that model" in text
    assert "**Waiting for you: 0**" in text and "No tasks yet." in text
    assert app.text_input(key="agent_new_repo") is not None


def test_a_task_is_given_worked_on_shown_and_accepted_through_the_tab(world):
    """The whole path with the real loop: add, run, see the diff and the history, accept."""

    app = AppTest.from_function(_panel_app, default_timeout=180).run()
    app.text_input(key="agent_new_repo").input(str(world["repo"]))
    app.text_input(key="agent_new_title").input("add() subtracts")
    app.text_area(key="agent_new_tests").input(ACCEPTANCE)
    app.button[0].click().run()  # the form's submit button
    assert not app.exception
    store = AgentStore(world["db"])
    task = store.list_tasks()[0]
    assert task.title == "add() subtracts" and any("Added task" in item.value for item in app.success)

    app.button(key="agent_run_now").click().run()

    assert not app.exception
    task = store.get_task(task.id)
    assert task.status == "review", task.result
    text = shown(app)
    assert "**Waiting for you: 1**" in text and "The agent stopped" in text
    assert any("+    return a + b" in item.value for item in app.code)  # the diff, from the task's own branch
    rows = agent_panel.action_rows(store.actions(limit=60))
    assert {"run_tests", "replace_in_file", "commit_changes"} <= {row["Tool"] for row in rows}
    assert any(row["Outcome"] == "checked" for row in rows)

    app.button(key=f"agent_accept_{task.id}").click().run()

    assert not app.exception
    assert store.get_task(task.id).status == "done"
    assert any("nothing was merged or pushed" in item.value for item in app.success)
    # The user's own checkout was never touched; the fix is on the task's branch.
    assert "return a - b" in (world["repo"] / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in git(world["repo"], "show", f"{task.branch}:calc.py")


def test_a_request_for_approval_is_decided_in_the_tab(world):
    store = AgentStore(world["db"])
    task = store.create_task("Publish", repo=str(world["repo"]))
    request = store.request_approval(key="k1", tool="push_branch", effect="external", summary="push the task's own branch to origin", arguments={}, task_id=task.id)

    app = AppTest.from_function(_panel_app, default_timeout=60).run()
    assert "push the task's own branch to origin" in shown(app)
    app.button(key=f"agent_refuse_{request}").click().run()

    assert not app.exception
    assert store.approval(request)["status"] == "denied" and store.approval(request)["decided_by"] == "owner"
    assert store.approvals() == []


def test_in_demo_safe_mode_the_tab_shows_and_changes_nothing(world, monkeypatch):
    store = AgentStore(world["db"])
    store.create_task("Something", repo=str(world["repo"]), acceptance=[ACCEPTANCE.split()])
    monkeypatch.setenv("CN_TEST_AGENT_READ_ONLY", "1")

    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    assert not app.exception and "Something" in str([frame.value for frame in app.dataframe])
    assert not [button for button in app.button]


def test_the_history_says_who_allowed_an_action_and_what_it_produced(world, tmp_path):
    """One real tool call that needs approval, allowed by the owner, as the history table shows it."""

    from agent.approvals import ApprovalPolicy
    from agent.registry import Tool, ToolContext, ToolRegistry, ToolResult

    store = AgentStore(world["db"])
    registry = ToolRegistry()
    made = tmp_path / "report.txt"

    def send_report(context):
        made.write_text("done", encoding="utf-8")
        return ToolResult(ok=True, output="sent", artifacts=[str(made)])

    registry.register(Tool("send_report", "Send a report.", {"type": "object", "properties": {}, "additionalProperties": False}, "external", send_report))
    context = ToolContext(store=store, policy=ApprovalPolicy())
    asked = registry.call("send_report", {}, context)
    assert asked.status == "needs_approval" and not made.exists()
    store.decide_approval(asked.approval_id, approved=True, by="owner")
    assert registry.call("send_report", {}, context).ok

    rows = agent_panel.action_rows(store.actions(), store)

    assert rows[0]["Tool"] == "send_report" and rows[0]["Can affect"] == "external" and rows[0]["Result"] == "ok"
    assert rows[0]["Approval"] == "allowed by owner" and rows[0]["Produced"] == str(made) and rows[0]["Input"] == "{}"
    assert agent_panel.action_rows([{**store.actions()[0], "approval_id": ""}])[0]["Approval"] == "not needed"


def test_the_capability_list_is_three_tables_a_person_can_read():
    listing = {
        "tools": [
            {"name": "web_search", "adapter": "web", "effect": "network", "usable": True, "missing": [], "checks_its_outcome": False, "description": "Search the web."},
            {"name": "open_pull_request", "adapter": "github", "effect": "external", "usable": False, "missing": ["needs a GitHub account allowed for 'pull_request' (not linked)"], "checks_its_outcome": True, "description": "Open a draft pull request."},
        ],
        "apps": [{"key": "git", "name": "Git", "found": True, "detail": "git version 2.56", "used_for": "Checkouts."}],
        "accounts": [
            {"service": "github", "name": "GitHub", "linked": True, "how": "stored by this app", "permissions": ["read"], "used_by_tools": ["ci_status"], "used_for": "Publishing."},
            {"service": "openai", "name": "OpenAI", "linked": False, "how": "", "permissions": [], "used_by_tools": [], "used_for": "Answers from OpenAI models."},
        ],
    }

    tables = agent_panel.capability_tables(listing)

    assert tables["tools"][0]["Usable now"] == "yes" and tables["tools"][1]["Usable now"] == "no: needs a GitHub account allowed for 'pull_request' (not linked)"
    assert tables["tools"][1]["Checks its outcome"] == "yes" and tables["apps"] == [{"App": "Git", "Found": "yes", "Detail": "git version 2.56", "Used for": "Checkouts."}]
    assert tables["accounts"][0] == {"Service": "GitHub", "Linked": "yes (stored by this app)", "May be used for": "read", "Used by": "ci_status"}
    assert tables["accounts"][1] == {"Service": "OpenAI", "Linked": "no", "May be used for": "", "Used by": "Answers from OpenAI models."}


def test_the_tab_shows_tools_apps_and_accounts(world):
    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    assert not app.exception
    frames = [frame.value for frame in app.dataframe]
    assert any("Usable now" in frame.columns and "run_tests" in set(frame["Tool"]) for frame in frames)
    assert any("App" in frame.columns and "Git" in set(frame["App"]) for frame in frames)
    assert any("Service" in frame.columns and {"GitHub", "OpenAI", "Anthropic", "Brave Search"} <= set(frame["Service"]) for frame in frames)

