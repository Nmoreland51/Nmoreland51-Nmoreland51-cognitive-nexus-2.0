"""What is known about each project: kept, shown to the coding agent, and kept up to date by it (item 048)."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from agent import cli
from agent.coder import build_prompt
from agent.project_memory import BRIEF_CHARS, ProjectMemory, git_state, project_key
from agent.store import AgentStore, StoreError
from tests.test_agent_coder import GOOD, git, make_agent, new_task, repo, store  # noqa: F401  (fixtures)


@pytest.fixture
def memory(store):  # noqa: F811
    return ProjectMemory(store)


# ---- the notes ------------------------------------------------------------------------------------


def test_the_owner_writes_objectives_decisions_and_bugs_and_closing_keeps_them_in_the_history(memory, tmp_path):
    project = str(tmp_path / "shop")
    goal = memory.add(project, "objective", "Ship the order export by Friday")
    decision = memory.add(project, "decision", "Keep SQLite; the data is small")
    bug = memory.add(project, "bug", "The importer drops the last row")

    assert [row["kind"] for row in memory.notes(project)] == ["objective", "decision", "bug"]
    closed = memory.close(bug["id"], by="Nora", note="fixed in 3f2a1c")
    assert closed["status"] == "closed" and closed["closed_by"] == "Nora" and closed["close_note"] == "fixed in 3f2a1c"
    assert [row["id"] for row in memory.notes(project)] == [goal["id"], decision["id"]]
    assert bug["id"] in [row["id"] for row in memory.notes(project, include_closed=True)]
    with pytest.raises(StoreError, match="already closed"):
        memory.close(bug["id"], by="Nora")


@pytest.mark.parametrize(
    "kind, text, problem",
    [("wish", "something", "Unknown kind"), ("bug", "   ", "empty"), ("bug", "x" * 2001, "at most 2000")],
)
def test_a_note_that_cannot_be_kept_is_refused_with_the_reason(memory, tmp_path, kind, text, problem):
    with pytest.raises(StoreError, match=problem):
        memory.add(str(tmp_path), kind, text)


def test_a_project_is_the_same_project_however_its_folder_or_address_is_written(tmp_path):
    folder = tmp_path / "Shop"
    folder.mkdir()
    assert project_key(str(folder)) == project_key(str(folder) + "/") == project_key(str(folder / "sub" / ".."))
    assert project_key("https://github.com/Owner/Shop.git") == project_key("https://github.com/owner/shop/")


def test_notes_outlive_the_app(tmp_path):
    first = AgentStore(tmp_path / "agent.db")
    ProjectMemory(first).add(str(tmp_path), "decision", "Use UTC everywhere")
    first.close()
    again = AgentStore(tmp_path / "agent.db")
    try:
        assert [row["text"] for row in ProjectMemory(again).notes(str(tmp_path))] == ["Use UTC everywhere"]
    finally:
        again.close()


def test_the_last_test_result_replaces_the_one_before_for_the_same_command(memory, tmp_path):
    runs = [{"argv": ["python", "-m", "pytest", "-q"], "passed": False, "counts": {"failed": 2, "passed": 1}}]
    memory.record_tests(str(tmp_path), runs, when="on the untouched code")
    memory.record_tests(str(tmp_path), [{**runs[0], "passed": True, "counts": {"passed": 3}}], when="after the change")
    tests = memory.notes(str(tmp_path), kinds=("test",))
    assert [row["text"] for row in tests] == ["$ python -m pytest -q: passed (3 passed), after the change"]
    assert tests[0]["source"] == "agent"


def test_the_state_of_a_repository_is_read_from_git(memory, repo):  # noqa: F811
    (repo / "notes.txt").write_text("not committed yet\n", encoding="utf-8")
    state = git_state(str(repo))
    assert state is not None and state["branch"] == "main" and state["head"].endswith(" first") and state["uncommitted"] == 1
    written = memory.record_state(str(repo))
    assert written is not None and "branch main, last commit" in written["text"] and "1 uncommitted file(s)" in written["text"]
    assert git_state(str(repo / "no-such-folder")) is None


def test_the_brief_marks_whose_note_each_is_and_stays_short(memory, tmp_path):
    project = str(tmp_path)
    memory.add(project, "bug", "The importer drops the last row")
    memory.record_tests(project, [{"argv": ["pytest"], "passed": False, "counts": {"failed": 1}}])
    brief = memory.brief(project)
    assert brief.splitlines() == [
        "Known bugs (the owner's notes):",
        "- The importer drops the last row",
        "Last test runs (recorded by the agent):",
        "- $ pytest: failed (1 failed)",
    ]
    for number in range(30):
        memory.add(project, "decision", f"Decision number {number}: " + "because " * 20)
    long = memory.brief(project)
    assert len(long) <= BRIEF_CHARS and long.endswith("- (more in the project memory)")
    assert memory.brief(str(tmp_path / "unknown")) == ""


# ---- the coding agent uses it ------------------------------------------------------------------------


def test_without_notes_the_agents_prompt_is_exactly_as_before(repo, store):  # noqa: F811
    task = new_task(store, repo)
    assert build_prompt(task, "1 failed", [], [], [], []) == build_prompt(task, "1 failed", [], [], [], [], project="")
    assert "WHAT IS KNOWN ABOUT THIS PROJECT" not in build_prompt(task, "1 failed", [], [], [], [])
    assert "add(2, 3) returns -1 instead of 5.\n\nTHE TESTS THAT MUST PASS" in build_prompt(task, "1 failed", [], [], [], [])


def test_the_agent_is_shown_what_is_known_and_keeps_the_tests_and_state_up_to_date(repo, store, tmp_path):  # noqa: F811
    memory = ProjectMemory(store)
    memory.add(str(repo), "decision", "Keep add() free of type checks; callers pass numbers")
    agent = make_agent(store, tmp_path, [GOOD])

    task = agent.run(new_task(store, repo).id)

    assert task.status == "review", task.result
    prompt = agent.model.prompts[0]
    assert "WHAT IS KNOWN ABOUT THIS PROJECT\nDecisions (the owner's notes):\n- Keep add() free of type checks; callers pass numbers" in prompt
    tests = memory.notes(str(repo), kinds=("test",))
    assert len(tests) == 1 and tests[0]["text"].endswith(f"passed (3 passed), after the agent's change, on its branch {task.branch}")
    state = memory.notes(str(repo), kinds=("state",))
    assert len(state) == 1 and state[0]["text"].startswith("branch main, last commit")


# ---- where the owner reaches it ---------------------------------------------------------------------------


def test_the_command_line_adds_lists_and_closes_notes(tmp_path, capsys):
    db = str(tmp_path / "agent.db")
    project = str(tmp_path / "shop")
    assert cli.main(["--db", db, "memory", "add", "--repo", project, "--kind", "bug", "The importer drops the last row"]) == 0
    note_id = capsys.readouterr().out.strip()
    assert cli.main(["--db", db, "memory"]) == 0
    listed = capsys.readouterr().out
    assert project_key(project) in listed and note_id in listed and "The importer drops the last row" in listed
    assert cli.main(["--db", db, "memory", "close", note_id, "--by", "Nora"]) == 0
    assert "closed: The importer drops the last row" in capsys.readouterr().out
    assert cli.main(["--db", db, "memory", "add", "--repo", project, "--kind", "bug", " "]) == 2


def _panel(db: str, project: str, read_only: bool) -> None:
    from agent.project_memory import ProjectMemory
    from agent.store import AgentStore
    from ui.project_memory_panel import render_project_memory

    agent_store = AgentStore(db)
    ProjectMemory(agent_store).add(project, "objective", "Ship the order export by Friday")
    render_project_memory(agent_store, read_only=read_only, repos=[project])


def test_the_agent_tab_shows_the_notes_and_takes_new_ones(tmp_path):
    db, project = str(tmp_path / "agent.db"), str(tmp_path / "shop")
    page = AppTest.from_function(_panel, args=(db, project, False), default_timeout=60).run()
    assert not page.exception
    assert any("Ship the order export by Friday" in item.value for item in page.markdown)
    page.text_area[0].input("Use UTC everywhere")
    page.selectbox[1].select("decision")
    page.button[-1].click().run()
    assert not page.exception
    saved = AgentStore(db)
    try:
        assert "Use UTC everywhere" in [row["text"] for row in ProjectMemory(saved).notes(project)]
    finally:
        saved.close()


def test_in_demo_safe_mode_the_notes_are_shown_but_cannot_be_changed(tmp_path):
    page = AppTest.from_function(_panel, args=(str(tmp_path / "agent.db"), str(tmp_path / "shop"), True), default_timeout=60).run()
    assert not page.exception
    assert not page.button and not page.text_area
