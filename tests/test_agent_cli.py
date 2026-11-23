"""The agent from a terminal: the commands a person uses to give work, approve, look and stop."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent import cli
from agent.coder import default_agent
from agent.github import register_github_tools
from agent.jobs import JobQueue
from agent.model import ScriptedModel
from agent.store import AgentStore
from agent.workspace import WorkspaceManager

REPO_ROOT = Path(__file__).resolve().parents[1]
FIX = "Wrong operator.\n\nFILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    for arguments in (["init", "-q", "-b", "main"], ["config", "user.name", "T"], ["config", "user.email", "t@example.org"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *arguments], cwd=folder, check=True)
    (folder / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    (folder / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-A"], cwd=folder, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=folder, check=True)
    return folder


@pytest.fixture
def run(tmp_path, capsys, monkeypatch):
    """Run the command line in this process against a throwaway database, with a scripted model."""

    database = tmp_path / "agent.db"

    def scripted_agent(store, model_name="", settings=None):
        model = ScriptedModel(lambda prompt: "APPROVE" if "reviewing a code change" in prompt else FIX, name="scripted")
        agent = default_agent(store, model, settings=settings or {}, workspaces=WorkspaceManager(tmp_path / "ws"))
        register_github_tools(agent.registry)
        return agent

    monkeypatch.setattr(cli, "build_agent", scripted_agent)

    def go(*arguments):
        code = cli.main(["--db", str(database), *arguments])
        captured = capsys.readouterr()
        return code, captured.out.strip(), captured.err.strip()

    go.database = database
    return go


def test_a_task_is_given_worked_on_looked_at_and_accepted(run, repo):
    code, task_id, _ = run("task", "add", "--repo", str(repo), "--title", "Fix add()", "--description", "It subtracts.", "--test", "python -m pytest -q -p no:cacheprovider test_calc.py", "--attempts", "2", "--time", "10m")
    assert code == 0 and task_id.startswith("task_")
    assert "[queued" in run("task", "list")[1]

    code, shown, _ = run("task", "run", task_id)
    assert code == 0
    for expected in ("[review]  Fix add()", "Ready for review: commit", "acceptance: python -m pytest -q -p no:cacheprovider test_calc.py", "used: 1 attempt(s)", "attempt 1: worked", "waiting for a person to review"):
        assert expected in shown, expected
    assert "+    return a + b" in run("task", "diff", task_id)[1]

    history = run("history", "--task", task_id)[1]
    assert "replace_in_file" in history and "run_tests" in history and "commit_changes" in history and "checked" in history
    assert run("task", "accept", task_id, "--by", "Nora")[1] == "done"
    code, out, err = run("task", "accept", task_id, "--by", "Nora")
    assert code == 2 and "not waiting for review" in err
    code, out, _ = run("task", "cleanup", task_id)
    assert code == 0 and "The branch agent/" in out and "still in" in out
    store = AgentStore(run.database)
    assert store.get_task(task_id).budget == {"attempts": 2, "seconds": 600.0} and store.get_task(task_id).workspace == ""
    store.close()


def test_a_task_without_a_test_is_accepted_with_a_warning(run, repo):
    code, task_id, err = run("task", "add", "--repo", str(repo), "--title", "Tidy up")
    assert code == 0 and "no way to tell when the task is done" in err
    code, shown, _ = run("task", "run", task_id)
    assert code == 1 and "Needs a person: The task has no acceptance tests" in shown and "what you can do: Give the task a command" in shown


def test_changes_can_be_requested_and_a_task_cancelled(run, repo):
    _, task_id, _ = run("task", "add", "--repo", str(repo), "--title", "Fix add()", "--test", "python -m pytest -q -p no:cacheprovider test_calc.py")
    run("task", "run", task_id)
    assert run("task", "changes", task_id, "Use a clearer name.", "--by", "Nora")[1] == "queued"
    assert run("task", "cancel", task_id)[1] == "cancelled"
    code, _, err = run("task", "show", "task_does_not_exist")
    assert code == 2 and "There is no task" in err


def test_approvals_are_listed_and_decided_from_the_terminal(run, repo):
    _, task_id, _ = run("task", "add", "--repo", str(repo), "--title", "Fix add()", "--test", "python -m pytest -q -p no:cacheprovider test_calc.py")
    run("task", "run", task_id)
    code, out, _ = run("task", "publish", task_id)
    assert code == 1 and '"status": "needs_approval"' in out and "python -m agent approve apr_" in out
    listed = run("approvals")[1]
    request = listed.split()[0]
    assert request.startswith("apr_") and "external" in listed and "push the task's branch to origin" in listed
    assert run("deny", request, "--by", "Nora", "--note", "no remote yet")[1].startswith("denied: push the task's branch")
    assert run("approvals")[1] == ""
    code, _, err = run("approve", request, "--by", "Nora")
    assert code == 2 and "already denied" in err


def test_reminders_watches_jobs_and_schedules(run):
    job_id = run("remind", "Call the dentist", "--in", "2h")[1]
    assert job_id.startswith("job_")
    daily = run("remind", "Stand up", "--daily-at", "09:30")[1]
    watch = run("watch", "https://example.org/releases", "--every", "6h", "--phrase", "version 3")[1]
    assert daily.startswith("sch_") and watch.startswith("sch_")
    jobs = run("jobs")[1]
    assert job_id in jobs and "[queued" in jobs and "reminder" in jobs
    schedules = run("schedules")[1]
    assert "daily at 09:30" in schedules and "every 21600 s" in schedules and "Watch https://example.org/releases" in schedules
    assert run("job", "cancel", job_id)[1] == "cancelled"
    assert run("job", "retry", job_id)[1] == "queued"
    run("schedule", "remove", daily)
    assert daily not in run("schedules")[1]
    store = AgentStore(run.database)
    assert JobQueue(store).schedules()[0]["payload"] == {"url": "https://example.org/releases", "phrase": "version 3"}
    store.close()


def test_a_due_reminder_is_delivered_by_the_worker_and_shown_once_as_new(run):
    run("remind", "Water the plants")
    assert run("worker", "--once")[1] == "Ran 1 job(s)."
    first = run("notices")[1]
    assert "new" in first and "Water the plants" in first
    assert "new" not in run("notices")[1]


def test_a_queued_task_is_worked_on_by_the_worker(run, repo):
    _, task_id, _ = run("task", "add", "--repo", str(repo), "--title", "Fix add()", "--test", "python -m pytest -q -p no:cacheprovider test_calc.py")
    job_id = run("queue", task_id)[1]
    assert run("queue", task_id)[1] == job_id  # queuing it twice is one job
    assert run("worker", "--once")[1] == "Ran 1 job(s)."
    assert "[review]" in run("task", "show", task_id)[1] and "[done" in run("jobs")[1]


def test_capabilities_and_isolation_are_printed(run):
    tools = run("tools")[1]
    for expected in ("files   read_file", "shell   run_tests", "git     commit_changes", "github  push_branch", "external", "checks its outcome"):
        assert expected in tools, expected
    report = run("sandbox")[1]
    assert "network" in report and "not blocked by the operating system" in report and "reads" in report


@pytest.mark.parametrize("text, seconds", [("90", 90.0), ("30s", 30.0), ("10m", 600.0), ("2h", 7200.0), ("1d", 86400.0), ("1.5 hours", 5400.0)])
def test_durations(text, seconds):
    assert cli.parse_duration(text) == seconds


def test_a_bad_duration_is_refused():
    with pytest.raises(Exception, match="not a duration"):
        cli.parse_duration("soon")


def test_the_module_can_be_run_as_a_program(tmp_path):
    done = subprocess.run([sys.executable, "-m", "agent", "--db", str(tmp_path / "agent.db"), "sandbox"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "environment" in done.stdout
