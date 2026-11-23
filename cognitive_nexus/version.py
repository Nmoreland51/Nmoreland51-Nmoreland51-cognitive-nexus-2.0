"""Version and build identity, so a running app can say exactly which code it is."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "2.1.0.dev0"

_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def build_info() -> dict[str, str]:
    """Return the version plus the git commit this copy runs, when it is a git checkout.

    A packaged build can ship a BUILD_COMMIT file (one line, the commit hash) instead.
    """

    commit = ""
    dirty = ""
    marker = _ROOT / "BUILD_COMMIT"
    if marker.exists():
        commit = marker.read_text(encoding="utf-8").strip()[:40]
    else:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short=12", "HEAD"], cwd=_ROOT, capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip()
            changed = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=_ROOT, capture_output=True, text=True, timeout=5
            ).stdout.strip()
            dirty = "yes" if changed else "no"
        except (OSError, subprocess.SubprocessError):
            commit = ""
    return {"version": __version__, "commit": commit or "unknown", "modified": dirty or "unknown"}


def build_label() -> str:
    info = build_info()
    suffix = " (modified)" if info["modified"] == "yes" else ""
    return f"Cognitive Nexus {info['version']} @ {info['commit']}{suffix}"
