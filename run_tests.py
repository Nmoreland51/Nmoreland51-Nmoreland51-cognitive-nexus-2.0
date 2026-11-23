"""Run the Cognitive Nexus test suite (same command CI uses)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys


def main() -> int:
    if importlib.util.find_spec("pytest") is None:
        print("pytest is not installed. Run: pip install -r requirements/dev.txt", file=sys.stderr)
        return 1
    # pytest also runs the plain test functions that `unittest discover` skips.
    return subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
