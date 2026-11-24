"""Where the app's own time goes, and what it asks the network for on each rerun (items 101 and 104).

    python tools/app_profile.py --save docs/benchmarks/app_profile.json

Measured, on this machine, with the model server that is running here:

1. Importing: seconds to import modules.nexus_core, and app.py's modules, each in a fresh process.
2. The page: app.py run by Streamlit's own test runner (AppTest), as a first visit, then as the
   rerun that every click causes, then once more with a chat message sent. The chat answer comes
   from a stand-in that answers at once, so the figures are the app's own cost, not the model's.
   For each run: the seconds it took, where that time went (a sampler looks at the running
   script's call stack every few milliseconds; a function's share is the share of samples it was
   on the stack for, so nested functions overlap), and every HTTP request the app made, by address.

Nothing here needs the model to answer, and nothing is saved in the app's own data folder: the
runs use a throwaway home (COGNITIVE_NEXUS_HOME) unless --keep-home is given.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "app.py"
STAND_IN_ANSWER = "A hash table stores values under keys and finds them again in about the same time however many it holds."


def import_seconds(module: str) -> float:
    """Seconds to import a module in a fresh interpreter (the median of three)."""

    code = f"import sys, time; sys.path.insert(0, {str(REPO_ROOT)!r}); t = time.perf_counter(); import {module}; print(time.perf_counter() - t)"
    runs = []
    for _ in range(3):
        done = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True, text=True, env=dict(os.environ))
        if done.returncode != 0:
            raise RuntimeError(f"importing {module} failed: {done.stderr.strip().splitlines()[-1:]}")
        runs.append(float(done.stdout.strip().splitlines()[-1]))
    return round(sorted(runs)[1], 2)


class StackSampler(threading.Thread):
    """Counts, for each function, how many samples found it on the stack of the threads it watches."""

    def __init__(self, interval: float = 0.004) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()
        self.watched: set[int] = set()
        self.samples = 0
        self.on_stack: collections.Counter[str] = collections.Counter()
        self.at_top: collections.Counter[str] = collections.Counter()
        self.ignore = {threading.main_thread().ident}

    def run(self) -> None:
        self.ignore.add(threading.get_ident())
        while not self.stop_event.is_set():
            frames = sys._current_frames()
            for ident, frame in frames.items():
                if ident in self.ignore or (self.watched and ident not in self.watched):
                    continue
                name = threading._active.get(ident).name if threading._active.get(ident) else ""  # type: ignore[attr-defined]
                if not self.watched and "ScriptRunner" not in name and "scriptrunner" not in name.lower():
                    continue
                self.samples += 1
                seen: set[str] = set()
                top = True
                current: Any = frame
                while current is not None:
                    key = _where(current)
                    if top:
                        self.at_top[key] += 1
                        top = False
                    if key not in seen:
                        self.on_stack[key] += 1
                        seen.add(key)
                    current = current.f_back
            time.sleep(self.interval)

    def report(self, limit: int = 25) -> dict[str, Any]:
        def share(counter: collections.Counter[str], only_ours: bool) -> list[dict[str, Any]]:
            rows = [(key, count) for key, count in counter.most_common() if not only_ours or key.startswith("repo:")]
            return [{"function": key.removeprefix("repo:"), "share": round(count / max(1, self.samples), 3)} for key, count in rows[:limit]]

        return {
            "samples": self.samples,
            "on_stack_ours": share(self.on_stack, True),
            "at_top_any": share(self.at_top, False),
        }


def _where(frame: Any) -> str:
    filename = frame.f_code.co_filename
    try:
        relative = Path(filename).resolve().relative_to(REPO_ROOT)
        return f"repo:{relative.as_posix()}:{frame.f_code.co_name}"
    except (ValueError, OSError):
        parts = Path(filename).parts
        package = next((part for part in reversed(parts[:-1]) if part not in {"site-packages", "Lib", "lib"}), "")
        return f"{package}/{Path(filename).name}:{frame.f_code.co_name}"


class HttpLog:
    """Records every request made through `requests` (which the app uses for all HTTP)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._original: Any = None

    def __enter__(self) -> "HttpLog":
        import requests

        self._original = requests.sessions.Session.send
        log = self

        def send(session: Any, request: Any, **kwargs: Any) -> Any:
            parts = urlsplit(request.url)
            log.calls.append(f"{request.method} {parts.scheme}://{parts.netloc}{parts.path}")
            return log._original(session, request, **kwargs)

        requests.sessions.Session.send = send  # type: ignore[method-assign,assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        import requests

        requests.sessions.Session.send = self._original  # type: ignore[method-assign]

    def summary(self) -> dict[str, Any]:
        counted = collections.Counter(self.calls)
        return {"total": len(self.calls), "by_address": [{"call": call, "times": n} for call, n in counted.most_common()]}


def _stand_in_model() -> None:
    """The chat answer and every other model call come back at once, so only the app's own work is timed."""

    from modules import provider_router

    def stream(self: Any, request: Any, preferred_provider: Any = None) -> Any:
        self.last_stream_metadata = {"provider": "ollama", "model": request.model or "stand-in", "success": True, "attempts": [], "fallback_reason": ""}
        yield STAND_IN_ANSWER

    def generate(self: Any, request: Any) -> Any:
        return provider_router.ProviderResult(text="Label: NO", provider="ollama", model=request.model or "stand-in", success=True)

    provider_router.ProviderRouter.stream = stream  # type: ignore[method-assign]
    provider_router.ProviderRouter.generate = generate  # type: ignore[method-assign]


def profile_page(timeout: float) -> dict[str, Any]:
    from streamlit.testing.v1 import AppTest

    _stand_in_model()
    app = AppTest.from_file(str(APP_PATH), default_timeout=timeout)
    runs: dict[str, Any] = {}

    def measured(label: str, action: Any) -> None:
        sampler = StackSampler()
        with HttpLog() as http:
            sampler.start()
            started = time.perf_counter()
            action()
            seconds = time.perf_counter() - started
            sampler.stop_event.set()
            sampler.join()
        runs[label] = {"seconds": round(seconds, 2), "exception": [str(item.value)[:300] for item in app.exception], "http": http.summary(), "time": sampler.report()}
        print(f"{label}: {seconds:.2f} s, {len(http.calls)} HTTP requests", flush=True)

    measured("first_visit", app.run)
    measured("rerun", app.run)
    chat = app.chat_input
    if len(chat):
        measured("chat_turn", lambda: chat[0].set_value("In one sentence, what is a hash table?").run())
    else:
        runs["chat_turn"] = {"skipped": "no chat box on the page"}
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-home", action="store_true", help="use the app's real data folder instead of a throwaway one")
    args = parser.parse_args(argv)
    if not args.keep_home:
        os.environ["COGNITIVE_NEXUS_HOME"] = tempfile.mkdtemp(prefix="cn-profile-")
    sys.path.insert(0, str(REPO_ROOT))

    from modules import hardware

    result: dict[str, Any] = {
        "what": "The app's own time and HTTP requests, with a stand-in model (tools/app_profile.py)",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": hardware.describe(),
        "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "import_seconds": {name: import_seconds(name) for name in ("modules.nexus_core", "app")},
    }
    print(f"imports: {result['import_seconds']}", flush=True)
    result["page"] = profile_page(args.timeout)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
