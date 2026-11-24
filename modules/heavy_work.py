"""Heavy work on this machine: one picture at a time, and room in memory for it (items 098 and 105).

The two largest things this app puts in memory are the chat model, which Ollama keeps loaded for a
day after each use (the app asks for keep_alive 24h; dolphin3:8b takes 4.95 GB), and the Stable
Diffusion pipeline that makes pictures on the processor (7.1 GB at its peak for a 512x512 picture,
8.5 GB for 768x768; tools/picture_memory_check.py). On the development machine, with 8.4 GB free
and the chat model loaded, making a 768x768 picture left 0.35 GB free at the lowest point. With so
little left, Windows moves memory to disk and everything becomes very slow, or a process is ended
for lack of memory.

* picture_slot(): one picture at a time on this machine, across browser tabs, the phone backend and
  other processes (a lock file). A request waits its turn for up to `wait_seconds`; at most
  MAX_WAITING requests wait at once, and one more is turned down straight away with a message that
  says the machine is busy. Nothing waits without the person being told.
* make_room(): before the pipeline is loaded. When the memory available is less than the picture
  needs plus MARGIN_GB and Ollama holds a chat model, the chat model is taken out of memory
  (keep_alive 0), unless the owner's setting `picture_memory` is "keep_chat_model". Ollama loads it
  again by itself for the next chat answer, which then takes longer to start. Nothing is refused for
  lack of memory: when no room can be made the picture is still made, and the note says it may be
  slow. What was done comes back with the picture and is shown under it.
* wait_for_room(): before a chat request. While a picture is being made, a chat model that is not
  loaded and does not fit in the memory left waits for the picture to finish (up to
  `wait_seconds`) instead of being loaded beside it. When no picture is being made this costs one
  check of a flag and a lock file, so chat is not slowed down.
* PictureStop: a time limit and a cancel for one picture, checked between denoising steps.
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import requests
from filelock import FileLock, Timeout

from modules.data_stores import DATA_ROOT

GB = 1024**3
MARGIN_GB = 1.5  # left free for the system, the browser and the app itself
MAX_WAITING = 2  # requests waiting for the picture slot at once; one more is turned down at once
DEFAULT_WAIT_SECONDS = 600.0
DEFAULT_TIME_LIMIT_SECONDS = 1800.0
POLICIES = ("free_chat_model", "keep_chat_model")
DEFAULT_POLICY = "free_chat_model"
POLICY_LABELS = {
    "free_chat_model": "Take the chat model out of memory first (it loads again for the next answer)",
    "keep_chat_model": "Keep the chat model loaded (the picture may be slow)",
}
# Measured with tools/picture_memory_check.py on the development machine (processor, float32,
# torch 2.15, 2026-11-24; docs/benchmarks/picture_memory.json): the peak working set of a process
# making one 512x512 picture, and one 768x768 picture. Loading alone took 5.94 GB of it. Other
# sizes are estimated from those two points; see picture_need_gb().
PICTURE_MEMORY_512_GB = 7.12
PICTURE_MEMORY_768_GB = 8.53
UNLOAD_WAIT_SECONDS = 15.0
_PICTURE_LOCK = DATA_ROOT / "images" / "making_a_picture.lock"

_guard = threading.Condition()
_state = {"in_progress": 0, "waiting": 0}


class MachineBusy(RuntimeError):
    """Another picture is being made and enough requests are already waiting for it."""


class PictureStopped(RuntimeError):
    """A picture was stopped between steps: cancelled, or over its time limit."""


def picture_need_gb(width: int, height: int) -> float:
    """Memory one picture of this size needs while it is made here (processor, float32), in GB.

    Grows with the number of pixels: through the two measured sizes, and on in a straight line
    beyond them, which is a lower bound because attention grows faster than the pixel count.
    """

    pixels = max(1, int(width)) * max(1, int(height))
    small, large = 512 * 512, 768 * 768
    per_pixel = (PICTURE_MEMORY_768_GB - PICTURE_MEMORY_512_GB) / (large - small)
    return round(max(PICTURE_MEMORY_512_GB * 0.8, PICTURE_MEMORY_512_GB + per_pixel * (pixels - small)), 2)


def available_gb() -> float:
    import psutil

    return psutil.virtual_memory().available / GB


def _base(base_url: str) -> str:
    if base_url:
        return base_url.rstrip("/")
    from modules.providers import get_ollama_base_url

    return get_ollama_base_url().rstrip("/")


def loaded_chat_models(base_url: str = "", *, timeout: float = 2.0) -> list[dict[str, Any]]:
    """The models Ollama holds in memory now: name and size in GB. Empty when Ollama does not answer."""

    try:
        response = requests.get(f"{_base(base_url)}/api/ps", timeout=timeout)
        response.raise_for_status()
        models = response.json().get("models") or []
    except (requests.RequestException, ValueError):
        return []
    return [{"name": str(item.get("name") or item.get("model") or ""), "size_gb": round(int(item.get("size") or 0) / GB, 2)} for item in models]


def model_file_gb(model: str, base_url: str = "", *, timeout: float = 2.0) -> float:
    """The size of a model's file as Ollama lists it, in GB (0.0 when unknown)."""

    try:
        response = requests.get(f"{_base(base_url)}/api/tags", timeout=timeout)
        response.raise_for_status()
        for item in response.json().get("models") or []:
            if model in (item.get("name"), item.get("model")):
                return int(item.get("size") or 0) / GB
    except (requests.RequestException, ValueError):
        pass
    return 0.0


def unload_model(name: str, base_url: str = "", *, wait_seconds: float = UNLOAD_WAIT_SECONDS) -> bool:
    """Ask Ollama to take a model out of memory now (an empty request with keep_alive 0) and wait until it has."""

    url = _base(base_url)
    try:
        response = requests.post(f"{url}/api/generate", json={"model": name, "keep_alive": 0}, timeout=(5.0, 30.0))
        response.raise_for_status()
    except requests.RequestException:
        return False
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if all(item["name"] != name for item in loaded_chat_models(url)):
            return True
        time.sleep(0.5)
    return False


def _lock_held_elsewhere() -> bool:
    """Whether another process holds the picture lock (a picture is being made there)."""

    if not _PICTURE_LOCK.parent.exists():
        return False
    probe = FileLock(str(_PICTURE_LOCK), thread_local=False)
    try:
        probe.acquire(timeout=0)
    except Timeout:
        return True
    probe.release()
    return False


def picture_in_progress() -> bool:
    """Whether a picture is being made on this machine now (in this process or another)."""

    with _guard:
        if _state["in_progress"]:
            return True
    return _lock_held_elsewhere()


@contextlib.contextmanager
def picture_slot(wait_seconds: float = DEFAULT_WAIT_SECONDS, *, max_waiting: int = MAX_WAITING) -> Iterator[float]:
    """Hold the one picture slot of this machine; yields the seconds spent waiting for it.

    Raises MachineBusy when `max_waiting` requests already wait, or when the slot does not come
    free within `wait_seconds`.
    """

    started = time.monotonic()
    with _guard:
        if _state["in_progress"] and _state["waiting"] >= max_waiting:
            raise MachineBusy(
                f"A picture is being made and {_state['waiting']} more are waiting for it. Try again when they are done."
            )
        _state["waiting"] += 1
        try:
            while _state["in_progress"]:
                left = wait_seconds - (time.monotonic() - started)
                if left <= 0:
                    raise MachineBusy(f"Another picture has been in the making for over {wait_seconds:.0f} s. Try again later.")
                _guard.wait(timeout=min(left, 5.0))
            _state["in_progress"] += 1
        finally:
            _state["waiting"] -= 1
    file_lock = FileLock(str(_PICTURE_LOCK), thread_local=False)
    try:
        _PICTURE_LOCK.parent.mkdir(parents=True, exist_ok=True)
        left = max(0.0, wait_seconds - (time.monotonic() - started))
        try:
            file_lock.acquire(timeout=left)
        except Timeout as exc:
            raise MachineBusy(
                f"Another program on this machine has been making a picture for over {wait_seconds:.0f} s. Try again later."
            ) from exc
        try:
            yield round(time.monotonic() - started, 1)
        finally:
            file_lock.release()
    finally:
        with _guard:
            _state["in_progress"] -= 1
            _guard.notify_all()


def make_room(
    need_gb: float,
    *,
    policy: str = DEFAULT_POLICY,
    base_url: str = "",
    memory: Callable[[], float] = available_gb,
    loaded: Callable[[str], list[dict[str, Any]]] | None = None,
    unload: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """Before a picture: free the chat model's memory when the picture would not fit beside it.

    Returns what was found and done; "note" is a sentence for the person, empty when nothing had
    to be done.
    """

    policy = policy if policy in POLICIES else DEFAULT_POLICY
    loaded = loaded or (lambda url: loaded_chat_models(url))
    unload = unload or (lambda name, url: unload_model(name, url))
    free = memory()
    report: dict[str, Any] = {
        "need_gb": round(need_gb, 2),
        "available_gb": round(free, 2),
        "margin_gb": MARGIN_GB,
        "short": free < need_gb + MARGIN_GB,
        "policy": policy,
        "action": "none",
        "unloaded": [],
        "note": "",
    }
    if not report["short"]:
        return report
    in_memory = [item for item in loaded(base_url) if item.get("name")]
    shortfall = f"{free:.1f} GB of memory free, about {need_gb + MARGIN_GB:.1f} GB needed"
    if not in_memory:
        report["action"] = "nothing to free"
        report["note"] = f"Memory was short ({shortfall}) and no chat model was loaded; the picture was made anyway and may be slow."
        return report
    names = ", ".join(f"{item['name']}, {item.get('size_gb', 0):.1f} GB" for item in in_memory)
    if policy == "keep_chat_model":
        report["action"] = "kept"
        report["note"] = f"Memory was short ({shortfall}); the setting keeps the chat model ({names}) loaded, so the picture was made beside it and may be slow."
        return report
    freed = [item["name"] for item in in_memory if unload(item["name"], base_url)]
    report["unloaded"] = freed
    report["available_after_gb"] = round(memory(), 2)
    if len(freed) == len(in_memory):
        report["action"] = "unloaded"
        report["note"] = (
            f"Made room first ({shortfall}): the chat model ({names}) was taken out of memory. "
            "It loads again by itself for the next chat answer, which will take a little longer to start "
            "(about 12 s on the development machine)."
        )
    else:
        report["action"] = "could not free"
        report["note"] = f"Memory was short ({shortfall}) and Ollama did not take the chat model ({names}) out of memory; the picture was made anyway and may be slow."
    return report


def wait_for_room(
    model: str,
    base_url: str = "",
    *,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    in_progress: Callable[[], bool] = picture_in_progress,
    memory: Callable[[], float] = available_gb,
    loaded: Callable[[str], list[dict[str, Any]]] | None = None,
    model_size: Callable[[str, str], float] | None = None,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    """Before a chat request: wait for a picture to finish when the model would not fit beside it.

    Returns {"waited_seconds": ..., "reason": ...}; both are empty when nothing had to wait.
    """

    report: dict[str, Any] = {"waited_seconds": 0.0, "reason": ""}
    if not model or not in_progress():
        return report
    loaded = loaded or (lambda url: loaded_chat_models(url))
    if any(item.get("name") == model for item in loaded(base_url)):
        return report  # already in memory: answering adds little
    model_size = model_size or (lambda name, url: model_file_gb(name, url))
    # What a loaded copy holds: the file plus its working memory (dolphin3:8b: 4.9 GB file, 5.3 GB loaded).
    need = model_size(model, base_url) * 1.1 + MARGIN_GB
    if memory() >= need:
        return report
    started = time.monotonic()
    while in_progress() and time.monotonic() - started < wait_seconds:
        time.sleep(poll_seconds)
    report["waited_seconds"] = round(time.monotonic() - started, 1)
    report["reason"] = "A picture was being made and the chat model did not fit in memory beside it, so the answer waited for the picture."
    return report


@dataclass
class PictureStop:
    """A time limit and a cancel for one picture, checked by the pipeline between denoising steps."""

    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS
    cancel: threading.Event | None = None
    started: float = field(default_factory=time.monotonic)
    reason: str = ""
    step: int = 0

    def should_stop(self) -> bool:
        if self.reason:
            return True
        if self.cancel is not None and self.cancel.is_set():
            self.reason = "cancelled"
        elif time.monotonic() - self.started > self.time_limit_seconds:
            self.reason = f"over its time limit of {self.time_limit_seconds:.0f} s"
        return bool(self.reason)

    def on_step_end(self, pipe: Any, step: int, timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
        """For diffusers' callback_on_step_end: ends the denoising loop when the picture should stop."""

        self.step = int(step) + 1
        if self.should_stop():
            pipe._interrupt = True
        return callback_kwargs

    def raise_if_stopped(self) -> None:
        if self.reason:
            raise PictureStopped(f"The picture was stopped after {time.monotonic() - self.started:.0f} s at step {self.step}: {self.reason}.")


def lock_path() -> Path:
    """The lock file held while a picture is being made (for tests and diagnostics)."""

    return _PICTURE_LOCK
