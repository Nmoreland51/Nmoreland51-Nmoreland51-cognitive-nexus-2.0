"""Fail when the repository tracks secrets or private runtime data.

Run by CI on every push:  python tools/check_repo_hygiene.py

Two checks over the files git tracks:
1. Secrets: API keys, tokens and private keys in file contents.
2. Private runtime data: chat history, user profiles, feedback logs, research output and other
   files the app writes while someone uses it. These belong on the user's machine, not in a
   public repository.

GRANDFATHERED lists private files that were committed before this check existed. They are
reported as warnings until the owner decides how to remove them (audit item 113); adding any new
private file fails the check.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "hard-coded credential": re.compile(
        r"""(?ix)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*["'](?!\s*["'])[A-Za-z0-9+/_\-]{24,}["']"""
    ),
}
# Files whose job is to contain example or test credentials.
SECRET_SCAN_SKIP = ("tools/check_repo_hygiene.py", "tests/test_repo_hygiene.py")

PRIVATE_DATA_PATTERNS = (
    ".env",
    ".env.*",
    "*accounts.json",
    "*chat_history*.json",
    "*user_profile*.json",
    "data/chat_profile.json",
    "data/feedback_log.jsonl",
    "data/memory_candidates.json",
    "data/response_preferences.json",
    "data/reality_grounding_patterns.json",
    "data/search_cache/*",
    "data/search_history/*",
    "data/web_research/*",
    "data/research_reports/*",
    "data/images/*",
    "data/knowledge_notes/*",
    "data/agent/*",
    "data/jobs/*",
    "data/backups/*",
    "data/_snapshots/*",
    "*.cnbackup",
    "*cognitive_nexus_export_*.zip",
    "*.backup.json",
    "*.damaged-*",
    "ai_system/knowledge_bank/images/*",
    "ai_system/knowledge_bank/web_research/*",
    "logs/*.log",
    "logs/*.jsonl",
)
PRIVATE_DATA_ALLOWED = (".env.example",)
GRANDFATHERED = (
    "ai_system/knowledge_bank/chat_history.json",
    "ai_system/knowledge_bank/images/*",
    "data/chat_profile.json",
    "data/feedback_log.jsonl",
    "data/memory_candidates.json",
)


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [name for name in result.stdout.decode("utf-8", "replace").split("\0") if name]


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def find_secrets(files: list[str]) -> list[str]:
    problems = []
    for name in files:
        if name in SECRET_SCAN_SKIP:
            continue
        path = ROOT / name
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{name}:{line}: looks like a {label}")
    return problems


def find_private_data(files: list[str]) -> tuple[list[str], list[str]]:
    """Return (new private files that fail the check, grandfathered ones to warn about)."""

    failures: list[str] = []
    warnings: list[str] = []
    for name in files:
        if _matches(name, PRIVATE_DATA_ALLOWED) or not _matches(name, PRIVATE_DATA_PATTERNS):
            continue
        (warnings if _matches(name, GRANDFATHERED) else failures).append(name)
    return failures, warnings


def main() -> int:
    files = tracked_files()
    secrets = find_secrets(files)
    private, grandfathered = find_private_data(files)
    for problem in secrets:
        print(f"SECRET  {problem}", file=sys.stderr)
    for name in private:
        print(f"PRIVATE {name}: runtime data must not be committed", file=sys.stderr)
    if grandfathered:
        print(
            f"warning: {len(grandfathered)} private file(s) committed before this check are still tracked "
            "(audit item 113, awaiting the owner's decision).",
            file=sys.stderr,
        )
    if secrets or private:
        return 1
    print(f"ok: {len(files)} tracked files, no secrets, no new private data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
