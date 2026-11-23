"""A private checkout for each task: a Git worktree on its own branch.

The user's own checkout is never touched. A task gets a new branch (agent/<task>-<title>) checked
out in a separate folder under the app's data folder; the agent edits and runs tests there, and
the result leaves as a commit on that branch. Removing the worktree leaves no trace in the user's
working tree.

Things in a workspace are treated as untrusted, because the agent runs the repository's own code
there (its tests) and code a model wrote:

* Git is always called with the real Git folder and work tree given explicitly, with hooks and
  the file-system monitor off, so nothing written inside the workspace can make the harness's Git
  run a program.
* Every path a tool is given is resolved for real (following links and junctions) and must stay
  inside the workspace.
* A link or junction that leads outside the workspace blocks diff and commit: otherwise a test
  could plant a link to the user's files and have them committed and pushed.
* Checkpoints are kept under refs the task branch does not contain, so restoring one is exact and
  the branch history stays clean.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agent import sandbox
from agent.store import AGENT_DIR

WORKSPACES_DIR = Path(os.environ.get("COGNITIVE_NEXUS_AGENT_WORKSPACES", "").strip() or (AGENT_DIR / "ws"))
PRIVATE_FOLDERS = (sandbox.TEMP_FOLDER, sandbox.HOME_FOLDER)
_GIT_TIMEOUT = 180
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class WorkspaceError(Exception):
    """A request about a workspace that cannot or must not be carried out."""


@dataclass(frozen=True)
class Workspace:
    task_id: str
    repo: Path  # the user's repository the worktree belongs to
    path: Path  # the task's own checkout
    git_dir: Path  # the worktree's Git folder, inside the user's repository and outside the sandbox's reach
    branch: str
    base_commit: str


def _slug(text: str, limit: int = 32) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-") or "task"


def _git_base(hooks_off: Path) -> list[str]:
    return [
        "git",
        "-c", f"core.hooksPath={hooks_off}",
        "-c", "core.fsmonitor=false",
        "-c", "core.pager=cat",
        "-c", "advice.detachedHead=false",
        "-c", "core.autocrlf=false",
        "-c", "core.longpaths=true",
    ]  # fmt: skip


def run_git(arguments: list[str], cwd: Path, *, hooks_off: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Git as the harness runs it: no hooks, no prompts, a time limit."""

    full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", **(env or {})}
    try:
        done = subprocess.run(
            [*_git_base(hooks_off), *arguments], cwd=str(cwd), env=full_env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_GIT_TIMEOUT, creationflags=_NO_WINDOW,
        )  # fmt: skip
    except FileNotFoundError as exc:
        raise WorkspaceError("Git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(f"git {' '.join(arguments[:2])} did not finish in {_GIT_TIMEOUT} seconds.") from exc
    if check and done.returncode != 0:
        raise WorkspaceError(f"git {' '.join(arguments[:3])} failed: {(done.stderr or done.stdout).strip()[:600]}")
    return done


def _is_link(path: Path) -> bool:
    """A symbolic link or, on Windows, a junction or other reparse point."""

    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class WorkspaceManager:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root if root is not None else WORKSPACES_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._hooks_off = self.root / "_no_hooks"
        self._hooks_off.mkdir(exist_ok=True)

    # ---- git ---------------------------------------------------------------------------------

    def _repo_git(self, repo: Path, arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return run_git(arguments, repo, hooks_off=self._hooks_off, check=check)

    def git(self, workspace: Workspace, arguments: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Git for a workspace, pointed at the real Git folder rather than at whatever `.git` says now."""

        return run_git(
            ["--git-dir", str(workspace.git_dir), "--work-tree", str(workspace.path), *arguments],
            workspace.path,
            hooks_off=self._hooks_off,
            env=env,
            check=check,
        )

    # ---- life cycle --------------------------------------------------------------------------

    def create(self, repo: Path | str, task_id: str, title: str = "", base_ref: str = "HEAD") -> Workspace:
        repo = Path(repo).resolve()
        if not repo.is_dir():
            raise WorkspaceError(f"{repo} is not a folder.")
        top = self._repo_git(repo, ["rev-parse", "--show-toplevel"], check=False)
        if top.returncode != 0:
            raise WorkspaceError(f"{repo} is not a Git repository.")
        repo = Path(top.stdout.strip()).resolve()
        resolved = self._repo_git(repo, ["rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"], check=False)
        if resolved.returncode != 0:
            raise WorkspaceError(f"{base_ref!r} is not a commit in {repo}.")
        base_commit = resolved.stdout.strip()
        short = task_id.split("_")[-1]
        path = self.root / short
        if path.exists():
            raise WorkspaceError(f"A workspace for {task_id} already exists at {path}.")
        branch = f"agent/{short}-{_slug(title)}"
        if self._repo_git(repo, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0:
            raise WorkspaceError(f"The branch {branch} already exists.")
        self._repo_git(repo, ["worktree", "add", "-b", branch, str(path), base_commit])
        git_dir = Path(run_git(["rev-parse", "--absolute-git-dir"], path, hooks_off=self._hooks_off).stdout.strip()).resolve()
        workspace = Workspace(task_id=task_id, repo=repo, path=path.resolve(), git_dir=git_dir, branch=branch, base_commit=base_commit)
        # The sandbox's home and temp folders live in the workspace and must never be committed.
        exclude = Path(self.git(workspace, ["rev-parse", "--git-path", "info/exclude"]).stdout.strip())
        exclude = exclude if exclude.is_absolute() else (workspace.path / exclude)
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"/{name}/\n" for name in PRIVATE_FOLDERS))
        sandbox.prepare_workspace(workspace.path)
        return workspace

    def open(self, task_id: str, repo: Path | str, path: Path | str, branch: str, base_commit: str) -> Workspace:
        """The workspace of an existing task, checked to still be what the record says it is."""

        repo, path = Path(repo).resolve(), Path(path).resolve()
        if not path.is_dir():
            raise WorkspaceError(f"The workspace {path} no longer exists.")
        if path != self.root and self.root not in path.parents:
            raise WorkspaceError(f"{path} is not one of this app's workspaces.")
        listed = self._repo_git(repo, ["worktree", "list", "--porcelain"]).stdout
        if not any(Path(line[9:].strip()).resolve() == path for line in listed.splitlines() if line.startswith("worktree ")):
            raise WorkspaceError(f"{path} is not a worktree of {repo}.")
        git_dir = (repo / ".git" / "worktrees" / path.name).resolve()
        if not git_dir.is_dir():
            raise WorkspaceError(f"The Git folder of the workspace {path} is missing.")
        return Workspace(task_id=task_id, repo=repo, path=path, git_dir=git_dir, branch=branch, base_commit=base_commit)

    def remove(self, workspace: Workspace, *, delete_branch: bool = False) -> None:
        """Delete the task's checkout. The branch (and any commits on it) stays unless asked otherwise."""

        self._repo_git(workspace.repo, ["worktree", "remove", "--force", str(workspace.path)], check=False)
        if workspace.path.exists():
            shutil.rmtree(workspace.path, ignore_errors=True)
        self._repo_git(workspace.repo, ["worktree", "prune"], check=False)
        if delete_branch:
            self._repo_git(workspace.repo, ["branch", "-D", workspace.branch], check=False)

    # ---- paths -------------------------------------------------------------------------------

    def resolve(self, workspace: Workspace, relative: str, *, must_exist: bool = False) -> Path:
        """The real location of a path given by a model or a tool caller, or WorkspaceError.

        Refuses absolute paths, anything that leaves the workspace (also through a link or
        junction), Git's own files and the sandbox's private folders.
        """

        text = str(relative or "").strip().replace("\\", "/")
        if not text or text in {".", "./"}:
            raise WorkspaceError("A file path is needed.")
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or text.startswith("~"):
            raise WorkspaceError(f"{relative!r} is not a path inside the workspace. Give a path relative to the repository root.")
        parts = [part for part in text.split("/") if part not in ("", ".")]
        if ".." in parts:
            raise WorkspaceError(f"{relative!r} leaves the workspace.")
        if parts[0].lower() == ".git" or parts[0] in PRIVATE_FOLDERS:
            raise WorkspaceError(f"{relative!r} is not part of the project's files.")
        root = Path(os.path.realpath(workspace.path))
        real = Path(os.path.realpath(root.joinpath(*parts)))
        if real != root and root not in real.parents:
            raise WorkspaceError(f"{relative!r} leads outside the workspace.")
        if must_exist and not real.exists():
            raise WorkspaceError(f"{relative!r} does not exist.")
        return real

    def relative(self, workspace: Workspace, path: Path) -> str:
        return Path(os.path.realpath(path)).relative_to(Path(os.path.realpath(workspace.path))).as_posix()

    def links_leading_outside(self, workspace: Workspace) -> list[str]:
        """Links and junctions in the workspace whose target is not inside it."""

        root = Path(os.path.realpath(workspace.path))
        found: list[str] = []
        for folder, folders, files in os.walk(root):
            here = Path(folder)
            if here == root:
                folders[:] = [name for name in folders if name != ".git"]
            for name in list(folders) + files:
                item = here / name
                if not _is_link(item):
                    continue
                if name in folders:
                    folders.remove(name)  # never walk through a link
                target = Path(os.path.realpath(item))
                if target != root and root not in target.parents:
                    found.append(item.relative_to(root).as_posix())
        return sorted(found)

    def _refuse_outside_links(self, workspace: Workspace) -> None:
        links = self.links_leading_outside(workspace)
        if links:
            raise WorkspaceError(
                "The workspace contains links that lead outside it, so its contents cannot be trusted: "
                + ", ".join(links[:8])
                + ". Remove them before going on."
            )

    # ---- contents ----------------------------------------------------------------------------

    def _tree_of_working_files(self, workspace: Workspace) -> str:
        """A Git tree object holding the working files as they are now, without touching the real index."""

        self._refuse_outside_links(workspace)
        with tempfile.TemporaryDirectory(dir=str(self.root)) as scratch:
            env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
            self.git(workspace, ["read-tree", "HEAD"], env=env)
            self.git(workspace, ["add", "-A", "--", "."], env=env)
            return self.git(workspace, ["write-tree"], env=env).stdout.strip()

    def checkpoint(self, workspace: Workspace, label: str) -> str:
        """Record the working files exactly as they are. Returns an id to give to restore()."""

        tree = self._tree_of_working_files(workspace)
        commit = self.git(
            workspace,
            ["-c", "user.name=Cognitive Nexus agent", "-c", "user.email=agent@localhost", "commit-tree", tree, "-p", "HEAD", "-m", f"checkpoint: {label}"],
        ).stdout.strip()
        number = len(self.checkpoints(workspace)) + 1
        self.git(workspace, ["update-ref", f"refs/agent/{workspace.path.name}/{number:04d}", commit])
        return commit

    def checkpoints(self, workspace: Workspace) -> list[dict[str, str]]:
        listed = self.git(workspace, ["for-each-ref", "--format=%(refname) %(objectname) %(subject)", f"refs/agent/{workspace.path.name}/"]).stdout
        return [dict(zip(("ref", "commit", "label"), line.split(" ", 2))) for line in listed.splitlines() if line.strip()]

    def restore(self, workspace: Workspace, checkpoint: str) -> None:
        """Put every file back to what it was at a checkpoint: edits undone, added files gone, deleted files back."""

        if self.git(workspace, ["cat-file", "-e", f"{checkpoint}^{{commit}}"], check=False).returncode != 0:
            raise WorkspaceError(f"{checkpoint} is not a checkpoint of this workspace.")
        self._refuse_outside_links(workspace)
        self.git(workspace, ["add", "-A", "--", "."])  # so that files added since are known and get removed
        self.git(workspace, ["read-tree", "-u", "--reset", checkpoint])
        self.git(workspace, ["reset", "-q"])  # leave nothing staged; the files stay as restored

    def changed_files(self, workspace: Workspace) -> list[str]:
        """Files that differ from the task's starting point, including new and deleted ones."""

        tree = self._tree_of_working_files(workspace)
        listed = self.git(workspace, ["diff", "--name-only", "-z", workspace.base_commit, tree]).stdout
        return sorted(name for name in listed.split("\0") if name)

    def diff(self, workspace: Workspace, since: str | None = None) -> str:
        """Everything the task changed, as a unified diff against its starting point (or a checkpoint)."""

        tree = self._tree_of_working_files(workspace)
        return self.git(workspace, ["diff", "--no-color", "--no-ext-diff", since or workspace.base_commit, tree]).stdout

    def diff_stat(self, workspace: Workspace) -> str:
        tree = self._tree_of_working_files(workspace)
        return self.git(workspace, ["diff", "--stat", "--no-color", workspace.base_commit, tree]).stdout.strip()

    def commit(self, workspace: Workspace, message: str) -> str:
        """Commit the working files to the task branch. Returns the new commit, or "" if nothing changed."""

        self._refuse_outside_links(workspace)
        self.git(workspace, ["add", "-A", "--", "."])
        if self.git(workspace, ["diff", "--cached", "--quiet"], check=False).returncode == 0:
            return ""
        identity: list[str] = []
        if self.git(workspace, ["config", "user.email"], check=False).returncode != 0:
            identity = ["-c", "user.name=Cognitive Nexus agent", "-c", "user.email=agent@localhost"]
        self.git(workspace, [*identity, "commit", "-q", "-m", message])
        commit = self.git(workspace, ["rev-parse", "HEAD"]).stdout.strip()
        if self.git(workspace, ["status", "--porcelain"]).stdout.strip():
            raise WorkspaceError("Files were still uncommitted after the commit.")
        return commit

    def head(self, workspace: Workspace) -> str:
        return self.git(workspace, ["rev-parse", "HEAD"]).stdout.strip()
