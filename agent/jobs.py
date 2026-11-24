"""Background work that survives a restart: a job queue, a scheduler and the workers that run them.

A job is a row in the agent's database (agent/store.py), so it exists until it is finished, and
whoever runs it has to say so:

* A worker takes a job by writing its name and a lease time on it. While it works it renews the
  lease and reports progress. If the worker dies, the lease runs out and the job is taken again
  (or fails for good after its last allowed try).
* A job that fails is tried again later, after a pause that doubles each time, up to its limit.
* A job can be cancelled: one that is waiting is cancelled at once; one that is running is told
  to stop, and the work it started in the sandbox is ended.
* A job has a time limit. One that overruns is told to stop and is recorded as timed out.
* Enqueuing with an idempotency key twice gives one job, so a retry after a crash (of the
  scheduler, or of whatever asked) does not do the work twice.
* Workers respect capacity: a total number of jobs at once, and a limit per kind of job (one
  model-heavy job at a time on a machine with one local model). Higher priority goes first.
* The queue is bounded: at most MAX_QUEUED_PER_KIND jobs of one kind wait at once (QUEUE_LIMITS:
  10 coding tasks). One more is refused with a message (QueueFull); a scheduled firing that would
  go over the limit is skipped, and the user gets a notice saying so.

A schedule turns into jobs: every N seconds, or daily at a time. Each firing is enqueued under a
key made of the schedule and the time it was due, so a firing happens once however often the
scheduler looks.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from agent.store import AgentStore, StoreError, new_id, now
from modules.event_log import record_event

JOB_STATUSES = ("queued", "running", "done", "failed", "cancelled")
LEASE_GRACE_SECONDS = 30.0  # how long past its time limit a silent worker keeps a job
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 600.0
DEFAULT_KIND_LIMITS = {"coding_task": 1}  # one job at a time that occupies the local model
# How many jobs of one kind may wait at once. One more is refused (QueueFull) instead of joining a
# queue that would take days to work through; a coding task takes many minutes on the local model.
MAX_QUEUED_PER_KIND = 100
QUEUE_LIMITS = {"coding_task": 10}


class JobCancelled(Exception):
    """Raised inside a handler by control.check() when the job was cancelled or ran out of time."""


class QueueFull(StoreError):
    """Too many jobs of this kind are already waiting."""


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def retry_delay(attempts: int) -> float:
    """Seconds to wait before the next try after `attempts` failed tries: 5, 10, 20, ... up to 10 minutes."""

    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1)))


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    status: str
    priority: int
    run_after: str
    attempts: int
    max_attempts: int
    timeout_seconds: float
    lease_owner: str
    lease_until: str
    heartbeat_at: str
    progress: float
    progress_note: str
    result: dict[str, Any]
    error: str
    idempotency_key: str | None
    schedule_id: str
    cancel_requested: bool
    created_at: str
    updated_at: str


def _job(row: Any) -> Job:
    values = dict(row)
    values["payload"] = json.loads(values["payload"] or "{}")
    values["result"] = json.loads(values["result"] or "{}")
    values["cancel_requested"] = bool(values["cancel_requested"])
    return Job(**values)


class JobControl:
    """What a handler gets to talk to the queue: report progress, and find out it should stop."""

    def __init__(self, queue: "JobQueue", job: Job, worker: str) -> None:
        self.queue, self.job, self.worker = queue, job, worker
        self.cancel = threading.Event()  # set when the job is cancelled, timed out or lost
        self.reason = ""

    def progress(self, fraction: float, note: str = "") -> None:
        """Say how far along the job is (0 to 1). Also renews the lease, and raises JobCancelled when the job should stop."""

        if self.queue.heartbeat(self.job.id, self.worker, progress=max(0.0, min(1.0, float(fraction))), note=note):
            self.reason = self.reason or "cancelled"
            self.cancel.set()
        self.check()

    def check(self) -> None:
        if self.cancel.is_set():
            raise JobCancelled(self.reason or "cancelled")


class JobQueue:
    def __init__(self, store: AgentStore) -> None:
        self.store = store

    # ---- putting work in ---------------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
        delay_seconds: float = 0.0,
        run_at: datetime | None = None,
        max_attempts: int = 3,
        timeout_seconds: float = 600.0,
        idempotency_key: str | None = None,
        schedule_id: str = "",
        queue_limit: int | None = None,
    ) -> str:
        """Add a job. With an idempotency key that was used before, returns the job it made then.

        Raises QueueFull when `queue_limit` jobs of this kind are already waiting (default: the
        kind's entry in QUEUE_LIMITS, else MAX_QUEUED_PER_KIND), so work does not pile up unseen.
        """

        if not kind.strip():
            raise StoreError("A job needs a kind.")
        stamp = now()
        due = _stamp(run_at) if run_at is not None else _stamp(datetime.now(timezone.utc) + timedelta(seconds=max(0.0, delay_seconds)))
        limit = int(queue_limit if queue_limit is not None else QUEUE_LIMITS.get(kind, MAX_QUEUED_PER_KIND))
        with self.store.transaction() as db:
            if idempotency_key is not None:
                existing = db.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if existing is not None:
                    return str(existing["id"])
            waiting = int(db.execute("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' AND kind = ?", (kind,)).fetchone()["n"])
            if waiting >= limit:
                raise QueueFull(
                    f"{waiting} {kind} jobs are already waiting, which is the limit. Wait for some to finish, or cancel some, and add it again."
                )
            job_id = new_id("job")
            db.execute(
                "INSERT INTO jobs (id, kind, payload, priority, run_after, max_attempts, timeout_seconds, idempotency_key, schedule_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, kind, json.dumps(payload or {}, ensure_ascii=False, default=str), int(priority), due, max(1, int(max_attempts)), float(timeout_seconds), idempotency_key, schedule_id, stamp, stamp),
            )
        return job_id

    # ---- looking -----------------------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        rows = self.store.read("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not rows:
            raise StoreError(f"There is no job {job_id}.")
        return _job(rows[0])

    def jobs(self, status: str | None = None, kind: str | None = None, limit: int = 200) -> list[Job]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.store.read(f"SELECT * FROM jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?", (*parameters, limit))
        return [_job(row) for row in rows]

    def counts(self) -> dict[str, int]:
        return {row["status"]: int(row["n"]) for row in self.store.read("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}

    # ---- a worker's side ---------------------------------------------------------------------

    def lease(self, worker: str, *, kinds: set[str] | None = None, capacity: int = 2, kind_limits: dict[str, int] | None = None) -> Job | None:
        """Take the most urgent job that is due and that capacity allows, or None."""

        limits = {**DEFAULT_KIND_LIMITS, **(kind_limits or {})}
        moment = now()
        with self.store.transaction() as db:
            running = db.execute("SELECT kind, COUNT(*) AS n FROM jobs WHERE status = 'running' GROUP BY kind").fetchall()
            in_use = {row["kind"]: int(row["n"]) for row in running}
            if sum(in_use.values()) >= capacity:
                return None
            due = db.execute("SELECT * FROM jobs WHERE status = 'queued' AND run_after <= ? ORDER BY priority DESC, run_after, created_at, rowid LIMIT 50", (moment,)).fetchall()
            for row in due:
                if kinds is not None and row["kind"] not in kinds:
                    continue
                if in_use.get(row["kind"], 0) >= limits.get(row["kind"], capacity):
                    continue
                lease_until = _stamp(datetime.now(timezone.utc) + timedelta(seconds=float(row["timeout_seconds"]) + LEASE_GRACE_SECONDS))
                db.execute(
                    "UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_owner = ?, lease_until = ?, heartbeat_at = ?, progress = 0, progress_note = '', error = '', updated_at = ? WHERE id = ?",
                    (worker, lease_until, moment, moment, row["id"]),
                )
                return _job(db.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())
        return None

    def heartbeat(self, job_id: str, worker: str, *, progress: float | None = None, note: str | None = None) -> bool:
        """Say the job is still being worked on. Returns True when the job should stop (cancelled, or no longer this worker's)."""

        moment = now()
        with self.store.transaction() as db:
            row = db.execute("SELECT status, lease_owner, cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None or row["status"] != "running" or row["lease_owner"] != worker:
                return True
            assignments = ["heartbeat_at = ?", "updated_at = ?"]
            parameters: list[Any] = [moment, moment]
            if progress is not None:
                assignments.append("progress = ?")
                parameters.append(progress)
            if note is not None:
                assignments.append("progress_note = ?")
                parameters.append(note[:300])
            db.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", (*parameters, job_id))
            return bool(row["cancel_requested"])

    def _finish(self, job_id: str, worker: str, status: str, *, result: dict[str, Any] | None = None, error: str = "", run_after: str | None = None) -> bool:
        """Record how a running job ended. False when the job is no longer this worker's (its result is dropped)."""

        moment = now()
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE jobs SET status = ?, result = ?, error = ?, lease_owner = '', lease_until = '', run_after = COALESCE(?, run_after), "
                "progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END, updated_at = ? WHERE id = ? AND status = 'running' AND lease_owner = ?",
                (status, json.dumps(result or {}, ensure_ascii=False, default=str), error[:2000], run_after, status, moment, job_id, worker),
            ).rowcount
        return bool(changed)

    def complete(self, job_id: str, worker: str, result: dict[str, Any] | None = None) -> bool:
        return self._finish(job_id, worker, "done", result=result)

    def fail(self, job_id: str, worker: str, error: str, *, retry: bool = True) -> str:
        """A try failed. Queues the job again after a pause if tries remain; returns the job's new status."""

        job = self.get(job_id)
        if job.cancel_requested:
            self._finish(job_id, worker, "cancelled", error=error or "Cancelled.")
            return "cancelled"
        if retry and job.attempts < job.max_attempts:
            again = _stamp(datetime.now(timezone.utc) + timedelta(seconds=retry_delay(job.attempts)))
            self._finish(job_id, worker, "queued", error=error, run_after=again)
            return "queued"
        self._finish(job_id, worker, "failed", error=error)
        record_event("tool_failure", f"Background job {job.kind} failed for good", job=job_id, job_kind=job.kind, error=error[:300])
        return "failed"

    def recover(self) -> list[str]:
        """Jobs whose worker went silent past its lease: queue them again, or fail them if no try is left."""

        moment = now()
        recovered: list[str] = []
        with self.store.transaction() as db:
            for row in db.execute("SELECT id, attempts, max_attempts, cancel_requested FROM jobs WHERE status = 'running' AND lease_until != '' AND lease_until < ?", (moment,)).fetchall():
                note = "The worker running this job stopped without finishing it."
                if row["cancel_requested"]:
                    status = "cancelled"
                elif row["attempts"] < row["max_attempts"]:
                    status = "queued"
                else:
                    status, note = "failed", note + " No try is left."
                db.execute("UPDATE jobs SET status = ?, lease_owner = '', lease_until = '', error = ?, updated_at = ? WHERE id = ?", (status, note, moment, row["id"]))
                recovered.append(str(row["id"]))
        return recovered

    # ---- a person's side ---------------------------------------------------------------------

    def cancel(self, job_id: str) -> str:
        """Cancel a job. One that is waiting is cancelled now; one that is running is told to stop."""

        moment = now()
        with self.store.transaction() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise StoreError(f"There is no job {job_id}.")
            if row["status"] == "queued":
                db.execute("UPDATE jobs SET status = 'cancelled', error = 'Cancelled before it started.', updated_at = ? WHERE id = ?", (moment, job_id))
                return "cancelled"
            if row["status"] == "running":
                db.execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (moment, job_id))
                return "stopping"
            return str(row["status"])

    def retry(self, job_id: str) -> None:
        """Queue a failed or cancelled job again with a full set of tries."""

        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE jobs SET status = 'queued', attempts = 0, cancel_requested = 0, error = '', run_after = ?, updated_at = ? WHERE id = ? AND status IN ('failed', 'cancelled')",
                (now(), now(), job_id),
            ).rowcount
        if not changed:
            raise StoreError(f"Job {job_id} is not failed or cancelled, so there is nothing to retry.")

    # ---- schedules ---------------------------------------------------------------------------

    def add_schedule(
        self,
        name: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        every_seconds: int = 0,
        daily_at: str = "",
        first_run: datetime | None = None,
    ) -> str:
        """Run a kind of job repeatedly: every N seconds, or every day at HH:MM (local time)."""

        if bool(every_seconds) == bool(daily_at):
            raise StoreError("A schedule needs either every_seconds or daily_at, not both and not neither.")
        if every_seconds and every_seconds < 10:
            raise StoreError("A schedule cannot repeat more often than every 10 seconds.")
        if daily_at:
            try:
                datetime.strptime(daily_at, "%H:%M")
            except ValueError as exc:
                raise StoreError("daily_at is a time of day such as 07:30.") from exc
        schedule_id = new_id("sch")
        start = first_run or (_next_daily(daily_at, datetime.now().astimezone()) if daily_at else datetime.now(timezone.utc) + timedelta(seconds=every_seconds))
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO schedules (id, name, kind, payload, every_seconds, daily_at, next_run, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (schedule_id, name, kind, json.dumps(payload or {}, ensure_ascii=False, default=str), int(every_seconds), daily_at, _stamp(start), now()),
            )
        return schedule_id

    def schedules(self) -> list[dict[str, Any]]:
        return [{**dict(row), "payload": json.loads(row["payload"]), "enabled": bool(row["enabled"])} for row in self.store.read("SELECT * FROM schedules ORDER BY created_at")]

    def set_schedule_enabled(self, schedule_id: str, enabled: bool) -> None:
        with self.store.transaction() as db:
            if not db.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (int(enabled), schedule_id)).rowcount:
                raise StoreError(f"There is no schedule {schedule_id}.")

    def remove_schedule(self, schedule_id: str) -> None:
        with self.store.transaction() as db:
            db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def remember(self, schedule_id: str, value: str) -> str:
        """Keep a small value between the runs of a schedule (what a watched page looked like). Returns the old value."""

        with self.store.transaction() as db:
            row = db.execute("SELECT last_value FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
            if row is None:
                return ""
            db.execute("UPDATE schedules SET last_value = ? WHERE id = ?", (value, schedule_id))
            return str(row["last_value"])

    def tick(self, moment: datetime | None = None) -> list[str]:
        """Enqueue a job for every schedule that is due. Safe to call as often as you like."""

        moment = moment or datetime.now(timezone.utc)
        made: list[str] = []
        for schedule in self.schedules():
            if not schedule["enabled"] or _parse(schedule["next_run"]) > moment:
                continue
            due = schedule["next_run"]
            # The key ties the job to this firing: looking twice, or crashing between the two
            # writes below, cannot make it twice.
            try:
                job_id = self.enqueue(schedule["kind"], {**schedule["payload"], "schedule_id": schedule["id"], "due": due}, idempotency_key=f"{schedule['id']}:{due}", schedule_id=schedule["id"])
            except QueueFull as full:
                # Too much of this kind is already waiting: this firing is skipped, and the user is
                # told once per firing (the notice id is the firing's key).
                job_id = ""
                self.notify("schedule_skipped", f"A scheduled {schedule['kind']} was skipped", str(full), {"schedule_id": schedule["id"], "due": due}, notice_id=f"skipped:{schedule['id']}:{due}")
            if schedule["every_seconds"]:
                following = _parse(due) + timedelta(seconds=schedule["every_seconds"])
                while following <= moment:  # the app was off for a while: one catch-up run, not one per missed firing
                    following += timedelta(seconds=schedule["every_seconds"])
            else:
                following = _next_daily(schedule["daily_at"], moment.astimezone())
            with self.store.transaction() as db:
                if job_id:
                    db.execute("UPDATE schedules SET next_run = ?, last_job = ? WHERE id = ?", (_stamp(following), job_id, schedule["id"]))
                else:
                    db.execute("UPDATE schedules SET next_run = ? WHERE id = ?", (_stamp(following), schedule["id"]))
            if job_id:
                made.append(job_id)
        return made

    # ---- notices -----------------------------------------------------------------------------

    def notify(self, kind: str, title: str, body: str = "", data: dict[str, Any] | None = None, *, notice_id: str | None = None) -> str:
        """Leave a message for the user (a reminder that came due, a page that changed).

        With a notice_id, a second call with the same id writes nothing: a job that is run again
        after a crash does not tell the user twice.
        """

        notice_id = notice_id or new_id("ntc")
        with self.store.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS notices (id TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}', seen INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute("INSERT OR IGNORE INTO notices (id, at, kind, title, body, data) VALUES (?, ?, ?, ?, ?, ?)", (notice_id, now(), kind, title, body, json.dumps(data or {}, ensure_ascii=False, default=str)))
        return notice_id

    def notices(self, unseen_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.transaction() as db:
            if db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'notices'").fetchone() is None:
                return []
            rows = db.execute(f"SELECT * FROM notices {'WHERE seen = 0' if unseen_only else ''} ORDER BY at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "data": json.loads(row["data"]), "seen": bool(row["seen"])} for row in rows]

    def mark_seen(self, notice_id: str) -> None:
        with self.store.transaction() as db:
            db.execute("UPDATE notices SET seen = 1 WHERE id = ?", (notice_id,))


def _next_daily(at: str, after: datetime) -> datetime:
    hour, minute = (int(part) for part in at.split(":"))
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > after else candidate + timedelta(days=1)


Handler = Callable[[Job, JobControl], "dict[str, Any] | None"]


@dataclass
class Worker:
    """Runs jobs from the queue, several at a time up to its capacity."""

    queue: JobQueue
    handlers: dict[str, Handler]
    capacity: int = 2
    kind_limits: dict[str, int] = field(default_factory=dict)
    poll_seconds: float = 1.0
    name: str = field(default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}-{new_id('w')[-6:]}")

    def __post_init__(self) -> None:
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def _run(self, job: Job) -> None:
        control = JobControl(self.queue, job, self.name)
        handler = self.handlers.get(job.kind)
        finished = threading.Event()

        def watch() -> None:
            """Renew the lease while the handler works, and tell it to stop on cancel or time limit."""

            deadline = time.monotonic() + job.timeout_seconds
            while not finished.wait(min(2.0, max(0.2, job.timeout_seconds / 10))):
                if time.monotonic() >= deadline:
                    control.reason = "timeout"
                    control.cancel.set()
                    return
                if self.queue.heartbeat(job.id, self.name):
                    control.reason = control.reason or "cancelled"
                    control.cancel.set()
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            if handler is None:
                self.queue.fail(job.id, self.name, f"Nothing on this machine knows how to do a job of kind {job.kind!r}.", retry=False)
                return
            result = handler(job, control)
            if control.reason == "timeout":
                self.queue.fail(job.id, self.name, f"The job did not finish within its time limit of {job.timeout_seconds:.0f} seconds.")
            elif control.cancel.is_set() and self.queue.get(job.id).cancel_requested:
                self.queue._finish(job.id, self.name, "cancelled", result=result or {}, error="Cancelled while running.")
            else:
                self.queue.complete(job.id, self.name, result or {})
        except JobCancelled as stopped:
            if str(stopped) == "timeout":
                self.queue.fail(job.id, self.name, f"The job did not finish within its time limit of {job.timeout_seconds:.0f} seconds.")
            else:
                self.queue._finish(job.id, self.name, "cancelled", error="Cancelled while running.")
        except Exception as exc:  # a failing job must not take the worker down
            self.queue.fail(job.id, self.name, f"{type(exc).__name__}: {exc}")
        finally:
            finished.set()

    def run_once(self) -> int:
        """Start every job that is due and fits. Returns how many were started."""

        with self._lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            started = 0
            while len(self._threads) < self.capacity:
                job = self.queue.lease(self.name, kinds=set(self.handlers), capacity=self.capacity, kind_limits=self.kind_limits)
                if job is None:
                    break
                thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job.id}")
                thread.start()
                self._threads.append(thread)
                started += 1
            return started

    def run_forever(self, stop: threading.Event) -> None:
        """Recover lost jobs, fire due schedules and run jobs until `stop` is set."""

        while not stop.is_set():
            self.queue.recover()
            self.queue.tick()
            self.run_once()
            stop.wait(self.poll_seconds)
        self.wait(30)

    def wait(self, seconds: float = 30.0) -> bool:
        """Wait for the jobs this worker started. True when all have ended."""

        deadline = time.monotonic() + seconds
        for thread in list(self._threads):
            thread.join(max(0.0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in self._threads)
