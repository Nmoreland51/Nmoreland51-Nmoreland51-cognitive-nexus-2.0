"""Two writers must not lose each other's changes: tested with real threads and real processes."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from modules.file_lock import StoreLockTimeout, append_line, lock_file_for, locked, read_json, update_json

REPO_ROOT = str(Path(__file__).resolve().parents[1])


# Each worker is a separate Python interpreter, started the way another program would be
# (not a forked or spawned copy of the test process).
ADD_ITEMS = """
import sys
sys.path.insert(0, sys.argv[1])
from modules.file_lock import update_json
path, worker, count = sys.argv[2], sys.argv[3], int(sys.argv[4])
for index in range(count):
    update_json(path, lambda data: data.setdefault("items", []).append(f"{worker}-{index}"))
"""

APPEND_LINES = """
import json, sys
sys.path.insert(0, sys.argv[1])
from modules.file_lock import append_line
path, worker, count = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
for index in range(count):
    append_line(path, json.dumps({"worker": worker, "index": index, "padding": "x" * 400}))
"""


def run_workers(code: str, path, workers: int, count: int) -> None:
    """Start `workers` interpreters at once and wait for all of them."""

    processes = [
        subprocess.Popen([sys.executable, "-c", code, REPO_ROOT, str(path), str(worker), str(count)], stderr=subprocess.PIPE)
        for worker in range(workers)
    ]
    for process in processes:
        _out, error = process.communicate(timeout=180)
        assert process.returncode == 0, error.decode(errors="replace")


def test_update_json_creates_and_changes_a_file(tmp_path):
    target = tmp_path / "store.json"

    assert update_json(target, lambda data: data.setdefault("count", 0)) == 0
    update_json(target, lambda data: data.update(count=data["count"] + 1))

    assert read_json(target) == {"count": 1}
    assert lock_file_for(target).name == "store.json.lock"


def test_a_failed_change_writes_nothing(tmp_path):
    target = tmp_path / "store.json"
    update_json(target, lambda data: data.update(value="kept"))

    def broken(data):
        data["value"] = "half-done"
        raise ValueError("stop")

    with pytest.raises(ValueError):
        update_json(target, broken)

    assert read_json(target) == {"value": "kept"}


def test_a_damaged_file_is_reported_not_treated_as_empty(tmp_path):
    target = tmp_path / "store.json"
    target.write_text('{"facts": ["important"', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        update_json(target, lambda data: data.update(facts=[]))

    # The damaged content is still there for recovery; it was not replaced by an empty store.
    assert target.read_text(encoding="utf-8") == '{"facts": ["important"'
    assert read_json(tmp_path / "missing.json", default={"new": True}) == {"new": True}


def test_threads_do_not_lose_updates(tmp_path):
    target = tmp_path / "store.json"
    workers, per_worker = 8, 25

    def work(worker: int) -> None:
        for index in range(per_worker):
            update_json(target, lambda data: data.setdefault("items", []).append(f"{worker}-{index}"))

    threads = [threading.Thread(target=work, args=(worker,)) for worker in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    items = read_json(target)["items"]
    assert len(items) == workers * per_worker
    assert len(set(items)) == workers * per_worker


def test_separate_processes_do_not_lose_updates(tmp_path):
    """The desktop app and the phone backend are separate processes writing the same files."""

    target = tmp_path / "store.json"
    workers, per_worker = 4, 20
    run_workers(ADD_ITEMS, target, workers, per_worker)

    items = read_json(target)["items"]
    assert len(items) == workers * per_worker, "an update from one process was overwritten by another"
    assert len(set(items)) == workers * per_worker


def test_separate_processes_do_not_interleave_appended_lines(tmp_path):
    target = tmp_path / "log.jsonl"
    workers, per_worker = 4, 30
    run_workers(APPEND_LINES, target, workers, per_worker)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == workers * per_worker
    parsed = [json.loads(line) for line in lines]  # every line is whole
    assert len({(row["worker"], row["index"]) for row in parsed}) == workers * per_worker


def test_lock_can_be_taken_again_by_the_same_thread(tmp_path):
    target = tmp_path / "store.json"

    with locked(target):
        with locked(target):
            update_json(target, lambda data: data.update(nested=True))

    assert read_json(target) == {"nested": True}


def test_waiting_too_long_for_another_thread_is_an_error(tmp_path):
    target = tmp_path / "store.json"
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with locked(target):
            holding.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert holding.wait(timeout=5)
        with pytest.raises(StoreLockTimeout, match="store.json"):
            with locked(target, timeout=0.2):
                pass
    finally:
        release.set()
        holder.join()

    append_line(tmp_path / "after.log", "still usable")
    assert (tmp_path / "after.log").read_text(encoding="utf-8") == "still usable\n"
