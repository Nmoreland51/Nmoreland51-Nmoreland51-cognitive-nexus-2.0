"""Run every check CI runs, locally, and report which passed.

  python tools/run_checks.py            # lint, types, hygiene, ledger, tests
  python tools/run_checks.py --audit    # also scan pinned dependencies for known vulnerabilities (needs network)
  python tools/run_checks.py --fast     # skip the test suite
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", action="store_true", help="also run pip-audit on requirements/constraints.txt")
    parser.add_argument("--fast", action="store_true", help="skip pytest")
    args = parser.parse_args()

    python = sys.executable
    checks: list[tuple[str, list[str]]] = [
        ("lint", [python, "-m", "ruff", "check", "."]),
        ("types", [python, "-m", "mypy"]),
        ("hygiene", [python, "tools/check_repo_hygiene.py"]),
        ("ledger", [python, "tools/audit_ledger.py", "check"]),
    ]
    if not args.fast:
        checks.append(("tests", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]))
    if args.audit:
        checks.append(
            ("audit", [python, "-m", "pip_audit", "-r", "requirements/constraints.txt", "--no-deps", "--disable-pip", "--progress-spinner", "off"])
        )

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    failed = []
    for name, command in checks:
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        seconds = time.perf_counter() - started
        tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-1:] or [""]
        print(f"{'ok  ' if result.returncode == 0 else 'FAIL'} {name:8s} {seconds:5.1f}s  {tail[0][:110]}")
        if result.returncode != 0:
            failed.append(name)
            print((result.stdout + result.stderr)[-3000:])
    print("all checks passed" if not failed else f"failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
