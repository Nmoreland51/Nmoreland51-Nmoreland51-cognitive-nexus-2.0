"""What the project dashboard shows (item 140): milestones, the build, active bugs, the agent's progress,
time estimates and recent changes.

Everything here is read from where it already is: the milestones from the audit ledger in the
repository (docs/backlog: one milestone per section of the 146 items), recent changes from Git,
bugs and test results from the coding agent's project memory, progress and time from its tasks.
The build state is the only thing fetched from outside: GitHub's record of the workflow runs, and
only when asked for.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import requests

from agent.project_memory import ProjectMemory, project_key
from agent.store import AgentStore, Task

OPEN_STATUSES = ("queued", "running", "waiting_approval", "blocked", "review", "escalated")
TROUBLE_STATUSES = ("failed", "escalated", "blocked")
FINISHED_STATUSES = ("review", "done")
_GITHUB_REMOTE = re.compile(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$")
GITHUB_API = "https://api.github.com"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def milestones(root: str | Path) -> dict[str, Any] | None:
    """Progress through the audit's sections, or None for a project without docs/backlog/items.json and status.json."""

    folder = Path(root)
    items_file, status_file = folder / "docs" / "backlog" / "items.json", folder / "docs" / "backlog" / "status.json"
    if not (items_file.exists() and status_file.exists()):
        return None
    listed = json.loads(items_file.read_text(encoding="utf-8"))
    statuses = json.loads(status_file.read_text(encoding="utf-8"))
    rows = []
    for section in listed["sections"]:
        numbers = [number for number, item in listed["items"].items() if item["section"] == section["number"]]
        counted = Counter(str(statuses.get(number, {}).get("status", "MISSING")) for number in numbers)
        applicable = len(numbers) - counted["NOT APPLICABLE"]
        rows.append(
            {
                "number": section["number"],
                "title": section["title"],
                "priority": section["priority"],
                "items": len(numbers),
                "complete": counted["COMPLETE"],
                "partial": counted["PARTIAL"],
                "missing": counted["MISSING"],
                "not_applicable": counted["NOT APPLICABLE"],
                "done": round(counted["COMPLETE"] / applicable, 3) if applicable else 1.0,
            }
        )
    totals = {key: sum(row[key] for row in rows) for key in ("items", "complete", "partial", "missing", "not_applicable")}
    return {"sections": rows, "totals": totals}


def recent_commits(root: str | Path, limit: int = 10) -> list[dict[str, str]]:
    """The newest commits on the current branch: short hash, date and subject. Empty outside a Git repository."""

    try:
        listed = _git(Path(root), "log", f"-{limit}", "--date=short", "--format=%h%x1f%ad%x1f%s")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return []
    rows = []
    for line in listed.splitlines():
        commit, date, subject = (line.split("\x1f") + ["", ""])[:3]
        rows.append({"commit": commit, "date": date, "subject": subject})
    return rows


def current_branch(root: str | Path) -> str:
    try:
        return _git(Path(root), "rev-parse", "--abbrev-ref", "HEAD")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ""


def github_slug(root: str | Path) -> str:
    """owner/repository on GitHub, from the "origin" remote; empty when it is not a GitHub repository."""

    try:
        address = _git(Path(root), "remote", "get-url", "origin")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ""
    match = _GITHUB_REMOTE.search(address)
    return f"{match['owner']}/{match['repo']}" if match else ""


def ci_runs(slug: str, branch: str, *, token: str = "", session: Any = None, limit: int = 5, timeout: float = 10.0) -> dict[str, Any]:
    """The newest workflow runs GitHub has for a branch: {"runs": [...], "error": ""}. Asked for only when the owner asks."""

    if not slug or not branch:
        return {"runs": [], "error": "This project has no GitHub remote, so there is no build on GitHub to show."}
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        answer = (session or requests).get(
            f"{GITHUB_API}/repos/{slug}/actions/runs", params={"branch": branch, "per_page": limit}, headers=headers, timeout=timeout
        )
        answer.raise_for_status()
        listed = answer.json().get("workflow_runs") or []
    except (requests.RequestException, ValueError) as exc:
        return {"runs": [], "error": f"GitHub did not answer: {exc}"}
    runs = [
        {
            "workflow": str(run.get("name") or ""),
            "status": str(run.get("status") or ""),
            "conclusion": str(run.get("conclusion") or ""),
            "commit": str(run.get("head_sha") or "")[:7],
            "started": str(run.get("run_started_at") or run.get("created_at") or "")[:16].replace("T", " "),
            "url": str(run.get("html_url") or ""),
        }
        for run in listed[:limit]
    ]
    return {"runs": runs, "error": "" if runs else f"GitHub has no workflow runs for the branch {branch}."}


def github_commits(slug: str, branch: str, *, token: str = "", session: Any = None, limit: int = 8, timeout: float = 10.0) -> dict[str, Any]:
    """The branch's newest commits as GitHub has them (what was pushed, by anyone): {"commits": [...], "error": ""}."""

    if not slug or not branch:
        return {"commits": [], "error": "This project has no GitHub remote."}
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        answer = (session or requests).get(f"{GITHUB_API}/repos/{slug}/commits", params={"sha": branch, "per_page": limit}, headers=headers, timeout=timeout)
        answer.raise_for_status()
        listed = answer.json()
    except (requests.RequestException, ValueError) as exc:
        return {"commits": [], "error": f"GitHub did not answer: {exc}"}
    commits = [
        {
            "commit": str(item.get("sha") or "")[:7],
            "date": str(((item.get("commit") or {}).get("committer") or {}).get("date") or "")[:10],
            "subject": str((item.get("commit") or {}).get("message") or "").splitlines()[0] if (item.get("commit") or {}).get("message") else "",
        }
        for item in (listed if isinstance(listed, list) else [])[:limit]
    ]
    return {"commits": commits, "error": "" if commits else f"GitHub has no commits for the branch {branch}."}


def _minutes(seconds: Any) -> float:
    return round(float(seconds or 0) / 60, 1)


def agent_progress(store: AgentStore, repo: str = "") -> dict[str, Any]:
    """The coding agent's tasks (for one project, or all): counts by status, the open ones with the time and attempts
    they have used of what they are allowed, and an estimate of how long a task takes, from the tasks already finished."""

    wanted = project_key(repo) if repo else ""
    tasks: list[Task] = [task for task in store.list_tasks() if not wanted or project_key(task.repo) == wanted]
    by_status = Counter(task.status for task in tasks)
    open_rows = [
        {
            "task": task.id,
            "title": task.title,
            "status": task.status,
            "attempts": f"{int(task.spent.get('attempts', 0))} of {task.budget.get('attempts', '?')}",
            "minutes": f"{_minutes(task.spent.get('seconds'))} of {_minutes(task.budget.get('seconds'))}" if task.budget.get("seconds") else f"{_minutes(task.spent.get('seconds'))}",
        }
        for task in tasks
        if task.status in OPEN_STATUSES
    ]
    finished = [float(task.spent.get("seconds") or 0) for task in tasks if task.status in FINISHED_STATUSES and task.spent.get("seconds")]
    estimate = (
        {"minutes_per_task": _minutes(statistics.median(finished)), "from_tasks": len(finished)}
        if finished
        else {"minutes_per_task": None, "from_tasks": 0}
    )
    return {"by_status": dict(by_status), "open": open_rows, "estimate": estimate, "tasks": len(tasks)}


def active_bugs(store: AgentStore, repo: str) -> list[dict[str, str]]:
    """Known bugs the owner wrote down, and the agent's tasks on the project that failed, were handed back or are blocked."""

    rows = [
        {"what": note["text"], "from": "project memory", "since": str(note["created_at"])[:10]}
        for note in ProjectMemory(store).notes(repo, kinds=("bug",))
    ]
    wanted = project_key(repo)
    rows += [
        {"what": f"{task.title} ({task.status})", "from": f"agent task {task.id}", "since": str(task.updated_at)[:10]}
        for task in store.list_tasks()
        if task.status in TROUBLE_STATUSES and project_key(task.repo) == wanted
    ]
    return rows


def last_test_results(store: AgentStore, repo: str) -> list[dict[str, str]]:
    return [{"result": note["text"], "seen": str(note["updated_at"])[:16].replace("T", " ")} for note in ProjectMemory(store).notes(repo, kinds=("test",))]
