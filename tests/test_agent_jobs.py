"""The job queue and scheduler: work that is taken, reported, retried, cancelled, limited and never lost."""

from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from agent.handlers import default_handlers, page_fingerprint, watch_url
from agent.jobs import JobCancelled, JobQueue, Worker, retry_delay
from agent.store import AgentStore, StoreError
from modules import event_log


@pytest.fixture
def store(tmp_path):
    made = AgentStore(tmp_path / "agent.db")
    yield made
    made.close()


@pytest.fixture
def queue(store):
    return JobQueue(store)


def wait_for(condition, seconds=20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def set_fields(store, job_id, **fields):
    with store.transaction() as db:
        for name, value in fields.items():
            db.execute(f"UPDATE jobs SET {name} = ? WHERE id = ?", (value, job_id))


# ---- taking and finishing -----------------------------------------------------------------------------


def test_a_job_is_taken_worked_on_and_finished(queue):
    job_id = queue.enqueue("report", {"month": "November"})
    assert queue.get(job_id).status == "queued" and queue.counts() == {"queued": 1}
    job = queue.lease("worker-a")
    assert job is not None and (job.id, job.status, job.attempts, job.lease_owner, job.payload) == (job_id, "running", 1, "worker-a", {"month": "November"})
    assert queue.lease("worker-b") is None  # nothing else to take, and this one is spoken for
    assert queue.heartbeat(job_id, "worker-a", progress=0.5, note="half way") is False
    assert (queue.get(job_id).progress, queue.get(job_id).progress_note) == (0.5, "half way")
    assert queue.complete(job_id, "worker-a", {"pages": 3})
    done = queue.get(job_id)
    assert (done.status, done.result, done.progress, done.lease_owner) == ("done", {"pages": 3}, 1.0, "")
    with pytest.raises(StoreError):
        queue.get("job_missing")
    with pytest.raises(StoreError, match="needs a kind"):
        queue.enqueue(" ")


def test_the_most_urgent_job_that_is_due_goes_first(queue):
    later = queue.enqueue("a", delay_seconds=3600)
    low = queue.enqueue("a", priority=0)
    high = queue.enqueue("a", priority=5)
    assert [queue.lease("w", capacity=10).id for _ in range(2)] == [high, low]
    assert queue.lease("w", capacity=10) is None and queue.get(later).status == "queued"
    soon = queue.enqueue("a", run_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert queue.lease("w", capacity=10).id == soon


def test_the_same_request_twice_is_one_job(queue):
    first = queue.enqueue("email_digest", {"day": "Monday"}, idempotency_key="digest:2026-11-23")
    second = queue.enqueue("email_digest", {"day": "Monday"}, idempotency_key="digest:2026-11-23")
    assert first == second and len(queue.jobs()) == 1
    assert queue.enqueue("email_digest", idempotency_key="digest:2026-11-24") != first
    assert queue.enqueue("email_digest") != queue.enqueue("email_digest")  # without a key each is its own job


# ---- failing, retrying, recovering ----------------------------------------------------------------------


def test_a_failed_try_is_repeated_later_and_gives_up_after_the_last(queue, store):
    event_log.reset_events()
    assert [retry_delay(attempts) for attempts in (1, 2, 3, 8, 20)] == [5.0, 10.0, 20.0, 600.0, 600.0]
    job_id = queue.enqueue("flaky", max_attempts=2)
    queue.lease("w")
    before = datetime.now(timezone.utc)
    assert queue.fail(job_id, "w", "connection reset") == "queued"
    waiting = queue.get(job_id)
    assert waiting.status == "queued" and waiting.error == "connection reset" and waiting.attempts == 1
    assert datetime.fromisoformat(waiting.run_after) >= before + timedelta(seconds=4)
    assert queue.lease("w") is None  # not due yet
    set_fields(store, job_id, run_after=before.isoformat(timespec="milliseconds"))
    assert queue.lease("w").attempts == 2
    assert queue.fail(job_id, "w", "connection reset again") == "failed"
    assert queue.get(job_id).status == "failed"
    assert event_log.event_counts().get("tool_failure") == 1
    queue.retry(job_id)
    assert (queue.get(job_id).status, queue.get(job_id).attempts) == ("queued", 0)
    with pytest.raises(StoreError, match="nothing to retry"):
        queue.retry(job_id)


def test_a_job_whose_worker_died_is_taken_again(queue, store):
    job_id = queue.enqueue("long", max_attempts=2)
    queue.lease("worker-that-dies")
    assert queue.recover() == []  # its lease has not run out
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="milliseconds")
    set_fields(store, job_id, lease_until=past)
    assert queue.recover() == [job_id]
    assert queue.get(job_id).status == "queued" and "stopped without finishing" in queue.get(job_id).error
    # The dead worker comes back to life and reports: too late, the job is no longer its own.
    assert queue.heartbeat(job_id, "worker-that-dies") is True
    assert queue.complete(job_id, "worker-that-dies", {"stale": True}) is False
    second = queue.lease("worker-b")
    assert second.id == job_id and second.attempts == 2
    set_fields(store, job_id, lease_until=past)
    queue.recover()
    assert queue.get(job_id).status == "failed" and "No try is left" in queue.get(job_id).error


def test_jobs_are_still_there_after_the_app_restarts(tmp_path):
    path = tmp_path / "agent.db"
    first = AgentStore(path)
    queue = JobQueue(first)
    waiting = queue.enqueue("report", {"n": 1})
    running = queue.enqueue("report", {"n": 2}, priority=1)
    queue.lease("old-process")
    queue.add_schedule("nightly", "report", every_seconds=3600)
    first.close()

    again = AgentStore(path)
    queue = JobQueue(again)
    assert {job.id: job.status for job in queue.jobs()} == {waiting: "queued", running: "running"}
    assert [item["name"] for item in queue.schedules()] == ["nightly"]
    again.close()


# ---- workers ------------------------------------------------------------------------------------------


def test_a_worker_runs_jobs_and_stores_what_they_return(queue):
    seen = []

    def handler(job, control):
        control.progress(0.5, "working")
        seen.append(job.payload["n"])
        return {"doubled": job.payload["n"] * 2}

    worker = Worker(queue, {"double": handler}, capacity=3)
    ids = [queue.enqueue("double", {"n": number}) for number in (1, 2, 3)]
    assert worker.run_once() == 3 and worker.wait(20)
    assert sorted(seen) == [1, 2, 3]
    assert [queue.get(job_id).result for job_id in ids] == [{"doubled": 2}, {"doubled": 4}, {"doubled": 6}]
    assert worker.run_once() == 0


def test_a_handler_that_raises_does_not_stop_the_worker(queue):
    def handler(job, control):
        if job.payload.get("bad"):
            raise ValueError("cannot parse the input")
        return {"ok": True}

    worker = Worker(queue, {"work": handler})
    bad = queue.enqueue("work", {"bad": True}, max_attempts=1)
    good = queue.enqueue("work", {})
    unknown = queue.enqueue("nobody_knows_this", max_attempts=5)
    worker.run_once()
    worker.wait(20)
    assert (queue.get(bad).status, queue.get(bad).error) == ("failed", "ValueError: cannot parse the input")
    assert queue.get(good).status == "done"
    # A kind no handler exists for is not taken by this worker at all, and stays for one that can.
    assert queue.get(unknown).status == "queued"
    assert Worker(queue, {}).run_once() == 0


def test_capacity_limits_how_many_jobs_run_at_once(queue):
    release = threading.Event()
    running = []

    def handler(job, control):
        running.append(job.id)
        release.wait(20)
        return {}

    worker = Worker(queue, {"slow": handler, "coding_task": handler}, capacity=2)
    for _ in range(3):
        queue.enqueue("slow")
    assert worker.run_once() == 2
    assert wait_for(lambda: len(running) == 2)
    assert worker.run_once() == 0 and queue.counts() == {"queued": 1, "running": 2}
    release.set()
    worker.wait(20)
    assert worker.run_once() == 1 and worker.wait(20)
    assert queue.counts() == {"done": 3}


def test_only_one_model_heavy_job_runs_at_a_time(queue):
    release = threading.Event()
    started = []

    def handler(job, control):
        started.append(job.kind)
        release.wait(20)
        return {}

    worker = Worker(queue, {"coding_task": handler, "reminder": handler}, capacity=4)
    first, second = queue.enqueue("coding_task"), queue.enqueue("coding_task")
    light = queue.enqueue("reminder")
    worker.run_once()
    assert wait_for(lambda: len(started) == 2)
    assert sorted(started) == ["coding_task", "reminder"]
    assert {queue.get(first).status, queue.get(second).status} == {"running", "queued"} and queue.get(light).status == "running"
    release.set()
    worker.wait(20)
    worker.run_once()
    worker.wait(20)
    assert queue.counts() == {"done": 3}
    # The limit is a setting: two at once on a machine that can take it.
    assert Worker(queue, {"coding_task": handler}, capacity=4, kind_limits={"coding_task": 2}).kind_limits == {"coding_task": 2}


# ---- cancelling and time limits ----------------------------------------------------------------------


def test_cancelling_a_waiting_job_and_a_running_one(queue):
    waiting = queue.enqueue("work", delay_seconds=3600)
    assert queue.cancel(waiting) == "cancelled" and queue.get(waiting).status == "cancelled"
    entered, stopped = threading.Event(), threading.Event()

    def handler(job, control):
        entered.set()
        try:
            while True:
                control.check()
                time.sleep(0.05)
        except JobCancelled:
            stopped.set()
            raise

    worker = Worker(queue, {"work": handler})
    running = queue.enqueue("work")
    worker.run_once()
    assert entered.wait(10)
    assert queue.cancel(running) == "stopping"
    assert stopped.wait(15) and worker.wait(15)
    assert queue.get(running).status == "cancelled"
    assert queue.cancel(running) == "cancelled"  # asking again changes nothing
    with pytest.raises(StoreError):
        queue.cancel("job_missing")


def test_a_job_that_overruns_its_time_limit_is_stopped_and_tried_again(queue):
    def handler(job, control):
        while True:
            control.check()
            time.sleep(0.05)

    worker = Worker(queue, {"stuck": handler})
    job_id = queue.enqueue("stuck", timeout_seconds=1.0, max_attempts=2)
    worker.run_once()
    assert worker.wait(20)
    after = queue.get(job_id)
    assert after.status == "queued" and "time limit of 1 seconds" in after.error and after.attempts == 1


# ---- schedules -----------------------------------------------------------------------------------------


def test_a_schedule_makes_one_job_per_firing_however_often_it_is_checked(queue):
    start = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    schedule = queue.add_schedule("Check mail", "check_mail", {"folder": "inbox"}, every_seconds=600, first_run=start)
    assert queue.tick(start - timedelta(seconds=1)) == []
    made = queue.tick(start + timedelta(seconds=5))
    assert len(made) == 1 and queue.tick(start + timedelta(seconds=6)) == [] and queue.tick(start + timedelta(seconds=7)) == []
    job = queue.get(made[0])
    assert job.kind == "check_mail" and job.payload["folder"] == "inbox" and job.payload["schedule_id"] == schedule and job.schedule_id == schedule
    assert queue.schedules()[0]["next_run"].startswith("2026-11-23T12:10:00")
    assert len(queue.tick(start + timedelta(seconds=605))) == 1
    # The computer was off for a day: one catch-up run, not one for each firing that was missed.
    after_a_day = queue.tick(start + timedelta(days=1, seconds=30))
    assert len(after_a_day) == 1 and len(queue.jobs()) == 3
    assert queue.schedules()[0]["next_run"].startswith("2026-11-24T12:10:00")


def test_a_firing_is_not_made_twice_if_the_app_died_between_its_two_writes(queue, store):
    start = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    schedule = queue.add_schedule("Check mail", "check_mail", every_seconds=600, first_run=start)
    made = queue.tick(start)
    with store.transaction() as db:  # as if the job was written but the schedule's next time was not
        db.execute("UPDATE schedules SET next_run = ? WHERE id = ?", (start.isoformat(timespec="milliseconds"), schedule))
    assert queue.tick(start + timedelta(seconds=1)) == made
    assert len(queue.jobs()) == 1


def test_daily_schedules_switching_off_and_what_is_refused(queue):
    daily = queue.add_schedule("Morning summary", "summary", daily_at="07:30")
    next_run = datetime.fromisoformat(queue.schedules()[0]["next_run"]).astimezone()
    assert (next_run.hour, next_run.minute) == (7, 30) and next_run > datetime.now().astimezone()
    queue.set_schedule_enabled(daily, False)
    assert queue.tick(datetime.now(timezone.utc) + timedelta(days=2)) == []
    queue.set_schedule_enabled(daily, True)
    assert len(queue.tick(datetime.now(timezone.utc) + timedelta(days=2))) == 1
    queue.remove_schedule(daily)
    assert queue.schedules() == []
    for arguments, complaint in (({}, "either every_seconds or daily_at"), ({"every_seconds": 60, "daily_at": "07:30"}, "either every_seconds or daily_at"), ({"every_seconds": 2}, "more often than every 10 seconds"), ({"daily_at": "7.30am"}, "time of day")):
        with pytest.raises(StoreError, match=complaint):
            queue.add_schedule("x", "y", **arguments)
    with pytest.raises(StoreError, match="no schedule"):
        queue.set_schedule_enabled("sch_missing", True)


# ---- what the built-in jobs do --------------------------------------------------------------------


def test_a_reminder_becomes_one_notice_even_if_its_job_runs_twice(queue):
    worker = Worker(queue, default_handlers(queue))
    job_id = queue.enqueue("reminder", {"title": "Call the dentist", "body": "Before five"})
    worker.run_once()
    assert worker.wait(20)
    assert [(notice["title"], notice["body"], notice["seen"]) for notice in queue.notices()] == [("Call the dentist", "Before five", False)]
    with queue.store.transaction() as db:  # the app died after telling the user and before recording that it had
        db.execute("UPDATE jobs SET status = 'queued', attempts = 0 WHERE id = ?", (job_id,))
    worker.run_once()
    worker.wait(20)
    assert len(queue.notices()) == 1
    queue.mark_seen(queue.notices()[0]["id"])
    assert queue.notices(unseen_only=True) == []


def test_a_reminder_set_for_later_waits_until_then(queue):
    worker = Worker(queue, default_handlers(queue))
    queue.enqueue("reminder", {"title": "Later"}, delay_seconds=3600)
    assert worker.run_once() == 0 and queue.notices() == []


def test_watching_a_page_reports_a_change_in_what_it_says_only(queue):
    pages = {"now": "<html><body><h1>Release 1.0</h1><script>var t=1</script></body></html>"}
    worker = Worker(queue, {"watch_url": watch_url(queue, fetch=lambda url: pages["now"])})
    start = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    queue.add_schedule("Watch releases", "watch_url", {"url": "https://example.org/releases"}, every_seconds=600, first_run=start)

    def look(minutes):
        made = queue.tick(start + timedelta(minutes=minutes, seconds=1))
        worker.run_once()
        assert worker.wait(20)
        return queue.get(made[0]).result

    assert look(0) == {"url": "https://example.org/releases", "changed": False, "first_look": True}
    assert look(10)["changed"] is False
    pages["now"] = "<html><body>\n  <h1>Release 1.0</h1>\n<script>var t=99</script><!-- build 7 --></body></html>"
    assert look(20)["changed"] is False  # only markup and a script changed
    pages["now"] = "<html><body><h1>Release 1.1</h1></body></html>"
    assert look(30)["changed"] is True
    assert [notice["title"] for notice in queue.notices()] == ["https://example.org/releases has changed"]
    assert look(40)["changed"] is False
    assert page_fingerprint("<p>a  b</p>")[0] == page_fingerprint("<div>a b</div>")[0] != page_fingerprint("<p>a c</p>")[0]


def test_watching_for_a_phrase_reports_when_it_appears_and_when_it_goes(queue):
    pages = {"now": "<p>Tickets: sold out</p>"}
    worker = Worker(queue, {"watch_url": watch_url(queue, fetch=lambda url: pages["now"])})
    start = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    queue.add_schedule("Tickets", "watch_url", {"url": "https://example.org/t", "phrase": "Available"}, every_seconds=600, first_run=start)

    def look(minutes):
        made = queue.tick(start + timedelta(minutes=minutes, seconds=1))
        worker.run_once()
        worker.wait(20)
        return queue.get(made[0]).result

    look(0)
    pages["now"] = "<p>Tickets: sold out. Updated today.</p>"
    assert look(10) == {"url": "https://example.org/t", "changed": False, "page_changed": True}
    pages["now"] = "<p>Tickets: available now</p>"
    assert look(20)["changed"] is True
    pages["now"] = "<p>Tickets: sold out again</p>"
    assert look(30)["changed"] is True
    assert [notice["title"] for notice in queue.notices()] == ['"Available" is no longer on https://example.org/t', '"Available" now appears on https://example.org/t']


def test_a_page_that_cannot_be_fetched_is_a_failed_try_not_a_change(queue):
    def unreachable(url):
        raise ConnectionError("no route to host")

    worker = Worker(queue, {"watch_url": watch_url(queue, fetch=unreachable)})
    job_id = queue.enqueue("watch_url", {"url": "https://example.org/x"}, max_attempts=3)
    worker.run_once()
    worker.wait(20)
    assert queue.get(job_id).status == "queued" and "no route to host" in queue.get(job_id).error
    assert queue.notices() == []


def test_the_page_watcher_refuses_addresses_on_the_local_network(queue):
    worker = Worker(queue, default_handlers(queue))
    job_id = queue.enqueue("watch_url", {"url": "http://127.0.0.1:1/admin"}, max_attempts=1)
    worker.run_once()
    assert worker.wait(30)
    assert queue.get(job_id).status == "failed" and queue.notices() == []


# ---- a coding task as a background job -------------------------------------------------------------


def test_a_coding_task_runs_as_a_background_job(queue, store, tmp_path):
    from agent.coder import default_agent
    from agent.model import ScriptedModel
    from agent.workspace import WorkspaceManager

    repo = tmp_path / "project"
    repo.mkdir()
    for arguments in (["init", "-q", "-b", "main"], ["config", "user.name", "T"], ["config", "user.email", "t@example.org"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *arguments], cwd=repo, check=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)
    fix = "Wrong operator.\n\nFILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"

    def make_agent():
        model = ScriptedModel(lambda prompt: "APPROVE" if "reviewing a code change" in prompt else fix, name="scripted")
        return default_agent(store, model, workspaces=WorkspaceManager(tmp_path / "ws"))

    task = store.create_task("Fix add()", repo=str(repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]])
    worker = Worker(queue, default_handlers(queue, make_agent))
    job_id = queue.enqueue("coding_task", {"task_id": task.id}, timeout_seconds=600)
    worker.run_once()
    assert worker.wait(120)
    job = queue.get(job_id)
    assert job.status == "done" and job.result["status"] == "review" and job.result["summary"].startswith("Ready for review")
    assert store.get_task(task.id).status == "review"
