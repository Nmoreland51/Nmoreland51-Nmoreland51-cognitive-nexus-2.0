"""Locks that stop two writers from overwriting each other's saved data.

Atomic writes (modules/file_utils.py) make sure a reader never sees a half-written file. They do
not help when two writers each read a file, change their own copy and write it back: the second
write silently discards the first one's change. That happens between the desktop app and the
phone backend, between two browser tabs, and inside one process between threads.

`locked(path)` holds a lock for one file (or one folder of files that must change together) across
threads and across processes. `update_json` does a whole read-change-write under that lock, which
is the only safe way to change a shared JSON file.
"""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from filelock import FileLock, Timeout

from modules.file_utils import atomic_write_json

# Long enough for a slow disk or a large knowledge index save; short enough that a stuck writer
# shows up as an error instead of a frozen app.
LOCK_TIMEOUT_SECONDS = 20.0

_registry_guard = threading.Lock()
# One (thread lock, file lock) pair per lock file. The thread lock gives mutual exclusion and
# re-entrancy between threads of this process; the file lock does the same between processes.
_locks: dict[str, tuple[threading.RLock, FileLock]] = {}


class StoreLockTimeout(RuntimeError):
    """Another writer held the lock for too long."""


def lock_file_for(path: Path | str) -> Path:
    """The lock file that guards `path` (a data file or a folder)."""

    target = Path(path)
    return target.with_name(target.name + ".lock")


def _lock_pair(path: Path | str) -> tuple[threading.RLock, FileLock]:
    lock_file = lock_file_for(path)
    key = str(lock_file.resolve())
    with _registry_guard:
        pair = _locks.get(key)
        if pair is None:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            pair = (threading.RLock(), FileLock(key, thread_local=False))
            _locks[key] = pair
        return pair


@contextlib.contextmanager
def locked(path: Path | str, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold the lock for `path` across threads and processes. Safe to nest for the same path."""

    thread_lock, file_lock = _lock_pair(path)
    if not thread_lock.acquire(timeout=timeout):
        raise StoreLockTimeout(f"Another part of the app has been changing {Path(path).name} for over {timeout:.0f} s.")
    try:
        try:
            file_lock.acquire(timeout=timeout)
        except Timeout as exc:
            raise StoreLockTimeout(
                f"Another program has been changing {Path(path).name} for over {timeout:.0f} s. "
                "If nothing else is running, delete the leftover .lock file next to it."
            ) from exc
        try:
            yield
        finally:
            file_lock.release()
    finally:
        thread_lock.release()


def read_json(path: Path | str, default: Any = None) -> Any:
    """Load a JSON file. Returns `default` when the file is missing; raises when it is damaged,
    so a damaged file is never mistaken for an empty one and then overwritten."""

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    if not text.strip():
        return default
    return json.loads(text)


def update_json(
    path: Path | str,
    change: Callable[[Any], Any],
    *,
    default: Callable[[], Any] = dict,
    indent: int | None = 2,
    timeout: float = LOCK_TIMEOUT_SECONDS,
) -> Any:
    """Read `path`, let `change` modify the loaded value in place, and save it, all under the lock.

    `change` receives the current content (or `default()` when there is no file yet) and may
    return a result, which is passed back to the caller. If it raises, nothing is written.
    """

    target = Path(path)
    with locked(target, timeout=timeout):
        current = read_json(target, None)
        if current is None:
            current = default()
        result = change(current)
        atomic_write_json(target, current, indent=indent)
        return result


def append_line(path: Path | str, line: str, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
    """Append one line to a log-style file without interleaving with another writer."""

    target = Path(path)
    with locked(target, timeout=timeout):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip("\n") + "\n")
