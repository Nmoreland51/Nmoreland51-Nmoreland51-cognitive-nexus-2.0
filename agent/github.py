"""Publishing a finished task to GitHub, and reading issues, CI results and releases from it.

Authorization is kept narrow on purpose:

* The token comes from the environment (COGNITIVE_NEXUS_GITHUB_TOKEN or GITHUB_TOKEN). It is never
  stored, never put on a command line, and never reaches the sandbox. A fine-grained token for
  the one repository with "Contents: read and write" and "Pull requests: read and write" is all
  that is needed; nothing here uses more.
* The agent pushes only the task's own branch (agent/...), never with force and never to another
  branch, and opens pull requests as drafts. It does not merge, close, comment, tag or release.
* Pushing and opening a pull request reach outside this machine, so each needs a person's
  approval for that one action (agent/approvals.py), whatever the approval mode.
* Reading (an issue, check runs, the latest release) is a network read and follows the mode.

The pull request says what was changed, the test evidence, how it was reviewed, and how to undo it.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from agent.registry import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from agent.store import Task
from agent.workspace import Workspace, WorkspaceError, WorkspaceManager
from core.reality_grounding.prompt_firewall import defuse_untrusted_text

API = "https://api.github.com"
TOKEN_VARIABLES = ("COGNITIVE_NEXUS_GITHUB_TOKEN", "GITHUB_TOKEN")
_REMOTE = re.compile(r"github\.com[:/]+(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")


class GitHubError(Exception):
    """GitHub refused a request or could not be reached. The message says what to do about it."""


def token_from_environment() -> str:
    for name in TOKEN_VARIABLES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


@dataclass
class GitHub:
    token: str
    api: str = API
    timeout: float = 30.0

    def _request(self, method: str, path: str, **options: Any) -> Any:
        if not self.token:
            raise GitHubError(f"No GitHub token is set. Put a fine-grained token for this repository in {TOKEN_VARIABLES[0]}.")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CognitiveNexus-agent",
        }
        try:
            response = requests.request(method, f"{self.api.rstrip('/')}{path}", headers=headers, timeout=self.timeout, **options)
        except requests.RequestException as exc:
            raise GitHubError(f"GitHub could not be reached: {exc}") from exc
        if response.status_code >= 400:
            try:
                said = response.json().get("message", "")
            except ValueError:
                said = response.text[:200]
            hint = {
                401: " The token was not accepted: it may have expired or been revoked.",
                403: " The token does not allow this. It needs 'Contents: read and write' and 'Pull requests: read and write' on this repository.",
                404: " The repository was not found, or the token cannot see it.",
                422: " GitHub could not process the request as sent.",
            }.get(response.status_code, "")
            raise GitHubError(f"GitHub answered {response.status_code} to {method} {path}: {said}.{hint}")
        return response.json() if response.content else {}

    def whoami(self) -> str:
        return str(self._request("GET", "/user").get("login", ""))

    def repository(self, owner: str, repo: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}")

    def find_pull_request(self, owner: str, repo: str, branch: str) -> dict[str, Any] | None:
        found = self._request("GET", f"/repos/{owner}/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"})
        return found[0] if found else None

    def create_pull_request(self, owner: str, repo: str, *, title: str, body: str, head: str, base: str, draft: bool = True) -> dict[str, Any]:
        return self._request("POST", f"/repos/{owner}/{repo}/pulls", json={"title": title, "body": body, "head": head, "base": base, "draft": draft})

    def pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")

    def check_runs(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        data = self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs")
        runs = data.get("check_runs", [])
        done = [run for run in runs if run.get("status") == "completed"]
        conclusions: dict[str, int] = {}
        for run in done:
            conclusions[str(run.get("conclusion"))] = conclusions.get(str(run.get("conclusion")), 0) + 1
        state = "none" if not runs else "running" if len(done) < len(runs) else "passed" if set(conclusions) <= {"success", "skipped", "neutral"} else "failed"
        return {"state": state, "total": len(runs), "completed": len(done), "conclusions": conclusions, "runs": [{"name": run.get("name"), "status": run.get("status"), "conclusion": run.get("conclusion"), "url": run.get("html_url")} for run in runs]}

    def issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}/issues/{number}")

    def latest_release(self, owner: str, repo: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"/repos/{owner}/{repo}/releases/latest")
        except GitHubError as exc:
            if "answered 404" in str(exc):
                return None
            raise


def repository_slug(manager: WorkspaceManager, checkout: Workspace, remote: str = "origin", override: str = "") -> tuple[str, str]:
    """(owner, repository) on GitHub for a checkout, from a setting or from the remote's address."""

    if override:
        owner, _, name = override.partition("/")
        if owner and name:
            return owner, name
        raise GitHubError(f"{override!r} is not of the form owner/repository.")
    address = manager.git(checkout, ["remote", "get-url", remote], check=False).stdout.strip()
    match = _REMOTE.search(address)
    if not match:
        raise GitHubError(f"The remote {remote!r} ({address or 'not set'}) is not a GitHub repository.")
    return match.group("owner"), match.group("repo")


def pull_request_body(task: Task) -> str:
    """What a reviewer needs: the change, the evidence, the review, and how to undo it."""

    result = task.result or {}
    review = result.get("review") or {}
    lines = [task.description.strip() or task.title, "", "## What changed", "", result.get("summary") or "See the diff.", ""]
    if result.get("diff_stat"):
        lines += ["```", result["diff_stat"], "```", ""]
    lines += ["## Test evidence", ""]
    for run in (result.get("tests") or {}).get("runs", []):
        counted = ", ".join(f"{count} {word}" for word, count in (run.get("counts") or {}).items()) or f"exit code {run.get('exit_code')}"
        lines.append(f"- `{' '.join(run.get('argv', []))}`: {'passed' if run.get('passed') else 'FAILED'} ({counted}) in {run.get('seconds', 0):.1f} s")
    isolation = result.get("isolation") or {}
    lines += [
        "",
        f"The tests were run after the last edit, in a sandbox ({isolation.get('writes', 'see the task record')}).",
        f"They failed before the change and pass after it. It took {result.get('attempts', '?')} attempt(s).",
        "",
        "## Review",
        "",
        "- Automatic checks passed: tests and project configuration untouched, change of reviewable size, no secret added.",
    ]
    verdict = review.get("model_verdict", "not asked")
    who = review.get("reviewer") or "no model"
    same = " (the same model that wrote the change, in a fresh context)" if review.get("same_model_as_author") else ""
    said = {"approve": "approved it", "reject": f"objected: {review.get('model_reasons', '')}", "unclear": "gave no clear verdict", "unavailable": "could not be asked", "not asked": "was not asked"}.get(verdict, verdict)
    lines += [f"- Reviewing model {who}{same} {said}.", "- **A person has not reviewed this yet.** It was written by a program; read the diff before merging.", ""]
    lines += [
        "## Undoing it",
        "",
        "- Before merging: close this pull request and delete the branch.",
        f"- After merging: `git revert {str(result.get('commit', '<merge commit>'))[:12]}` (or revert the merge commit) and push.",
        "",
        f"Task `{task.id}`, branch `{task.branch}`, based on `{str(result.get('base', ''))[:12]}`.",
        "",
        "Generated by the Cognitive Nexus coding agent.",
    ]
    return "\n".join(lines)


# ---- tools -------------------------------------------------------------------------------------


def _checkout(context: ToolContext) -> tuple[WorkspaceManager, Workspace]:
    if context.workspaces is None or context.checkout is None:
        raise ToolError("This tool needs a task workspace, and none is open.")
    return context.workspaces, context.checkout


def _client(context: ToolContext) -> GitHub:
    return GitHub(token=token_from_environment(), api=str(context.settings.get("agent_github_api") or API))


def _slug(context: ToolContext, remote: str = "origin") -> tuple[str, str]:
    manager, checkout = _checkout(context)
    try:
        return repository_slug(manager, checkout, remote, str(context.settings.get("agent_github_repository") or ""))
    except GitHubError as exc:
        raise ToolError(str(exc)) from exc


def _push_environment(address: str) -> dict[str, str]:
    """Git settings that carry the token for one push, passed in the environment and not on the command line."""

    token = token_from_environment()
    if not token or not address.startswith("https://"):
        return {}  # a local or SSH remote, or no token: Git uses whatever access the user already has
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    host = re.match(r"https://[^/]+/", address)
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{host.group(0) if host else 'https://github.com/'}.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}


def push_branch(context: ToolContext, remote: str = "origin") -> ToolResult:
    manager, checkout = _checkout(context)
    if not checkout.branch.startswith("agent/"):
        raise ToolError(f"Only a task's own branch is pushed, and {checkout.branch} is not one.")
    address = manager.git(checkout, ["remote", "get-url", remote], check=False).stdout.strip()
    if not address:
        raise ToolError(f"The repository has no remote named {remote}.")
    try:
        commit = manager.head(checkout)
        # One branch, by its full name on both sides, no force: this cannot move any other branch.
        manager.git(checkout, ["push", remote, f"refs/heads/{checkout.branch}:refs/heads/{checkout.branch}"], env=_push_environment(address))
    except WorkspaceError as exc:
        raise ToolError(f"The push did not succeed: {str(exc).replace(token_from_environment() or chr(0), '***')}") from exc
    return ToolResult(ok=True, output=f"Pushed {checkout.branch} ({commit[:12]}) to {remote}.", data={"commit": commit, "branch": checkout.branch, "remote": remote})


def _push_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    manager, checkout = _checkout(context)
    remote = result.data["remote"]
    address = manager.git(checkout, ["remote", "get-url", remote], check=False).stdout.strip()
    listed = manager.git(checkout, ["ls-remote", remote, f"refs/heads/{checkout.branch}"], env=_push_environment(address), check=False).stdout.split()
    there = bool(listed) and listed[0] == result.data["commit"]
    return there, f"the remote's {checkout.branch} is at the pushed commit" if there else f"the remote's {checkout.branch} is not at the pushed commit"


def open_pull_request(context: ToolContext, title: str = "", base: str = "", draft: bool = True) -> ToolResult:
    _manager, checkout = _checkout(context)
    owner, repo = _slug(context)
    client = _client(context)
    task = context.store.get_task(context.task_id)
    try:
        existing = client.find_pull_request(owner, repo, checkout.branch)
        if existing is None:
            target = base or str(client.repository(owner, repo).get("default_branch") or "main")
            made = client.create_pull_request(owner, repo, title=title or task.title, body=pull_request_body(task), head=checkout.branch, base=target, draft=draft)
        else:
            made = existing
    except GitHubError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        ok=True,
        output=f"{'Found the open' if existing else 'Opened a draft' if made.get('draft') else 'Opened a'} pull request #{made['number']}: {made.get('html_url', '')}",
        data={"number": made["number"], "url": made.get("html_url", ""), "draft": bool(made.get("draft")), "already_existed": existing is not None, "repository": f"{owner}/{repo}"},
        artifacts=[made.get("html_url", "")],
    )


def _pull_request_done(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    manager, checkout = _checkout(context)
    owner, repo = result.data["repository"].split("/", 1)
    seen = _client(context).pull_request(owner, repo, int(result.data["number"]))
    right = seen.get("state") == "open" and (seen.get("head") or {}).get("ref") == checkout.branch and (seen.get("head") or {}).get("sha") == manager.head(checkout)
    return right, "GitHub shows the pull request open at the task's commit" if right else "GitHub does not show an open pull request at the task's commit"


def ci_status(context: ToolContext) -> ToolResult:
    manager, checkout = _checkout(context)
    owner, repo = _slug(context)
    try:
        status = _client(context).check_runs(owner, repo, manager.head(checkout))
    except GitHubError as exc:
        raise ToolError(str(exc)) from exc
    lines = [f"Checks for {manager.head(checkout)[:12]}: {status['state']} ({status['completed']} of {status['total']} finished)"]
    lines += [f"- {run['name']}: {run['conclusion'] or run['status']}" for run in status["runs"][:30]]
    return ToolResult(ok=True, output="\n".join(lines), data=status)


def read_issue(context: ToolContext, number: int) -> ToolResult:
    owner, repo = _slug(context)
    try:
        issue = _client(context).issue(owner, repo, int(number))
    except GitHubError as exc:
        raise ToolError(str(exc)) from exc
    # An issue is text from the internet: anything in it addressed to an AI model is dropped.
    # Always the strict handling, whatever the owner chose for chat: an agent acts on what it reads.
    body, removed = defuse_untrusted_text(str(issue.get("body") or ""), mode="remove_and_fence")
    return ToolResult(
        ok=True,
        output=f"#{issue.get('number')} {issue.get('title', '')} ({issue.get('state', '')})\n\n{body[:6000]}",
        data={"number": issue.get("number"), "title": issue.get("title", ""), "state": issue.get("state", ""), "body": body[:6000], "url": issue.get("html_url", ""), "sentences_removed": removed},
    )


def latest_release(context: ToolContext) -> ToolResult:
    owner, repo = _slug(context)
    try:
        release = _client(context).latest_release(owner, repo)
    except GitHubError as exc:
        raise ToolError(str(exc)) from exc
    if release is None:
        return ToolResult(ok=True, output=f"{owner}/{repo} has no published release.", data={"release": None})
    return ToolResult(
        ok=True,
        output=f"Latest release of {owner}/{repo}: {release.get('tag_name')} ({release.get('name') or 'no title'}), published {str(release.get('published_at', ''))[:10]}",
        data={"tag": release.get("tag_name"), "name": release.get("name"), "published_at": release.get("published_at"), "url": release.get("html_url")},
    )


def register_github_tools(registry: ToolRegistry) -> ToolRegistry:
    def schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}

    text = {"type": "string"}
    registry.register(Tool("push_branch", "Push the task's own branch to the repository's remote. Never forces, never touches another branch.",
                           schema({"remote": text}), "external", push_branch, adapter="github", verify=_push_done,
                           summarize=lambda a: f"push the task's branch to {a.get('remote', 'origin')}"))  # fmt: skip
    registry.register(Tool("open_pull_request", "Open a draft pull request for the task's branch, with the test evidence and how to undo it.",
                           schema({"title": text, "base": text, "draft": {"type": "boolean"}}), "external", open_pull_request, adapter="github",
                           verify=_pull_request_done, summarize=lambda a: "open a pull request for the task's branch"))  # fmt: skip
    registry.register(Tool("ci_status", "Read the CI check results for the task's commit.", schema({}), "network", ci_status, adapter="github", repeatable=True))
    registry.register(Tool("read_issue", "Read an issue of the repository.", schema({"number": {"type": "integer", "minimum": 1}}, ("number",)), "network", read_issue, adapter="github", repeatable=True))
    registry.register(Tool("latest_release", "Read the repository's latest published release.", schema({}), "network", latest_release, adapter="github", repeatable=True))
    return registry


def publish(agent: Any, task_id: str, *, remote: str = "origin") -> dict[str, Any]:
    """Push a reviewed task's branch and open its pull request.

    Returns {"status": "published", "url": ...}, {"status": "needs_approval", "approval": id,
    "summary": ...} (call again once a person has approved), or {"status": "failed", "error": ...}.
    The task stays in "review": opening a pull request does not accept the change.
    """

    from agent.approvals import ApprovalPolicy

    task: Task = agent.store.get_task(task_id)
    if task.status != "review":
        return {"status": "failed", "error": f"Task {task_id} is {task.status}; only a change that passed its tests and review is published."}
    checkout = agent.workspaces.open(task.id, task.repo, task.workspace, task.branch, task.base_ref)
    context = ToolContext(
        store=agent.store,
        policy=ApprovalPolicy.from_settings(agent.settings),
        workspace=checkout.path,
        task_id=task.id,
        settings=dict(agent.settings),
        workspaces=agent.workspaces,
        checkout=checkout,
    )
    commit = str(task.result.get("commit", ""))
    for tool, arguments in (("push_branch", {"remote": remote}), ("open_pull_request", {})):
        if agent.registry.get(tool) is None:
            return {"status": "failed", "error": "The GitHub tools are not registered for this agent."}
        result = agent.registry.call(tool, arguments, context, step=f"publish.{commit[:12]}")
        if result.status == "needs_approval":
            return {"status": "needs_approval", "approval": result.approval_id, "summary": result.error}
        if not result.ok:
            agent.store.add_event(task.id, "publish_failed", f"{tool} failed: {result.error[:300]}")
            return {"status": "failed", "error": result.error}
        if tool == "open_pull_request":
            published = {**task.result, "pull_request": {"url": result.data["url"], "number": result.data["number"], "draft": result.data["draft"]}}
            agent.store.update_task(task.id, result=published)
            agent.store.add_event(task.id, "published", f"Pull request #{result.data['number']} opened: {result.data['url']}", result.data)
            return {"status": "published", "url": result.data["url"], "number": result.data["number"]}
    return {"status": "failed", "error": "Nothing was published."}


__all__ = ["GitHub", "GitHubError", "publish", "pull_request_body", "register_github_tools", "repository_slug", "token_from_environment"]
