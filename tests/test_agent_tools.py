"""The coding tools on a real repository, through the registry, with commands run in the sandbox."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent import sandbox
from agent.approvals import ApprovalPolicy
from agent.registry import ToolContext, ToolRegistry
from agent.store import AgentStore
from agent.tools import parse_test_output, register_coding_tools
from agent.workspace import WorkspaceManager

WINDOWS = os.name == "nt"
BUGGY = "def add(a, b):\n    return a - b\n\n\ndef double(value):\n    return add(value, value)\n"
TESTS = "from calc import add, double\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_double():\n    assert double(4) == 8\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n"


def git(repo, *arguments):
    done = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Test User"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        git(repo, "config", key, value)
    (repo / "calc.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text(TESTS, encoding="utf-8", newline="\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# Guide\n\nUse add(a, b) to add numbers.\n", encoding="utf-8", newline="\n")
    (repo / "logo.bin").write_bytes(b"\x89PNG\0\0binary add(")
    (repo / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    store = AgentStore(tmp_path / "agent.db")
    manager = WorkspaceManager(tmp_path / "ws")
    checkout = manager.create(repo, "task_0000000b0001", "fix add")
    context = ToolContext(
        store=store,
        policy=ApprovalPolicy("workspace"),
        workspace=checkout.path,
        task_id="task_0000000b0001",
        workspaces=manager,
        checkout=checkout,
        settings={"acceptance": [["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]]},
    )
    registry = register_coding_tools(ToolRegistry())
    yield type("Env", (), {"repo": repo, "store": store, "manager": manager, "checkout": checkout, "context": context, "registry": registry, "tmp": tmp_path})
    store.close()


def call(env, name, step="", **arguments):
    return env.registry.call(name, arguments, env.context, step=step)


# ---- reading ---------------------------------------------------------------------------------------


def test_listing_shows_project_files_and_not_ignored_or_private_ones(env):
    (env.checkout.path / "new.py").write_text("x = 1\n")
    (env.checkout.path / "build").mkdir()
    (env.checkout.path / "build" / "out.txt").write_text("ignored")
    (env.checkout.path / "debug.log").write_text("ignored")
    (env.checkout.path / sandbox.TEMP_FOLDER / "scratch.txt").write_text("private")
    listed = call(env, "list_files")
    assert listed.ok and listed.data["files"] == [".gitignore", "calc.py", "docs/guide.md", "logo.bin", "new.py", "test_calc.py"]
    assert call(env, "list_files", pattern="*.py").data["files"] == ["calc.py", "new.py", "test_calc.py"]
    assert call(env, "list_files", folder="docs").data["files"] == ["docs/guide.md"]
    limited = call(env, "list_files", limit=2)
    assert len(limited.data["files"]) == 2 and "and 4 more" in limited.output
    assert not call(env, "list_files", folder="../outside").ok


def test_reading_is_numbered_bounded_and_confined(env):
    read = call(env, "read_file", path="calc.py")
    assert read.ok and "1  def add(a, b):" in read.output and "[lines 1-6 of 6]" in read.output
    (env.checkout.path / "long.txt").write_text("\n".join(f"line {number}" for number in range(1, 1001)))
    part = call(env, "read_file", path="long.txt", start_line=500, max_lines=3)
    assert part.output.splitlines()[:3] == ["500  line 500", "501  line 501", "502  line 502"]
    assert "read on with start_line=503" in part.output
    assert call(env, "read_file", path="long.txt", max_lines=9999).status == "invalid"  # over the schema's maximum
    (env.checkout.path / "wide.txt").write_text("x" * 5000)
    assert "[line cut]" in call(env, "read_file", path="wide.txt").output
    for path, complaint in (("logo.bin", "not a text file"), ("docs", "is a folder"), ("missing.py", "does not exist"), ("../secret", "leaves the workspace"), (".git/config", "not part of the project"), ("C:/Windows/win.ini", "not a path inside")):
        refused = call(env, "read_file", path=path)
        assert not refused.ok and complaint in refused.error, path
    (env.checkout.path / "huge.txt").write_bytes(b"a" * 2_100_000)
    assert "larger than 2 MB" in call(env, "read_file", path="huge.txt").error


def test_search_finds_text_and_patterns_with_file_and_line(env):
    found = call(env, "search_text", query="add(")
    assert found.ok and found.data == {"matches": 6, "files": 3}
    assert "calc.py:1: def add(a, b):" in found.output and "docs/guide.md:3: Use add(a, b) to add numbers." in found.output
    assert "logo.bin" not in found.output  # binary files are skipped
    by_pattern = call(env, "search_text", query=r"^def \w+", regex=True, folder=".")
    assert sorted(line.split(":")[0] for line in by_pattern.output.splitlines()) == ["calc.py", "calc.py", "test_calc.py", "test_calc.py", "test_calc.py"]
    assert "1 more matches not shown" in call(env, "search_text", query="def ", max_results=4).output
    assert "No match" in call(env, "search_text", query="no such text anywhere").output
    assert "not a valid regular expression" in call(env, "search_text", query="(", regex=True).error


# ---- changing ----------------------------------------------------------------------------------------


def test_writing_a_file_returns_a_diff_and_a_way_back(env):
    made = call(env, "write_file", path="pkg/util.py", content="VALUE = 1\n")
    assert made.ok and made.verified and made.data["created"] and made.artifacts == ["pkg/util.py"]
    assert "+VALUE = 1" in made.output and "Undo with restore_checkpoint" in made.output
    changed = call(env, "write_file", path="pkg/util.py", content="VALUE = 2\n", step="2")
    assert "-VALUE = 1" in changed.output and "+VALUE = 2" in changed.output
    same = call(env, "write_file", path="pkg/util.py", content="VALUE = 2\n", step="3")
    assert same.ok and same.data == {"changed": False}
    # Undo the second write, then the first.
    assert call(env, "restore_checkpoint", checkpoint=changed.data["checkpoint"][:12]).verified
    assert (env.checkout.path / "pkg" / "util.py").read_text() == "VALUE = 1\n"
    assert call(env, "restore_checkpoint", checkpoint=made.data["checkpoint"]).ok
    assert not (env.checkout.path / "pkg" / "util.py").exists()
    for path in ("../escape.py", ".git/hooks/pre-commit", f"{sandbox.HOME_FOLDER}/x.py"):
        assert not call(env, "write_file", path=path, content="x").ok
    assert not (env.tmp / "escape.py").exists()


def test_replacing_text_needs_an_exact_unique_match(env):
    fixed = call(env, "replace_in_file", path="calc.py", old="    return a - b\n", new="    return a + b\n")
    assert fixed.ok and fixed.verified and "-    return a - b" in fixed.output and "+    return a + b" in fixed.output
    assert "return a + b" in (env.checkout.path / "calc.py").read_text()

    missing = call(env, "replace_in_file", path="calc.py", old="    return a-b\n", new="x", step="2")
    assert not missing.ok and "was not found" in missing.error and "The closest line in the file is: 'return a + b'" in missing.error
    twice = call(env, "replace_in_file", path="calc.py", old="return", new="yield", step="3")
    assert not twice.ok and "occurs 2 times" in twice.error
    assert call(env, "replace_in_file", path="calc.py", old="return", new="yield", count=2, step="4").ok
    assert "same" in call(env, "replace_in_file", path="calc.py", old="yield", new="yield", step="5").error
    assert call(env, "replace_in_file", path="nope.py", old="a", new="b").error.endswith("does not exist.")


def test_a_patch_is_applied_whole_or_not_at_all(env):
    patch = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,4 +1,4 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n \n \n"
        "--- /dev/null\n+++ b/CHANGES.md\n@@ -0,0 +1 @@\n+Fixed add.\n"
    )
    applied = call(env, "apply_patch", patch=patch)
    assert applied.ok and applied.verified, applied.error
    assert "return a + b" in (env.checkout.path / "calc.py").read_text() and (env.checkout.path / "CHANGES.md").read_text() == "Fixed add.\n"

    before = (env.checkout.path / "calc.py").read_text()
    stale = call(env, "apply_patch", patch=patch, step="2")  # the same patch no longer applies
    assert not stale.ok and "does not apply to the current files" in stale.error
    assert (env.checkout.path / "calc.py").read_text() == before
    # Git anchors a change with nothing after it to the end of the file, so this one cannot apply.
    no_context_after = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return a * b\n"
    sloppy = call(env, "apply_patch", patch=no_context_after, step="3")
    assert not sloppy.ok and "unchanged lines before and after" in sloppy.error
    outside = call(env, "apply_patch", patch="--- /dev/null\n+++ b/../../evil.txt\n@@ -0,0 +1 @@\n+x\n")
    assert not outside.ok and "leaves the workspace" in outside.error
    assert call(env, "restore_checkpoint", checkpoint=applied.data["checkpoint"]).ok
    assert "return a - b" in (env.checkout.path / "calc.py").read_text() and not (env.checkout.path / "CHANGES.md").exists()


def test_a_deleted_file_can_be_brought_back(env):
    gone = call(env, "delete_file", path="docs/guide.md")
    assert gone.ok and gone.verified and not (env.checkout.path / "docs" / "guide.md").exists()
    assert "docs/guide.md" in call(env, "show_diff").data["files"]
    assert len(call(env, "list_checkpoints").data["checkpoints"]) == 1
    assert call(env, "restore_checkpoint", checkpoint=gone.data["checkpoint"]).ok
    assert (env.checkout.path / "docs" / "guide.md").exists()
    assert "not one of this task's checkpoints" in call(env, "restore_checkpoint", checkpoint="deadbeef1234").error
    assert "is a folder" in call(env, "delete_file", path="docs").error


# ---- running -------------------------------------------------------------------------------------------


def test_commands_run_in_the_sandbox_without_a_shell(env):
    ran = call(env, "run_command", argv=["python", "-c", "import calc; print(calc.add(5, 3))"])
    assert ran.ok and "exit code 0" in ran.output and ran.output.strip().endswith("2")
    assert ran.data["isolation"]["writes_confined"] is WINDOWS
    failed = call(env, "run_command", argv=["python", "-c", "import sys; print('bad'); sys.exit(4)"])
    assert not failed.ok and failed.data["exit_code"] == 4 and "exit code 4" in failed.error
    slow = call(env, "run_command", argv=["python", "-c", "import time; time.sleep(60)"], timeout_seconds=2)
    assert not slow.ok and slow.data["stopped"] == "timeout"
    outside = env.tmp / "outside.txt"
    attempt = call(env, "run_command", argv=["python", "-c", f"open(r'{outside}', 'w').write('x')"])
    if WINDOWS:
        assert not attempt.ok and "PermissionError" in attempt.output and not outside.exists()


@pytest.mark.parametrize(
    "argv, complaint",
    [
        (["cmd", "/c", "echo hi"], "not a program tasks may start"),
        (["powershell", "-Command", "Get-Process"], "not a program tasks may start"),
        (["bash", "-c", "ls"], "not a program tasks may start"),
        (["curl", "https://example.org"], "not a program tasks may start"),
        (["git", "push", "origin", "main"], "Git may only look"),
        (["git", "commit", "-m", "x"], "Git may only look"),
        (["git", "config", "core.hooksPath", "x"], "Git may only look"),
        (["python", "-m", "pip", "install", "requests"], "setup_environment"),
        (["../../bin/make"], "without a path"),
    ],
)
def test_programs_outside_the_allowed_list_are_refused(env, argv, complaint):
    refused = call(env, "run_command", argv=argv)
    assert not refused.ok and complaint in refused.error


def test_the_allowed_list_is_a_setting(env):
    env.context.settings["agent_allowed_programs"] = ["python"]
    assert "not a program tasks may start" in call(env, "run_command", argv=["git", "status"]).error
    assert call(env, "run_command", argv=["python", "-c", "print(1)"]).ok


def test_git_can_look_from_inside_the_sandbox(env):
    looked = call(env, "run_command", argv=["git", "status", "--short"])
    assert looked.ok, looked.output


def test_running_the_tests_reports_what_failed_and_then_that_all_pass(env):
    before = call(env, "run_tests")
    assert before.ok and before.data["passed"] is False
    run = before.data["runs"][0]
    assert run["counts"] == {"failed": 2, "passed": 1} and run["exit_code"] == 1
    assert run["failing"] == ["test_calc.py::test_add", "test_calc.py::test_double"]
    assert "FAILED (exit code 1): 2 failed, 1 passed" in before.output and "assert add(2, 3) == 5" in before.output

    call(env, "replace_in_file", path="calc.py", old="return a - b", new="return a + b")
    after = call(env, "run_tests")
    assert after.data["passed"] is True and after.data["runs"][0]["counts"] == {"passed": 3}
    assert "passed: 3 passed" in after.output

    env.context.settings["acceptance"] = []
    assert "no acceptance tests" in call(env, "run_tests").error
    explicit = call(env, "run_tests", commands=[["python", "-c", "raise SystemExit(0)"], ["python", "-c", "raise SystemExit(3)"]])
    assert explicit.data["passed"] is False and [item["passed"] for item in explicit.data["runs"]] == [True, False]


def test_parsing_pytest_summaries():
    text = "FAILED tests/test_a.py::test_one - assert 1 == 2\nERROR tests/test_b.py::test_two\n===== 1 failed, 3 passed, 1 error, 2 warnings in 0.42s ====="
    assert parse_test_output(text) == {"counts": {"failed": 1, "passed": 3, "error": 1, "warnings": 2}, "failing": ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]}
    assert parse_test_output("5 passed in 0.10s")["counts"] == {"passed": 5}
    assert parse_test_output("Build succeeded.") == {"counts": {}, "failing": []}


# ---- committing, and the record -----------------------------------------------------------------


def test_a_commit_goes_to_the_task_branch_and_is_checked(env):
    assert "nothing to commit" in call(env, "commit_changes", message="empty").error
    call(env, "replace_in_file", path="calc.py", old="return a - b", new="return a + b")
    done = call(env, "commit_changes", message="Fix add()\n\nIt subtracted instead of adding.")
    assert done.ok and done.verified and done.data["branch"] == env.checkout.branch
    assert git(env.repo, "rev-parse", env.checkout.branch) == done.data["commit"]
    assert git(env.repo, "log", "-1", "--format=%s", env.checkout.branch) == "Fix add()"
    assert git(env.repo, "status", "--porcelain") == "" and git(env.repo, "branch", "--show-current") == "main"
    # Running the same step again after a restart does not commit twice.
    assert call(env, "commit_changes", message="Fix add()\n\nIt subtracted instead of adding.").replayed


def test_everything_a_task_did_is_in_the_history(env):
    call(env, "read_file", path="calc.py")
    call(env, "replace_in_file", path="calc.py", old="return a - b", new="return a + b")
    call(env, "run_tests")
    call(env, "run_command", argv=["cmd", "/c", "dir"])
    history = list(reversed(env.store.actions(env.context.task_id)))
    assert [(item["tool"], item["effect"], item["status"]) for item in history] == [
        ("read_file", "read", "ok"),
        ("replace_in_file", "write", "ok"),
        ("run_tests", "execute", "ok"),
        ("run_command", "execute", "failed"),
    ]
    assert history[1]["arguments"]["path"] == "calc.py" and history[1]["artifacts"] == ["calc.py"] and history[1]["verified"] is True
    assert history[2]["data"]["passed"] is True
    assert "not a program tasks may start" in history[3]["error"]


def test_a_read_only_session_can_look_but_not_touch(env):
    env.context.policy = ApprovalPolicy("read_only")
    assert call(env, "read_file", path="calc.py").ok and call(env, "search_text", query="add").ok
    for name, arguments in (("write_file", {"path": "x.py", "content": "x"}), ("run_tests", {}), ("commit_changes", {"message": "m"}), ("delete_file", {"path": "calc.py"})):
        assert env.registry.call(name, arguments, env.context).status == "denied", name
    assert (env.checkout.path / "calc.py").exists() and not (env.checkout.path / "x.py").exists()


def test_every_tool_declares_its_effect_and_schema(env):
    described = {item["name"]: item for item in env.registry.describe()}
    assert {name for name, item in described.items() if item["effect"] == "read"} == {"list_files", "read_file", "search_text", "show_diff", "list_checkpoints"}
    assert {name for name, item in described.items() if item["effect"] == "execute"} == {"run_command", "run_tests"}
    writers = {name for name, item in described.items() if item["effect"] == "write"}
    assert writers == {"write_file", "replace_in_file", "apply_patch", "delete_file", "restore_checkpoint", "commit_changes"}
    assert all(described[name]["checks_its_outcome"] for name in writers)
    assert all(item["parameters"]["additionalProperties"] is False for item in described.values())
    assert Path(env.checkout.path).is_dir()
