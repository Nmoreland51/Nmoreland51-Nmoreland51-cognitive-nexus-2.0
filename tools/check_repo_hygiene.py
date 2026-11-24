"""Fail when the repository tracks secrets or private runtime data.

Run by CI on every push:  python tools/check_repo_hygiene.py
Other files and folders:  python tools/check_repo_hygiene.py --scan logs data app-release.apk

--scan looks for secrets in the files given, in every file under a folder given, and inside zip-based
archives (an Android .apk or .aab, .jar, .whl, .zip), so the app's own logs from before item 110 and
a phone build can be checked too. It does not look for private data, which is what those folders hold.

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

import argparse
import fnmatch
import re
import subprocess
import sys
import zipfile
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


ARCHIVE_SUFFIXES = (".apk", ".aab", ".jar", ".whl", ".zip")
MAX_SCANNED_BYTES = 20_000_000


def _secrets_in(text: str, where: str) -> list[str]:
    found = []
    for label, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(f"{where}:{line}: looks like a {label}")
    return found


def _decoded(data: bytes) -> str:
    """Text from a file's bytes, binary or not: keys in compiled code are stored as plain characters."""

    return data.decode("utf-8", errors="replace")


def scan_paths(paths: list[str]) -> tuple[list[str], int]:
    """Secrets in the given files, folders and archives. Returns (problems, files looked at)."""

    problems: list[str] = []
    looked_at = 0
    for given in paths:
        path = Path(given)
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else []
        if not candidates:
            problems.append(f"{given}: not found")
        for item in candidates:
            try:
                if item.stat().st_size > MAX_SCANNED_BYTES and item.suffix.lower() not in ARCHIVE_SUFFIXES:
                    continue
                if item.suffix.lower() in ARCHIVE_SUFFIXES and zipfile.is_zipfile(item):
                    with zipfile.ZipFile(item) as archive:
                        for entry in archive.infolist():
                            if entry.is_dir() or entry.file_size > MAX_SCANNED_BYTES:
                                continue
                            looked_at += 1
                            problems.extend(_secrets_in(_decoded(archive.read(entry)), f"{item}!{entry.filename}"))
                    continue
                looked_at += 1
                problems.extend(_secrets_in(_decoded(item.read_bytes()), str(item)))
            except (OSError, zipfile.BadZipFile) as exc:
                problems.append(f"{item}: could not be read ({exc})")
    return problems, looked_at


def find_private_data(files: list[str]) -> tuple[list[str], list[str]]:
    """Return (new private files that fail the check, grandfathered ones to warn about)."""

    failures: list[str] = []
    warnings: list[str] = []
    for name in files:
        if _matches(name, PRIVATE_DATA_ALLOWED) or not _matches(name, PRIVATE_DATA_PATTERNS):
            continue
        (warnings if _matches(name, GRANDFATHERED) else failures).append(name)
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scan", nargs="+", metavar="PATH", help="look for secrets in these files, folders or archives instead")
    args = parser.parse_args(argv)
    if args.scan:
        problems, looked_at = scan_paths(args.scan)
        for problem in problems:
            print(f"SECRET  {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"ok: {looked_at} files looked at, no secrets")
        return 0

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
