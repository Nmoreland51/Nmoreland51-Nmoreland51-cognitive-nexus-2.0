"""The project dashboard: milestones, build, bugs, agent progress, time estimates and recent changes (item 140).

GitHub is played by a stand-in here; the real lookup was tried once by hand (docs/benchmarks/README.md).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

from agent.project_memory import ProjectMemory
from agent.store import AgentStore
from modules import project_dashboard as dashboard
from tests.test_agent_coder import git, repo, store  # noqa: F401  (fixtures)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_milestones_are_the_audit_sections_with_the_ledger_counts():
    found = dashboard.milestones(REPO_ROOT)
    assert found is not None
    items = json.loads((REPO_ROOT / "docs" / "backlog" / "items.json").read_text(encoding="utf-8"))
    statuses = json.loads((REPO_ROOT / "docs" / "backlog" / "status.json").read_text(encoding="utf-8"))
    counted = Counter(statuses[number]["status"] for number in items["items"])
    assert len(found["sections"]) == len(items["sections"])
    assert found["totals"] == {
        "items": len(items["items"]),
        "complete": counted["COMPLETE"],
        "partial": counted["PARTIAL"],
        "missing": counted["MISSING"],
        "not_applicable": counted["NOT APPLICABLE"],
    }
    first = found["sections"][0]
    assert first["number"] == 1 and first["title"] == items["sections"][0]["title"]
    assert 0.0 <= first["done"] <= 1.0


def test_a_project_without_a_milestone_list_has_none(tmp_path):
    assert dashboard.milestones(tmp_path) is None


def test_recent_changes_branch_and_github_address_come_from_git(repo):  # noqa: F811
    git(repo, "remote", "add", "origin", "https://github.com/Owner/shop.git")
    assert dashboard.github_slug(repo) == "Owner/shop"
    git(repo, "remote", "set-url", "origin", "git@github.com:Owner/shop.git")
    assert dashboard.github_slug(repo) == "Owner/shop"
    git(repo, "remote", "set-url", "origin", "https://gitlab.example.org/owner/shop.git")
    assert dashboard.github_slug(repo) == ""
    assert dashboard.current_branch(repo) == "main"
    commits = dashboard.recent_commits(repo)
    assert [row["subject"] for row in commits] == ["first"] and len(commits[0]["commit"]) >= 7
    assert dashboard.recent_commits(repo / "missing") == []


class _Answer:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self.payload


class _GitHub:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def get(self, url, **how):
        self.asked.append((url, how))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_build_is_github_s_record_of_the_branch_s_workflow_runs():
    run = {"name": "Tests", "status": "completed", "conclusion": "success", "head_sha": "abc1234def", "run_started_at": "2026-11-24T23:54:10Z", "html_url": "https://github.com/o/r/actions/runs/1"}
    github = _GitHub(_Answer({"workflow_runs": [run]}))
    found = dashboard.ci_runs("o/r", "main", token="t0ken", session=github)
    assert found == {"runs": [{"workflow": "Tests", "status": "completed", "conclusion": "success", "commit": "abc1234", "started": "2026-11-24 23:54", "url": "https://github.com/o/r/actions/runs/1"}], "error": ""}
    url, how = github.asked[0]
    assert url == "https://api.github.com/repos/o/r/actions/runs" and how["params"]["branch"] == "main"
    assert how["headers"]["Authorization"] == "Bearer t0ken"


def test_when_github_cannot_tell_the_dashboard_says_why():
    assert "did not answer" in dashboard.ci_runs("o/r", "main", session=_GitHub(requests.ConnectionError("no network")))["error"]
    assert "did not answer" in dashboard.ci_runs("o/r", "main", session=_GitHub(_Answer({}, status=404)))["error"]
    assert "no workflow runs" in dashboard.ci_runs("o/r", "main", session=_GitHub(_Answer({"workflow_runs": []})))["error"]
    assert "no GitHub remote" in dashboard.ci_runs("", "main")["error"]


def test_progress_and_the_time_estimate_come_from_the_agent_s_tasks(store, tmp_path):  # noqa: F811
    project = str(tmp_path / "shop")
    finished = [store.create_task(f"Fix {name}", "", repo=project, budget={"attempts": 3, "seconds": 900}) for name in ("a", "b", "c")]
    for task, seconds in zip(finished, (120, 300, 600)):
        store.update_task(task.id, status="running")
        store.update_task(task.id, status="review", spent={"attempts": 1, "seconds": seconds})
    waiting = store.create_task("Fix d", "", repo=project, budget={"attempts": 3, "seconds": 600})
    store.create_task("Elsewhere", "", repo=str(tmp_path / "other"))

    progress = dashboard.agent_progress(store, project)
    assert progress["tasks"] == 4 and progress["by_status"] == {"review": 3, "queued": 1}
    assert progress["estimate"] == {"minutes_per_task": 5.0, "from_tasks": 3}  # the middle of 2, 5 and 10 minutes
    assert {"task": waiting.id, "title": "Fix d", "status": "queued", "attempts": "0 of 3", "minutes": "0.0 of 10.0"} in progress["open"]
    assert dashboard.agent_progress(store, str(tmp_path / "nothing"))["estimate"] == {"minutes_per_task": None, "from_tasks": 0}


def test_active_bugs_are_the_owner_s_notes_and_the_tasks_that_failed(store, tmp_path):  # noqa: F811
    project = str(tmp_path / "shop")
    ProjectMemory(store).add(project, "bug", "The importer drops the last row")
    failed = store.create_task("Fix the importer", "", repo=project)
    store.update_task(failed.id, status="running")
    store.update_task(failed.id, status="failed")
    other = store.create_task("Unrelated", "", repo=str(tmp_path / "other"))
    store.update_task(other.id, status="running")
    store.update_task(other.id, status="failed")

    bugs = dashboard.active_bugs(store, project)
    assert [row["what"] for row in bugs] == ["The importer drops the last row", "Fix the importer (failed)"]
    assert bugs[1]["from"] == f"agent task {failed.id}"


def _dashboard(db: str, root: str) -> None:
    from agent.store import AgentStore
    from ui.dashboard_panel import render_project_dashboard

    render_project_dashboard(AgentStore(db), root)


def test_the_dashboard_draws_the_milestones_of_this_repository(tmp_path):
    page = AppTest.from_function(_dashboard, args=(str(tmp_path / "agent.db"), str(REPO_ROOT)), default_timeout=60).run()
    assert not page.exception, [item.value for item in page.exception]
    assert any("-item audit, one milestone per section" in item.value for item in page.caption)
    assert len(page.dataframe) >= 2  # the milestones and the recent changes
    assert [item.label for item in page.metric][:2] == ["Agent tasks open", "Waiting for your review"]


def test_the_dashboard_of_a_plain_folder_says_what_it_does_not_have(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    page = AppTest.from_function(_dashboard, args=(str(tmp_path / "agent.db"), str(folder)), default_timeout=60).run()
    assert not page.exception
    shown = " ".join(item.value for item in page.caption)
    assert "no milestone list" in shown and "No GitHub remote" in shown and "Not a Git repository" in shown
    assert "No time estimate yet" in shown


def test_the_agent_tab_shows_the_dashboard_first(tmp_path):
    def panel(db: str) -> None:
        from agent.store import AgentStore
        from ui.agent_panel import render_agent_panel

        render_agent_panel(AgentStore(db), read_only=True)

    page = AppTest.from_function(panel, args=(str(tmp_path / "agent.db"),), default_timeout=60).run()
    assert not page.exception
    assert page.expander[0].label.startswith("Project dashboard")
    assert AgentStore  # the module imported above is the one the panel uses


def _dashboard_read_only(db: str, root: str) -> None:
    from agent.store import AgentStore
    from ui.dashboard_panel import render_project_dashboard

    render_project_dashboard(AgentStore(db), root, read_only=True)


def test_in_demo_safe_mode_the_dashboard_shows_no_path_and_looks_nothing_up(tmp_path):
    page = AppTest.from_function(_dashboard_read_only, args=(str(tmp_path / "agent.db"), str(REPO_ROOT)), default_timeout=60).run()
    assert not page.exception
    assert not page.text_input and not page.toggle and not page.button
    assert any("not looked up in demo-safe mode" in item.value for item in page.caption)
    assert any("-item audit, one milestone per section" in item.value for item in page.caption)


def test_recent_changes_on_github_are_the_branch_s_newest_pushed_commits():
    pushed = [{"sha": "abc1234def", "commit": {"message": "Fix the importer\n\nDetails.", "committer": {"date": "2026-11-24T10:00:00Z"}}}]
    github = _GitHub(_Answer(pushed))
    found = dashboard.github_commits("o/r", "main", session=github)
    assert found == {"commits": [{"commit": "abc1234", "date": "2026-11-24", "subject": "Fix the importer"}], "error": ""}
    assert github.asked[0][0] == "https://api.github.com/repos/o/r/commits" and github.asked[0][1]["params"]["sha"] == "main"
    assert "did not answer" in dashboard.github_commits("o/r", "main", session=_GitHub(requests.Timeout("slow")))["error"]
