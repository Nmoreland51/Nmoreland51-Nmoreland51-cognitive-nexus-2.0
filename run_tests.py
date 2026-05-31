"""Run the Cognitive Nexus unittest suite."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
