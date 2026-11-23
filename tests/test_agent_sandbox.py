"""The sandbox runs real programs here: these tests start processes and check what the operating
system let them do."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from agent import sandbox
from agent.sandbox import Limits, SandboxError

PYTHON = sys.executable
WINDOWS = os.name == "nt"


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "workspace"
    sandbox.prepare_workspace(folder)
    return folder


def python(workspace, code, *arguments, **options):
    return sandbox.run([PYTHON, "-I", "-c", code, *map(str, arguments)], workspace, **options)


def test_output_and_exit_code_are_captured(workspace):
    result = python(workspace, "import sys; print('to stdout'); print('to stderr', file=sys.stderr); sys.exit(3)")
    assert result.exit_code == 3 and not result.ok
    assert result.stdout.strip() == "to stdout"
    assert result.stderr.strip() == "to stderr"
    assert result.stopped == "" and result.seconds > 0
    assert python(workspace, "print('fine')").ok


def test_the_environment_carries_no_secrets_and_points_home_into_the_workspace(workspace, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-the-sandbox")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_for_the_sandbox")
    result = python(workspace, "import os, json; print(json.dumps(dict(os.environ)))")
    assert result.ok, result.stderr
    assert "not-for-the-sandbox" not in result.stdout and "not_for_the_sandbox" not in result.stdout
    import json

    env = json.loads(result.stdout)
    assert "OPENAI_API_KEY" not in env and "GITHUB_TOKEN" not in env
    for name in ("TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA"):
        assert Path(env[name]).resolve().is_relative_to(workspace.resolve()), name
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:9" and env["PIP_NO_INDEX"] == "1"
    open_network = sandbox.clean_environment(workspace, allow_network=True, extra={"MY_SETTING": "1"})
    assert "HTTPS_PROXY" not in open_network and open_network["MY_SETTING"] == "1"


def test_temporary_files_land_inside_the_workspace(workspace):
    result = python(workspace, "import tempfile; f = tempfile.NamedTemporaryFile(delete=False); f.write(b'x'); print(f.name)")
    assert result.ok, result.stderr
    assert Path(result.stdout.strip()).resolve().is_relative_to(workspace.resolve())


ATTEMPT = """
import os, sys
def attempt(action):
    try:
        action(); return "done"
    except OSError as exc:
        return "refused"
inside, outside = sys.argv[1], sys.argv[2]
print("write inside:", attempt(lambda: open(os.path.join(inside, "made_inside.txt"), "w").write("x")))
print("edit existing inside:", attempt(lambda: open(os.path.join(inside, "existing.txt"), "a").write("x")))
print("write outside:", attempt(lambda: open(os.path.join(outside, "made_outside.txt"), "w").write("x")))
print("edit outside:", attempt(lambda: open(os.path.join(outside, "victim.txt"), "a").write("tampered")))
print("delete outside:", attempt(lambda: os.remove(os.path.join(outside, "victim.txt"))))
print("mkdir outside:", attempt(lambda: os.mkdir(os.path.join(outside, "made_dir"))))
print("read outside:", open(os.path.join(outside, "victim.txt")).read())
"""


def test_the_operating_system_refuses_writes_outside_the_workspace(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("original")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "existing.txt").write_text("made before the folder was prepared")
    sandbox.prepare_workspace(workspace)

    result = python(workspace, ATTEMPT, workspace, outside)
    report = dict(line.split(": ", 1) for line in result.stdout.strip().splitlines())
    assert report["write inside"] == "done" and report["edit existing inside"] == "done", result.stderr
    assert (workspace / "made_inside.txt").exists()
    if not WINDOWS:
        assert result.isolation["writes_confined"] is False
        assert "not confined" in result.isolation["writes"]
        return
    assert result.isolation["writes_confined"] is True
    assert report["write outside"] == report["edit outside"] == report["delete outside"] == report["mkdir outside"] == "refused"
    assert (outside / "victim.txt").read_text() == "original"
    assert sorted(item.name for item in outside.iterdir()) == ["victim.txt"]
    assert report["read outside"] == "original"  # reading is not confined, and the report says so
    assert "not confined" in result.isolation["reads"]


@pytest.mark.skipif(not WINDOWS, reason="write confinement is a Windows feature here")
def test_without_confinement_the_same_program_can_write_outside(tmp_path):
    """The control for the test above: it is the confinement that stops the writes, nothing else."""

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("original")
    workspace = tmp_path / "workspace"
    sandbox.prepare_workspace(workspace)
    (workspace / "existing.txt").write_text("x")
    result = python(workspace, ATTEMPT, workspace, outside, confine_writes=False)
    assert "write outside: done" in result.stdout
    assert result.isolation["writes_confined"] is False


SPAWN_CHILD = """
import subprocess, sys, time, os
child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(120)"])
open(os.path.join(sys.argv[1], "child.pid"), "w").write(str(child.pid))
print("started", flush=True)
time.sleep(120)
"""


def _wait_gone(pid, seconds=10.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.1)
    return False


def test_a_time_limit_ends_the_program_and_everything_it_started(workspace):
    started = time.perf_counter()
    result = python(workspace, SPAWN_CHILD, workspace, limits=Limits(seconds=3))
    assert result.stopped == "timeout" and result.exit_code is None and not result.ok
    assert time.perf_counter() - started < 20
    assert "started" in result.stdout
    child = int((workspace / "child.pid").read_text())
    assert _wait_gone(child), "the program's child process outlived the time limit"


def test_cancelling_stops_a_running_program(workspace):
    cancel = threading.Event()

    def cancel_once_the_child_is_running():
        deadline = time.time() + 45
        while time.time() < deadline and not (workspace / "child.pid").exists():
            time.sleep(0.05)
        time.sleep(0.2)
        cancel.set()

    threading.Thread(target=cancel_once_the_child_is_running, daemon=True).start()
    started = time.perf_counter()
    result = python(workspace, SPAWN_CHILD, workspace, limits=Limits(seconds=90), cancel=cancel)
    assert result.stopped == "cancelled"
    assert time.perf_counter() - started < 60
    assert _wait_gone(int((workspace / "child.pid").read_text()))


def test_children_left_behind_by_a_finished_program_are_ended_too(workspace):
    code = (
        "import subprocess, sys, os\n"
        "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(120)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "open(os.path.join(sys.argv[1], 'child.pid'), 'w').write(str(child.pid))\n"
        "print('parent done')\n"
    )
    result = python(workspace, code, workspace, limits=Limits(seconds=30))
    assert result.ok and "parent done" in result.stdout
    assert _wait_gone(int((workspace / "child.pid").read_text()))


def test_memory_beyond_the_limit_cannot_be_taken(workspace):
    code = "data = bytearray(1500 * 1024 * 1024); print('allocated', len(data))"
    limited = python(workspace, code, limits=Limits(memory_mb=300, seconds=60))
    assert not limited.ok
    assert "allocated" not in limited.stdout
    assert "MemoryError" in limited.stderr or limited.exit_code not in (0, None)
    small = python(workspace, "data = bytearray(20 * 1024 * 1024); print('allocated', len(data))", limits=Limits(memory_mb=300, seconds=60))
    assert small.ok, small.stderr
    if WINDOWS:
        assert small.peak_memory_mb is not None and 20 <= small.peak_memory_mb <= 300


def test_output_is_kept_bounded(workspace):
    result = python(workspace, "print('START'); print('x' * 3_000_000); print('END')", limits=Limits(output_chars=20_000, seconds=60))
    assert result.ok
    assert result.truncated
    assert len(result.stdout) < 25_000
    assert result.stdout.startswith("START") and result.stdout.rstrip().endswith("END")
    assert "left out" in result.stdout


def test_arguments_are_not_interpreted_by_a_shell(workspace):
    marker = workspace / "hacked.txt"
    result = python(workspace, "import sys; print(sys.argv[1])", f"harmless && echo hacked > {marker} | more; `whoami` $(whoami) %PATH%")
    assert result.ok
    assert "&& echo hacked" in result.stdout and "%PATH%" in result.stdout
    assert not marker.exists()


def test_the_working_folder_must_be_inside_the_workspace(workspace, tmp_path):
    inner = workspace / "package"
    inner.mkdir()
    assert python(workspace, "import os; print(os.getcwd())", cwd=inner).stdout.strip().lower().endswith("package")
    with pytest.raises(SandboxError, match="outside the workspace"):
        python(workspace, "print(1)", cwd=tmp_path)
    with pytest.raises(SandboxError, match="does not exist"):
        python(workspace, "print(1)", cwd=workspace / "missing")


def test_a_program_that_cannot_be_started_is_an_error_not_a_result(workspace):
    with pytest.raises(SandboxError, match="Could not start"):
        sandbox.run(["definitely-not-a-real-program-4711"], workspace)
    with pytest.raises(SandboxError, match="non-empty list"):
        sandbox.run([], workspace)


def test_the_report_says_what_is_and_is_not_enforced():
    report = sandbox.isolation_report()
    assert "not blocked by the operating system" in report["network"]
    assert "not confined" in report["reads"]
    assert report["writes_confined"] is WINDOWS
    assert "closed port" not in sandbox.isolation_report(allow_network=True)["network"]
