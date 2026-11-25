"""What is known about each project the coding agent works on (item 048).

One project is one repository, as a task names it. For each the memory keeps five kinds of note:

    objective   what the project is for, or what is being worked towards       (the owner)
    decision    what was decided, and why                                       (the owner)
    bug         a known problem that is not fixed yet                           (the owner)
    test        the last result of each acceptance command                      (the agent, every run)
    state       where the repository stood: branch, last commit, uncommitted    (the agent, every run)

The owner writes the first three in the Agent tab or with `python -m agent memory add`; the agent
keeps the last two up to date as it works. Before every attempt the coding agent is shown what is
known (brief()), the owner's notes marked as the owner's. A bug that is fixed, a decision that is
reversed or an objective that is reached is closed, not deleted, so the history stays.

The notes live in the agent's database (data/agent/agent.db), in a table of their own, created
the first time it is needed; nothing older in that database changes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent.store import AgentStore, StoreError, new_id, now

KINDS = ("objective", "decision", "bug", "test", "state")
TITLES = {"objective": "Objectives", "decision": "Decisions", "bug": "Known bugs", "test": "Last test runs", "state": "Repository state"}
OWNER_KINDS = ("objective", "decision", "bug")
MAX_NOTE_CHARS = 2000
BRIEF_CHARS = 1500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_notes (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_by TEXT NOT NULL DEFAULT '',
    close_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS project_notes_repo ON project_notes (repo, kind, status)
"""


def project_key(repo: str) -> str:
    """One name per project: a folder by its full path (any case on Windows), an address without ".git"."""

    given = (repo or "").strip()
    if not given:
        return ""
    if "://" in given or given.startswith("git@"):
        return given.rstrip("/").removesuffix(".git").lower()
    path = Path(given).expanduser()
    try:
        path = path.resolve()
    except OSError:
        pass
    text = path.as_posix()
    return text.lower() if len(text) > 1 and text[1] == ":" else text


def git_state(repo: str, timeout: float = 10.0) -> dict[str, Any] | None:
    """The branch, last commit and number of uncommitted files of a local repository; None when it is not one."""

    folder = Path(repo or "")
    if not folder.is_dir():
        return None

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip())
        return done.stdout.strip()

    try:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        head = git("log", "-1", "--format=%h %s")
        changed = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return None
    return {"branch": branch, "head": head, "uncommitted": len(changed)}


class ProjectMemory:
    def __init__(self, store: AgentStore) -> None:
        self.store = store
        with store.transaction() as db:
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)

    def add(self, repo: str, kind: str, text: str, *, source: str = "owner", key: str = "") -> dict[str, Any]:
        """Write a note. With a key, an open note of the same kind and key is replaced (the last test result, the current state)."""

        project = project_key(repo)
        if not project:
            raise StoreError("A note needs the project it is about.")
        if kind not in KINDS:
            raise StoreError(f"Unknown kind of note '{kind}'. Use one of: {', '.join(KINDS)}.")
        cleaned = " ".join((text or "").split())
        if not cleaned:
            raise StoreError("The note is empty.")
        if len(cleaned) > MAX_NOTE_CHARS:
            raise StoreError(f"A note can be at most {MAX_NOTE_CHARS} characters; this one has {len(cleaned)}.")
        stamp = now()
        with self.store.transaction() as db:
            existing = (
                db.execute(
                    "SELECT id FROM project_notes WHERE repo = ? AND kind = ? AND key = ? AND status = 'open' ORDER BY updated_at DESC LIMIT 1",
                    (project, kind, key),
                ).fetchone()
                if key
                else None
            )
            if existing is not None:
                note_id = str(existing["id"])
                db.execute("UPDATE project_notes SET text = ?, source = ?, updated_at = ? WHERE id = ?", (cleaned, source, stamp, note_id))
            else:
                note_id = new_id("note")
                db.execute(
                    "INSERT INTO project_notes (id, repo, kind, key, text, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (note_id, project, kind, key, cleaned, source, stamp, stamp),
                )
        return self.note(note_id)

    def note(self, note_id: str) -> dict[str, Any]:
        rows = self.store.read("SELECT * FROM project_notes WHERE id = ?", (note_id,))
        if not rows:
            raise StoreError(f"There is no note {note_id}.")
        return dict(rows[0])

    def close(self, note_id: str, *, by: str, note: str = "") -> dict[str, Any]:
        """A bug fixed, a decision reversed, an objective reached: the note stays in the history, closed."""

        if not by.strip():
            raise StoreError("Say who closes the note.")
        with self.store.transaction() as db:
            row = db.execute("SELECT status FROM project_notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                raise StoreError(f"There is no note {note_id}.")
            if row["status"] != "open":
                raise StoreError(f"Note {note_id} is already closed.")
            db.execute(
                "UPDATE project_notes SET status = 'closed', closed_by = ?, close_note = ?, updated_at = ? WHERE id = ?",
                (by.strip(), " ".join(note.split()), now(), note_id),
            )
        return self.note(note_id)

    def notes(self, repo: str, *, kinds: tuple[str, ...] | None = None, include_closed: bool = False) -> list[dict[str, Any]]:
        """A project's notes: by kind in the order of KINDS, the newest first within a kind."""

        rows = self.store.read(
            "SELECT * FROM project_notes WHERE repo = ?" + ("" if include_closed else " AND status = 'open'") + " ORDER BY updated_at DESC",
            (project_key(repo),),
        )
        wanted = kinds or KINDS
        found = [dict(row) for row in rows if row["kind"] in wanted]
        return sorted(found, key=lambda row: KINDS.index(row["kind"]))

    def projects(self) -> list[str]:
        return [str(row["repo"]) for row in self.store.read("SELECT DISTINCT repo FROM project_notes ORDER BY repo")]

    def record_tests(self, repo: str, runs: list[dict[str, Any]], *, when: str = "") -> list[dict[str, Any]]:
        """The result of each acceptance command, as the run_tests tool reports it ({"argv", "passed", "counts"})."""

        written = []
        for run in runs:
            command = " ".join(str(part) for part in run.get("argv") or [])
            counts = ", ".join(f"{count} {word}" for word, count in (run.get("counts") or {}).items()) or f"exit code {run.get('exit_code', '?')}"
            outcome = "passed" if run.get("passed") else "failed"
            text = f"$ {command}: {outcome} ({counts})" + (f", {when}" if when else "")
            written.append(self.add(repo, "test", text, source="agent", key=command))
        return written

    def record_state(self, repo: str) -> dict[str, Any] | None:
        """Where a local repository stands now. None when it is not one (an address, or not a Git folder)."""

        state = git_state(repo)
        if state is None:
            return None
        text = f"branch {state['branch']}, last commit {state['head']}, {state['uncommitted']} uncommitted file(s), seen {now()[:16].replace('T', ' ')} UTC"
        return self.add(repo, "state", text, source="agent", key="git")

    def brief(self, repo: str, *, max_chars: int = BRIEF_CHARS) -> str:
        """What the agent is told about a project before an attempt; empty when nothing is known."""

        lines: list[str] = []
        known = self.notes(repo)
        for kind in KINDS:
            found = [row for row in known if row["kind"] == kind]
            if not found:
                continue
            whose = "the owner's notes" if kind in OWNER_KINDS else "recorded by the agent"
            lines.append(f"{TITLES[kind]} ({whose}):")
            lines.extend(f"- {row['text']}" for row in found)
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 30].rsplit("\n", 1)[0] + "\n- (more in the project memory)"
        return text
