"""One SQLite database for everything the agent has to remember across restarts.

Tasks (with owner, status, blockers, dependencies and acceptance tests), the history of every
action taken (inputs, approval, result, artifacts), approval requests, and the background job
queue (agent/jobs.py) all live in data/agent/agent.db. SQLite gives the two things the JSON files
elsewhere in the app cannot: several processes can use it at once, and a change is either fully
written or not at all, so a crash never leaves half a record.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from modules.data_stores import DATA_ROOT

AGENT_DIR = DATA_ROOT / "agent"
DB_FILE = AGENT_DIR / "agent.db"
SCHEMA_VERSION = 1

TASK_STATUSES = ("queued", "running", "waiting_approval", "blocked", "review", "done", "failed", "escalated", "cancelled")
# Which status may follow which. "done" and "cancelled" are final.
TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("running", "blocked", "cancelled"),
    "running": ("waiting_approval", "blocked", "review", "done", "failed", "escalated", "cancelled", "queued"),
    "waiting_approval": ("running", "queued", "cancelled"),
    "blocked": ("queued", "running", "cancelled"),
    "review": ("done", "failed", "running", "queued", "cancelled"),
    "escalated": ("queued", "running", "cancelled"),
    "failed": ("queued", "cancelled"),
    "done": (),
    "cancelled": (),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'fix',
    status TEXT NOT NULL DEFAULT 'queued',
    owner TEXT NOT NULL DEFAULT 'agent',
    repo TEXT NOT NULL DEFAULT '',
    base_ref TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL DEFAULT '',
    acceptance TEXT NOT NULL DEFAULT '[]',
    blockers TEXT NOT NULL DEFAULT '[]',
    budget TEXT NOT NULL DEFAULT '{}',
    spent TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    parent TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_deps (
    task_id TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on)
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS task_events_task ON task_events (task_id, id);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    session TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    effect TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    output TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    artifacts TEXT NOT NULL DEFAULT '[]',
    verified INTEGER,
    verification TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS actions_key ON actions (key, started_at);
CREATE INDEX IF NOT EXISTS actions_task ON actions (task_id, started_at);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    effect TEXT NOT NULL,
    summary TEXT NOT NULL,
    arguments TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS approvals_key ON approvals (key, requested_at);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    run_after TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    timeout_seconds REAL NOT NULL DEFAULT 600,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_until TEXT NOT NULL DEFAULT '',
    heartbeat_at TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    progress_note TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT,
    schedule_id TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency ON jobs (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (status, run_after, priority);
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    every_seconds INTEGER NOT NULL DEFAULT 0,
    daily_at TEXT NOT NULL DEFAULT '',
    next_run TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_job TEXT NOT NULL DEFAULT '',
    last_value TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class StoreError(Exception):
    """A request the store refuses: an unknown task, a status that cannot follow the current one."""


def now() -> str:
    """The current time in UTC, to the millisecond, as sortable text."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


@dataclass
class Task:
    """A unit of work with an owner, a status, and the tests that say when it is done."""

    id: str
    title: str
    description: str = ""
    kind: str = "fix"
    status: str = "queued"
    owner: str = "agent"
    repo: str = ""
    base_ref: str = ""
    branch: str = ""
    workspace: str = ""
    acceptance: list[list[str]] = field(default_factory=list)  # commands that must succeed
    blockers: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    spent: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # where the agent is, for resuming
    result: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    parent: str = ""
    created_at: str = ""
    updated_at: str = ""
    depends_on: list[str] = field(default_factory=list)


_TASK_JSON_FIELDS = ("acceptance", "blockers", "budget", "spent", "state", "result")
_TASK_TEXT_FIELDS = ("title", "description", "kind", "owner", "repo", "base_ref", "branch", "workspace", "parent")


class AgentStore:
    """The agent's database. Safe to share between threads and processes."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path if path is not None else DB_FILE).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.transaction() as db:
            # One statement at a time: executescript would commit and end the transaction.
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            row = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                db.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(row["value"]) > SCHEMA_VERSION:
                raise StoreError(
                    f"{self.path} was written by a newer version of the app (schema {row['value']}, this version reads {SCHEMA_VERSION})."
                )

    # ---- connection ----------------------------------------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=30000")
            self._local.connection = connection
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Everything inside happens together or not at all, and no other writer gets in between."""

        connection = self._connection()
        if connection.in_transaction:  # already inside one on this thread
            yield connection
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    def read(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self._connection().execute(sql, parameters).fetchall()

    def close(self) -> None:
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    # ---- tasks ---------------------------------------------------------------------------------

    def create_task(
        self,
        title: str,
        description: str = "",
        *,
        kind: str = "fix",
        owner: str = "agent",
        repo: str = "",
        base_ref: str = "",
        acceptance: list[list[str]] | None = None,
        budget: dict[str, Any] | None = None,
        priority: int = 0,
        depends_on: list[str] | None = None,
        parent: str = "",
    ) -> Task:
        if not title.strip():
            raise StoreError("A task needs a title.")
        task_id = new_id("task")
        stamp = now()
        with self.transaction() as db:
            for dependency in depends_on or []:
                if db.execute("SELECT 1 FROM tasks WHERE id = ?", (dependency,)).fetchone() is None:
                    raise StoreError(f"Task {dependency} does not exist, so nothing can depend on it.")
            db.execute(
                "INSERT INTO tasks (id, title, description, kind, owner, repo, base_ref, acceptance, budget, priority, parent, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, title.strip(), description, kind, owner, repo, base_ref, _json(acceptance or []), _json(budget or {}), priority, parent, stamp, stamp),
            )
            for dependency in depends_on or []:
                db.execute("INSERT INTO task_deps (task_id, depends_on) VALUES (?, ?)", (task_id, dependency))
            self._event(db, task_id, "created", f"Task created: {title.strip()}", {"owner": owner, "depends_on": depends_on or []})
        return self.get_task(task_id)

    def _task(self, row: sqlite3.Row, db: sqlite3.Connection) -> Task:
        values = dict(row)
        for name in _TASK_JSON_FIELDS:
            values[name] = json.loads(values[name] or ("[]" if name in ("acceptance", "blockers") else "{}"))
        values["depends_on"] = [item["depends_on"] for item in db.execute("SELECT depends_on FROM task_deps WHERE task_id = ? ORDER BY depends_on", (row["id"],))]
        return Task(**values)

    def get_task(self, task_id: str) -> Task:
        db = self._connection()
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise StoreError(f"There is no task {task_id}.")
        return self._task(row, db)

    def list_tasks(self, status: str | None = None, parent: str | None = None) -> list[Task]:
        db = self._connection()
        clauses, parameters = [], []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if parent is not None:
            clauses.append("parent = ?")
            parameters.append(parent)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = db.execute(f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at", tuple(parameters)).fetchall()
        return [self._task(row, db) for row in rows]

    def update_task(self, task_id: str, *, note: str = "", **changes: Any) -> Task:
        """Change fields of a task. A status change must be one the current status allows."""

        with self.transaction() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise StoreError(f"There is no task {task_id}.")
            assignments, parameters = [], []
            status = changes.pop("status", None)
            if status is not None and status != row["status"]:
                if status not in TASK_STATUSES:
                    raise StoreError(f"{status!r} is not a task status.")
                if status not in TASK_TRANSITIONS[row["status"]]:
                    raise StoreError(f"A task that is {row['status']} cannot become {status}.")
                assignments.append("status = ?")
                parameters.append(status)
                self._event(db, task_id, "status", note or f"{row['status']} -> {status}", {"from": row["status"], "to": status})
            for name, value in changes.items():
                if name in _TASK_JSON_FIELDS:
                    assignments.append(f"{name} = ?")
                    parameters.append(_json(value))
                elif name in _TASK_TEXT_FIELDS:
                    assignments.append(f"{name} = ?")
                    parameters.append(str(value))
                elif name == "priority":
                    assignments.append("priority = ?")
                    parameters.append(int(value))
                else:
                    raise StoreError(f"A task has no field {name!r}.")
            if assignments:
                assignments.append("updated_at = ?")
                parameters.extend([now(), task_id])
                db.execute(f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?", tuple(parameters))
        return self.get_task(task_id)

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        """Make one task wait for another. Refused if it would make the tasks wait for each other."""

        with self.transaction() as db:
            for item in (task_id, depends_on):
                if db.execute("SELECT 1 FROM tasks WHERE id = ?", (item,)).fetchone() is None:
                    raise StoreError(f"There is no task {item}.")
            pending, seen = [depends_on], set()
            while pending:
                current = pending.pop()
                if current == task_id:
                    raise StoreError(f"{task_id} cannot depend on {depends_on}: {depends_on} already depends on it.")
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(row["depends_on"] for row in db.execute("SELECT depends_on FROM task_deps WHERE task_id = ?", (current,)))
            db.execute("INSERT OR IGNORE INTO task_deps (task_id, depends_on) VALUES (?, ?)", (task_id, depends_on))
            self._event(db, task_id, "dependency", f"Now depends on {depends_on}", {"depends_on": depends_on})

    def unfinished_dependencies(self, task_id: str) -> list[str]:
        rows = self.read(
            "SELECT d.depends_on FROM task_deps d JOIN tasks t ON t.id = d.depends_on WHERE d.task_id = ? AND t.status != 'done' ORDER BY d.depends_on",
            (task_id,),
        )
        return [row["depends_on"] for row in rows]

    def ready_tasks(self) -> list[Task]:
        """Queued tasks whose dependencies are all done, most urgent first."""

        return [task for task in self.list_tasks("queued") if not self.unfinished_dependencies(task.id)]

    def _event(self, db: sqlite3.Connection, task_id: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO task_events (task_id, at, kind, message, data) VALUES (?, ?, ?, ?, ?)", (task_id, now(), kind, message, _json(data or {})))

    def add_event(self, task_id: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        with self.transaction() as db:
            self._event(db, task_id, kind, message, data)

    def events(self, task_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.read("SELECT * FROM task_events WHERE task_id = ? ORDER BY id LIMIT ?", (task_id, limit))
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    # ---- actions -------------------------------------------------------------------------------

    def begin_action(self, *, key: str, tool: str, effect: str, arguments: dict[str, Any], task_id: str = "", session: str = "", approval_id: str = "") -> str:
        """Write down that an action is about to run. Returns its id."""

        action_id = new_id("act")
        with self.transaction() as db:
            db.execute(
                "INSERT INTO actions (id, key, task_id, session, tool, effect, arguments, status, approval_id, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?, ?)",
                (action_id, key, task_id, session, tool, effect, _json(arguments), approval_id, now()),
            )
        return action_id

    def finish_action(
        self,
        action_id: str,
        *,
        status: str,
        output: str = "",
        data: dict[str, Any] | None = None,
        error: str = "",
        artifacts: list[str] | None = None,
        verified: bool | None = None,
        verification: str = "",
        duration: float = 0.0,
    ) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE actions SET status = ?, finished_at = ?, duration = ?, output = ?, data = ?, error = ?, artifacts = ?, verified = ?, verification = ? WHERE id = ?",
                (status, now(), duration, output, _json(data or {}), error, _json(artifacts or []), None if verified is None else int(verified), verification, action_id),
            )

    def record_refusal(self, *, key: str, tool: str, effect: str, arguments: dict[str, Any], status: str, error: str, task_id: str = "", session: str = "") -> str:
        """An action that was not run (denied, invalid arguments, unknown tool) still goes in the history."""

        action_id = new_id("act")
        stamp = now()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO actions (id, key, task_id, session, tool, effect, arguments, status, started_at, finished_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (action_id, key, task_id, session, tool, effect, _json(arguments), status, stamp, stamp, error),
            )
        return action_id

    @staticmethod
    def _action(row: sqlite3.Row) -> dict[str, Any]:
        values = dict(row)
        for name in ("arguments", "data", "artifacts"):
            values[name] = json.loads(values[name])
        values["verified"] = None if values["verified"] is None else bool(values["verified"])
        return values

    def completed_action(self, key: str) -> dict[str, Any] | None:
        """The last successful run of the action with this key, if there is one."""

        rows = self.read("SELECT * FROM actions WHERE key = ? AND status = 'ok' ORDER BY started_at DESC LIMIT 1", (key,))
        return self._action(rows[0]) if rows else None

    def interrupted_actions(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """Actions that started and never finished: the process stopped while they ran."""

        if task_id is None:
            rows = self.read("SELECT * FROM actions WHERE status = 'started' ORDER BY started_at")
        else:
            rows = self.read("SELECT * FROM actions WHERE status = 'started' AND task_id = ? ORDER BY started_at", (task_id,))
        return [self._action(row) for row in rows]

    def mark_interrupted(self, action_id: str, note: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE actions SET status = 'interrupted', finished_at = ?, error = ? WHERE id = ? AND status = 'started'", (now(), note, action_id))

    def actions(self, task_id: str | None = None, limit: int = 200, effect: str | None = None) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if task_id is not None:
            clauses.append("task_id = ?")
            parameters.append(task_id)
        if effect is not None:
            clauses.append("effect = ?")
            parameters.append(effect)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.read(f"SELECT * FROM actions {where} ORDER BY started_at DESC, rowid DESC LIMIT ?", (*parameters, limit))
        return [self._action(row) for row in rows]

    # ---- approvals -----------------------------------------------------------------------------

    def request_approval(self, *, key: str, tool: str, effect: str, summary: str, arguments: dict[str, Any], task_id: str = "") -> str:
        """Ask a person to allow one specific action. Asking twice for the same action returns the same request."""

        with self.transaction() as db:
            row = db.execute("SELECT id FROM approvals WHERE key = ? AND status = 'pending' ORDER BY requested_at DESC LIMIT 1", (key,)).fetchone()
            if row is not None:
                return str(row["id"])
            approval_id = new_id("apr")
            db.execute(
                "INSERT INTO approvals (id, key, task_id, tool, effect, summary, arguments, status, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (approval_id, key, task_id, tool, effect, summary, _json(arguments), now()),
            )
            if task_id:
                self._event(db, task_id, "approval_requested", summary, {"approval": approval_id, "tool": tool})
        return approval_id

    def decide_approval(self, approval_id: str, *, approved: bool, by: str, note: str = "") -> dict[str, Any]:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if row is None:
                raise StoreError(f"There is no approval request {approval_id}.")
            if row["status"] != "pending":
                raise StoreError(f"Approval request {approval_id} was already {row['status']}.")
            if not by.strip():
                raise StoreError("An approval has to say who decided it.")
            status = "approved" if approved else "denied"
            db.execute("UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, note = ? WHERE id = ?", (status, now(), by.strip(), note, approval_id))
            if row["task_id"]:
                self._event(db, row["task_id"], f"approval_{status}", f"{by.strip()} {status} {row['tool']}", {"approval": approval_id, "note": note})
        return self.approval(approval_id)

    def approval(self, approval_id: str) -> dict[str, Any]:
        rows = self.read("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if not rows:
            raise StoreError(f"There is no approval request {approval_id}.")
        return {**dict(rows[0]), "arguments": json.loads(rows[0]["arguments"])}

    def approval_for(self, key: str) -> dict[str, Any] | None:
        """The newest decision or open request about the action with this key."""

        rows = self.read("SELECT * FROM approvals WHERE key = ? AND status IN ('pending', 'approved', 'denied') ORDER BY requested_at DESC LIMIT 1", (key,))
        return {**dict(rows[0]), "arguments": json.loads(rows[0]["arguments"])} if rows else None

    def use_approval(self, approval_id: str) -> bool:
        """An approval allows one run. Returns False if it was already used or is not an approval."""

        with self.transaction() as db:
            changed = db.execute("UPDATE approvals SET status = 'used' WHERE id = ? AND status = 'approved'", (approval_id,)).rowcount
        return bool(changed)

    def approvals(self, status: str | None = "pending", task_id: str | None = None) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if task_id is not None:
            clauses.append("task_id = ?")
            parameters.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.read(f"SELECT * FROM approvals {where} ORDER BY requested_at", tuple(parameters))
        return [{**dict(row), "arguments": json.loads(row["arguments"])} for row in rows]
