"""The register of every restriction and behaviour-affecting mechanism in Cognitive Nexus.

    python tools/restriction_register.py render   write docs/OWNER_CONTROL_RESTRICTIONS.md
    python tools/restriction_register.py check    used by CI (see below)
    python tools/restriction_register.py scan     which files mention restriction-related terms, and how each is accounted for

Source of truth: docs/backlog/restrictions.json. The Markdown file is generated; do not edit it.

An entry says where a mechanism is by quoting a line of the code (an "anchor"), not by line
number, so the register cannot go stale without the check noticing:

  * every anchor of an active entry must still be in its file (the line number shown in the
    document is looked up when it is rendered);
  * every anchor of a removed mechanism must be gone from its file: "removed" is checked, not claimed;
  * every source file that mentions a restriction-related term must either be the home of a
    register entry or be listed as reviewed with the reason it holds no restriction. A new
    filter, refusal text or approval gate in a new place fails the check until it is registered.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "docs" / "backlog" / "restrictions.json"
REPORT_FILE = ROOT / "docs" / "OWNER_CONTROL_RESTRICTIONS.md"

CATEGORIES = {
    "A": "Conversation behaviour (what the app itself asks of, or keeps from, the model)",
    "B": "Model and provider (outside the app's control; disclosed, not changeable here)",
    "C": "Tools and side effects (what the agent may do, and what waits for the owner)",
    "D": "Integrity and security (credentials, data, outside text, isolation)",
    "E": "Quality controls (accuracy labels and checks; they add notes, they do not refuse)",
    "F": "Interface defaults and labels",
}
STATUSES = ("active", "changed", "removed")
# Every entry needs these. `decision_date` may be empty while a decision is pending.
REQUIRED = (
    "id", "name", "category", "status", "trigger", "effect", "owner_requested", "evidence", "origin", "technical_reason",
    "affected_workflows", "default_state", "effective_state", "alternatives", "configurable", "owner_decision", "tests",
    "regression_risk", "known_limitations",
)  # fmt: skip
SCAN_TERMS = re.compile(
    r"refus|can.t (?:help|assist|provide)|cannot (?:help|assist|provide)|not as actionable|safety_|unhinged|nsfw|moderat|"
    r"block(?:ed|_reason)|forbid|disallow|censor|harmful|illegal|never (?:produce|write)|do not provide|must not|cannot override|"
    r"approval|allowlist|allowed_programs|never_allow|protected|sandbox|untrusted|private (?:address|network)|ssrf|restrict|"
    r"guardrail|jailbreak|content_rule|content rule|injection",
    re.IGNORECASE,
)
SCAN_SUFFIXES = {".py"}
SCAN_EXTRA_FILES = ("config/nexus_config.json",)
# Not scanned, and why. Anything executable that shapes behaviour lives outside these.
NOT_SCANNED = {
    "tests": "tests describe behaviour; they do not create it",
    "legacy": "the pre-2.0 app, kept for reference and not imported by the running app",
    "fullstack-local": "an abandoned experiment, not imported by the running app",
    "docs": "documentation",
    "data": "saved user data",
    "ai_system": "saved knowledge",
    "generated_images": "saved images",
    "logs": "logs",
    ".agents": "Markdown descriptions for coding assistants; nothing in the app reads them",
    "skills": "Markdown descriptions for coding assistants; nothing in the app reads them",
    "commands": "Markdown descriptions for coding assistants; nothing in the app reads them",
    "internal": "notes",
    ".git": "version control",
    ".github": "CI configuration",
}


def load() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def find_line(relative: str, anchor: str) -> int | None:
    """The 1-based line of the first occurrence of an anchor in a file, or None."""

    path = ROOT / relative
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    at = text.find(anchor)
    return None if at < 0 else text.count("\n", 0, at) + 1


def scan() -> dict[str, int]:
    """Source files that mention a restriction-related term, with the number of lines that do."""

    found: dict[str, int] = {}
    candidates = [path for path in ROOT.rglob("*") if path.suffix in SCAN_SUFFIXES and path.is_file()]
    candidates += [ROOT / name for name in SCAN_EXTRA_FILES if (ROOT / name).is_file()]
    for path in candidates:
        relative = path.relative_to(ROOT).as_posix()
        top = relative.split("/")[0]
        if top in NOT_SCANNED or "__pycache__" in relative or top.startswith(".") and top not in {"."}:
            continue
        hits = sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if SCAN_TERMS.search(line))
        if hits:
            found[relative] = hits
    return dict(sorted(found.items()))


def coverage(data: dict[str, Any]) -> list[dict[str, Any]]:
    """For every scanned file with a match: the entries that live there, or why it holds no restriction."""

    homes: dict[str, list[str]] = {}
    for entry in data["entries"]:
        for location in entry.get("locations", []) + entry.get("gone", []):
            homes.setdefault(location["file"], []).append(entry["id"])
    reviewed = data.get("reviewed_files", {})
    return [
        {"file": name, "lines": hits, "entries": sorted(set(homes.get(name, []))), "reviewed": reviewed.get(name, "")}
        for name, hits in scan().items()
    ]


def render() -> str:
    data = load()
    entries = data["entries"]
    lines = [
        "# Restrictions and behaviour-affecting mechanisms",
        "",
        "Generated by `tools/restriction_register.py` from `docs/backlog/restrictions.json`. Do not edit this file by hand.",
        "",
        data["about"],
        "",
        "## How to read this",
        "",
        "- **Category** says which layer a mechanism belongs to. The layers are kept apart in the code as well: "
        "conversation rules are not tool permissions, and neither is a security protection.",
        "- **Status**: *active* (in the code now), *changed* (still there, altered by the owner-control work), "
        "*removed* (gone; the check confirms the quoted code is no longer in the file).",
        "- **Where** quotes a line of the code and gives its current line number, looked up when this file was generated.",
        "- **Owner requested** and **Origin** say who asked for a mechanism. \"Earlier AI-written code\" means it was in "
        "the repository before this work and no owner request for it is recorded.",
        "",
        "## Summary",
        "",
        "| Layer | Active | Changed | Removed |",
        "|---|---|---|---|",
    ]
    for key, title in CATEGORIES.items():
        mine = [entry for entry in entries if entry["category"] == key]
        lines.append(f"| {key}. {title.split(' (')[0]} | " + " | ".join(str(sum(entry["status"] == status for entry in mine)) for status in STATUSES) + " |")
    lines += ["", "| ID | Mechanism | Status | Default | Can the owner change it? | Owner decision |", "|---|---|---|---|---|---|"]
    for entry in entries:
        lines.append(
            f"| {entry['id']} | {entry['name']} | {entry['status']} | {entry['default_state'].split('. ')[0].rstrip('.')} | "
            f"{entry['configurable'].split('. ')[0].rstrip('.')} | {entry['owner_decision'].split('. ')[0].rstrip('.')} |"
        )
    for key, title in CATEGORIES.items():
        mine = [entry for entry in entries if entry["category"] == key]
        if not mine:
            continue
        lines += ["", f"## {key}. {title}", ""]
        for entry in mine:
            lines += [f"### {entry['id']} · {entry['name']} · {entry['status']}", ""]
            for location in entry.get("locations", []):
                line = find_line(location["file"], location["anchor"])
                lines.append(f"- **Where:** `{location['file']}:{line if line else '?'}` — `{location['anchor'].strip()[:110]}`")
            for location in entry.get("gone", []):
                lines.append(f"- **Where it was:** `{location['file']}` — `{location['anchor'].strip()[:110]}` (no longer in the file)")
            for label, field in (
                ("Trigger", "trigger"), ("Effect", "effect"), ("Owner requested", "owner_requested"), ("Evidence", "evidence"),
                ("Origin", "origin"), ("Technical reason", "technical_reason"), ("Affected workflows", "affected_workflows"),
                ("Default", "default_state"), ("Effective now", "effective_state"), ("Alternatives", "alternatives"),
                ("Can the owner change it?", "configurable"), ("Owner decision", "owner_decision"), ("Decision date", "decision_date"),
                ("Tests", "tests"), ("Regression risk", "regression_risk"), ("Known limitations", "known_limitations"),
            ):  # fmt: skip
                if entry.get(field):
                    lines.append(f"- **{label}:** {entry[field]}")
            lines.append(f"- **Reviewer:** {entry.get('reviewer') or data['reviewer']}")
            lines.append("")
    lines += [
        "## Search coverage",
        "",
        "Every Python source file outside the folders listed below, and the settings file, is searched for the terms in "
        "`tools/restriction_register.py` (`SCAN_TERMS`). Each file with a match is either the home of a register entry or "
        "is listed with the reason it holds no restriction. The check fails when a matching file is neither.",
        "",
        "| File | Matching lines | Register entries | Reviewed: why it holds no restriction |",
        "|---|---|---|---|",
    ]
    for row in coverage(data):
        lines.append(f"| `{row['file']}` | {row['lines']} | {', '.join(row['entries']) or '-'} | {row['reviewed'] or '-'} |")
    lines += ["", "Not searched:", ""]
    lines += [f"- `{name}/`: {reason}" for name, reason in NOT_SCANNED.items()]
    lines += ["", data.get("other_repositories", "")]
    return "\n".join(lines).rstrip() + "\n"


def check() -> list[str]:
    data = load()
    problems: list[str] = []
    seen: set[str] = set()
    for entry in data["entries"]:
        name = entry.get("id", "?")
        if name in seen:
            problems.append(f"{name}: id used twice")
        seen.add(name)
        for field in REQUIRED:
            if not str(entry.get(field, "")).strip():
                problems.append(f"{name}: '{field}' is empty")
        if entry.get("category") not in CATEGORIES:
            problems.append(f"{name}: category must be one of {', '.join(CATEGORIES)}")
        if entry.get("status") not in STATUSES:
            problems.append(f"{name}: status must be one of {', '.join(STATUSES)}")
        if entry.get("status") in {"active", "changed"} and not entry.get("locations"):
            problems.append(f"{name}: an active mechanism needs at least one location")
        if entry.get("status") == "removed" and not entry.get("gone"):
            problems.append(f"{name}: a removed mechanism needs the code that was removed ('gone'), so its absence can be checked")
        if not str(entry.get("owner_decision", "")).lower().startswith("pending") and not entry.get("decision_date"):
            problems.append(f"{name}: a decision that is not pending needs its date")
        for location in entry.get("locations", []):
            if find_line(location["file"], location["anchor"]) is None:
                problems.append(f"{name}: not found in {location['file']}: {location['anchor'][:70]!r} (the code moved or changed: update the register)")
        for location in entry.get("gone", []):
            if find_line(location["file"], location["anchor"]) is not None:
                problems.append(f"{name}: recorded as removed, but still in {location['file']}: {location['anchor'][:70]!r}")
    for row in coverage(data):
        if not row["entries"] and not row["reviewed"]:
            problems.append(f"{row['file']}: mentions restriction-related terms on {row['lines']} line(s) and is neither in the register nor listed as reviewed")
    if not REPORT_FILE.exists() or REPORT_FILE.read_text(encoding="utf-8") != render():
        problems.append("docs/OWNER_CONTROL_RESTRICTIONS.md is out of date; run: python tools/restriction_register.py render")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("render", "check", "scan"))
    args = parser.parse_args(argv)
    if args.command == "render":
        REPORT_FILE.write_bytes(render().encode("utf-8"))
        print(f"rendered {REPORT_FILE.relative_to(ROOT)}")
    elif args.command == "scan":
        for row in coverage(load()):
            how = ", ".join(row["entries"]) or (f"reviewed: {row['reviewed']}" if row["reviewed"] else "NOT ACCOUNTED FOR")
            print(f"{row['file']:<48} {row['lines']:>4}  {how}")
    else:
        problems = check()
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
