"""Task workspaces are real Git worktrees: these tests create repositories and run Git."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent import sandbox
from agent.workspace import WorkspaceError, WorkspaceManager

WINDOWS = os.name == "nt"


def git(repo, *arguments):
    done = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.name", "Test User")
    git(folder, "config", "user.email", "test@example.org")
    git(folder, "config", "commit.gpgsign", "false")
    (folder / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (folder / "notes").mkdir()
    (folder / "notes" / "todo.txt").write_text("fix add\n", encoding="utf-8")
    (folder / "old.txt").write_text("to be deleted\n", encoding="utf-8")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return folder


@pytest.fixture
def manager(tmp_path):
    return WorkspaceManager(tmp_path / "ws")


def make_link(link: Path, target: Path) -> None:
    """A junction on Windows (needs no privilege), a symbolic link elsewhere."""

    if WINDOWS:
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr + done.stdout
    else:
        os.symlink(target, link, target_is_directory=target.is_dir())


# ---- creating ---------------------------------------------------------------------------------------


def test_a_task_gets_its_own_branch_and_folder_and_the_user_s_checkout_is_untouched(repo, manager):
    head_before = git(repo, "rev-parse", "HEAD")
    workspace = manager.create(repo, "task_ab12cd34ef56", "Fix the add() function!")
    assert workspace.branch == "agent/ab12cd34ef56-fix-the-add-function"
    assert workspace.path == (manager.root / "ab12cd34ef56").resolve() and workspace.base_commit == head_before
    assert (workspace.path / "calc.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
    # The user's checkout: same branch, same commit, nothing changed.
    assert git(repo, "branch", "--show-current") == "main"
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert git(repo, "status", "--porcelain") == ""
    assert workspace.branch in git(repo, "branch", "--list", "agent/*")
    # The sandbox's own folders exist and Git does not see them.
    assert (workspace.path / sandbox.TEMP_FOLDER).is_dir() and (workspace.path / sandbox.HOME_FOLDER).is_dir()
    assert manager.git(workspace, ["status", "--porcelain"]).stdout.strip() == ""
    assert workspace.git_dir.is_dir() and repo in workspace.git_dir.parents


def test_creation_refuses_what_it_cannot_do_safely(repo, manager, tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    with pytest.raises(WorkspaceError, match="not a Git repository"):
        manager.create(plain, "task_000000000001")
    with pytest.raises(WorkspaceError, match="not a commit"):
        manager.create(repo, "task_000000000002", base_ref="no-such-branch")
    manager.create(repo, "task_000000000003", "one")
    with pytest.raises(WorkspaceError, match="already exists"):
        manager.create(repo, "task_000000000003", "one")


def test_a_workspace_can_start_from_another_commit(repo, manager):
    first = git(repo, "rev-parse", "HEAD")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "second")
    workspace = manager.create(repo, "task_00000000aaaa", "from first", base_ref=first)
    assert "a - b" in (workspace.path / "calc.py").read_text(encoding="utf-8")
    assert workspace.base_commit == first


# ---- paths --------------------------------------------------------------------------------------------


def test_paths_must_stay_inside_the_workspace(repo, manager, tmp_path):
    workspace = manager.create(repo, "task_00000000bbbb")
    assert manager.resolve(workspace, "calc.py") == (workspace.path / "calc.py").resolve()
    assert manager.resolve(workspace, "notes\\todo.txt", must_exist=True).name == "todo.txt"
    assert manager.resolve(workspace, "./new/deep/file.py").parent.name == "deep"
    assert manager.relative(workspace, workspace.path / "notes" / "todo.txt") == "notes/todo.txt"
    outside = tmp_path / "secret.txt"
    outside.write_text("private")
    for bad in ("../secret.txt", "notes/../../secret.txt", str(outside), "/etc/passwd", "C:\\Windows\\win.ini", "~/secret", ".git/config", ".GIT/hooks/x", f"{sandbox.HOME_FOLDER}/x", "", "."):
        with pytest.raises(WorkspaceError):
            manager.resolve(workspace, bad)
    with pytest.raises(WorkspaceError, match="does not exist"):
        manager.resolve(workspace, "missing.py", must_exist=True)


def test_a_link_out_of_the_workspace_cannot_be_used_to_reach_outside(repo, manager, tmp_path):
    workspace = manager.create(repo, "task_00000000cccc")
    private = tmp_path / "private"
    private.mkdir()
    (private / "id_rsa").write_text("PRIVATE KEY")
    make_link(workspace.path / "innocent", private)

    with pytest.raises(WorkspaceError, match="outside the workspace"):
        manager.resolve(workspace, "innocent/id_rsa")
    assert manager.links_leading_outside(workspace) == ["innocent"]
    for action in (lambda: manager.diff(workspace), lambda: manager.changed_files(workspace), lambda: manager.commit(workspace, "leak"), lambda: manager.checkpoint(workspace, "x")):
        with pytest.raises(WorkspaceError, match="links that lead outside"):
            action()
    assert "PRIVATE KEY" not in git(repo, "log", "--all", "-p")
    # Once the link is gone, work continues.
    if WINDOWS:
        os.rmdir(workspace.path / "innocent")
    else:
        os.unlink(workspace.path / "innocent")
    assert manager.links_leading_outside(workspace) == []
    assert manager.diff(workspace) == ""


def test_a_link_that_stays_inside_the_workspace_is_fine(repo, manager):
    workspace = manager.create(repo, "task_00000000dddd")
    make_link(workspace.path / "shortcut", workspace.path / "notes")
    assert manager.links_leading_outside(workspace) == []
    assert manager.resolve(workspace, "shortcut/todo.txt") == (workspace.path / "notes" / "todo.txt").resolve()


# ---- checkpoints, diffs, commits -----------------------------------------------------------------


def _edit_everything(workspace):
    (workspace.path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace.path / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (workspace.path / "pkg").mkdir()
    (workspace.path / "pkg" / "deep.py").write_text("X = 2\n", encoding="utf-8")
    (workspace.path / "old.txt").unlink()


def _snapshot(workspace):
    return {
        path.relative_to(workspace.path).as_posix(): path.read_bytes()
        for path in sorted(workspace.path.rglob("*"))
        if path.is_file() and ".git" not in path.parts and sandbox.TEMP_FOLDER not in path.parts and sandbox.HOME_FOLDER not in path.parts
    }


def test_restoring_a_checkpoint_puts_every_file_back(repo, manager):
    workspace = manager.create(repo, "task_00000000eeee")
    original = _snapshot(workspace)
    head = manager.head(workspace)
    start = manager.checkpoint(workspace, "before the attempt")

    _edit_everything(workspace)
    edited = _snapshot(workspace)
    assert edited != original
    middle = manager.checkpoint(workspace, "after the attempt")

    manager.restore(workspace, start)
    assert _snapshot(workspace) == original  # edit undone, added files and folder gone, deleted file back
    assert not (workspace.path / "pkg").exists() or not any((workspace.path / "pkg").iterdir())
    manager.restore(workspace, middle)
    assert _snapshot(workspace) == edited
    manager.restore(workspace, start)
    assert _snapshot(workspace) == original

    # Checkpoints are not on the branch, and restoring leaves nothing staged.
    assert manager.head(workspace) == head
    assert manager.git(workspace, ["diff", "--cached", "--name-only"]).stdout.strip() == ""
    assert [item["label"] for item in manager.checkpoints(workspace)] == ["checkpoint: before the attempt", "checkpoint: after the attempt"]
    with pytest.raises(WorkspaceError, match="not a checkpoint"):
        manager.restore(workspace, "0" * 40)


def test_the_diff_covers_edits_new_files_and_deletions_without_staging_anything(repo, manager):
    workspace = manager.create(repo, "task_00000000ffff")
    assert manager.diff(workspace) == "" and manager.changed_files(workspace) == []
    _edit_everything(workspace)
    assert manager.changed_files(workspace) == ["calc.py", "new_module.py", "old.txt", "pkg/deep.py"]
    diff = manager.diff(workspace)
    assert "-    return a - b" in diff and "+    return a + b" in diff
    assert "+VALUE = 1" in diff and "deleted file mode" in diff and "+X = 2" in diff
    assert sandbox.TEMP_FOLDER not in diff and sandbox.HOME_FOLDER not in diff
    assert "4 files changed" in manager.diff_stat(workspace)
    # The real index was not touched: Git still reports the new file as untracked.
    assert "?? new_module.py" in manager.git(workspace, ["status", "--porcelain"]).stdout
    # A diff since a checkpoint shows only what came after it.
    checkpoint = manager.checkpoint(workspace, "first attempt")
    (workspace.path / "new_module.py").write_text("VALUE = 2\n", encoding="utf-8")
    later = manager.diff(workspace, since=checkpoint)
    assert "-VALUE = 1" in later and "+VALUE = 2" in later and "return a + b" not in later


def test_a_commit_lands_on_the_task_branch_only(repo, manager):
    workspace = manager.create(repo, "task_0000000a0001", "fix add")
    main_head = git(repo, "rev-parse", "main")
    assert manager.commit(workspace, "nothing to commit") == ""
    _edit_everything(workspace)
    (workspace.path / sandbox.TEMP_FOLDER / "scratch.bin").write_bytes(b"x")
    commit = manager.commit(workspace, "Fix add()\n\nIt subtracted.")
    assert commit == git(repo, "rev-parse", workspace.branch) != main_head
    assert git(repo, "rev-parse", "main") == main_head and git(repo, "status", "--porcelain") == ""
    assert sorted(git(repo, "show", "--name-only", "--format=", commit).splitlines()) == ["calc.py", "new_module.py", "old.txt", "pkg/deep.py"]
    assert git(repo, "log", "-1", "--format=%an <%ae>|%s", commit) == "Test User <test@example.org>|Fix add()"
    assert manager.diff(workspace) != ""  # still differs from where the task started
    assert manager.git(workspace, ["status", "--porcelain"]).stdout.strip() == ""


def test_a_repository_without_an_identity_still_gets_a_commit(tmp_path, manager, monkeypatch):
    folder = tmp_path / "anonymous"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    (folder / "a.txt").write_text("a\n")
    git(folder, "add", "-A")
    git(folder, "-c", "user.name=Seed", "-c", "user.email=seed@example.org", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "seed")
    git(folder, "config", "commit.gpgsign", "false")
    home = tmp_path / "empty_home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "none"))
    workspace = manager.create(folder, "task_0000000a0002")
    (workspace.path / "a.txt").write_text("b\n")
    commit = manager.commit(workspace, "change a")
    assert git(folder, "log", "-1", "--format=%an <%ae>", commit) == "Cognitive Nexus agent <agent@localhost>"


# ---- Git is not a way to run code ----------------------------------------------------------------


def test_repository_hooks_do_not_run(repo, manager, tmp_path):
    marker = tmp_path / "hook_ran.txt"
    for name in ("post-checkout", "pre-commit", "post-commit", "prepare-commit-msg"):
        hook = repo / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\necho {name} >> '{marker.as_posix()}'\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)
    workspace = manager.create(repo, "task_0000000a0003")
    (workspace.path / "calc.py").write_text("changed\n")
    manager.checkpoint(workspace, "c")
    assert manager.commit(workspace, "with hooks present")
    assert not marker.exists()


def test_rewriting_the_workspace_s_git_pointer_does_not_redirect_the_harness(repo, manager, tmp_path):
    """A program run in the workspace can write its `.git` file; the harness must not follow it."""

    workspace = manager.create(repo, "task_0000000a0004")
    marker = tmp_path / "evil_ran.txt"
    evil = workspace.path / "evil_git"
    git(tmp_path, "init", "-q", "--bare", str(evil))
    (evil / "config").write_text(
        f"[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tfsmonitor = \"echo ran > '{marker.as_posix()}'; false\"\n", encoding="utf-8"
    )
    pointer = workspace.path / ".git"
    original = pointer.read_text(encoding="utf-8")
    pointer.unlink()  # Git marks it hidden on Windows; a program would replace it the same way
    pointer.write_text(f"gitdir: {evil.as_posix()}\n", encoding="utf-8")
    (workspace.path / "calc.py").write_text("changed\n")

    assert "calc.py" in manager.changed_files(workspace)
    assert "-def add" in manager.diff(workspace)
    assert not marker.exists()
    # Commits still go to the real repository's task branch.
    pointer.write_text(original, encoding="utf-8")
    shutil.rmtree(evil)
    commit = manager.commit(workspace, "real commit")
    assert commit == git(repo, "rev-parse", workspace.branch)
    assert not marker.exists()


# ---- reopening and removing -----------------------------------------------------------------------


def test_an_existing_workspace_is_reopened_only_if_it_is_what_the_record_says(repo, manager, tmp_path):
    workspace = manager.create(repo, "task_0000000a0005")
    again = manager.open(workspace.task_id, repo, workspace.path, workspace.branch, workspace.base_commit)
    assert again == workspace
    with pytest.raises(WorkspaceError, match="no longer exists"):
        manager.open("t", repo, manager.root / "gone", "b", "c")
    with pytest.raises(WorkspaceError, match="not one of this app's workspaces"):
        manager.open("t", repo, tmp_path, "b", "c")
    stray = manager.root / "stray"
    stray.mkdir()
    with pytest.raises(WorkspaceError, match="not a worktree"):
        manager.open("t", repo, stray, "b", "c")


def test_removing_a_workspace_keeps_the_branch_unless_told_otherwise(repo, manager):
    workspace = manager.create(repo, "task_0000000a0006", "keep")
    (workspace.path / "calc.py").write_text("changed\n")
    commit = manager.commit(workspace, "work to keep")
    manager.remove(workspace)
    assert not workspace.path.exists()
    assert git(repo, "rev-parse", workspace.branch) == commit
    assert str(workspace.path) not in git(repo, "worktree", "list")

    other = manager.create(repo, "task_0000000a0007", "discard")
    manager.remove(other, delete_branch=True)
    assert other.branch not in git(repo, "branch", "--list", "agent/*")
    assert git(repo, "status", "--porcelain") == ""
