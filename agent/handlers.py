"""What the background jobs actually do.

    coding_task   work on a task with the coding agent (agent/coder.py)
    reminder      leave the user a notice at a time they chose
    watch_url     fetch a public page and leave a notice when it has changed since the last look
    snapshot      take the daily local snapshot of the saved data

A handler gets the job and a control object; it returns a small result that is stored with the
job. Each one is safe to run again after a crash: the coding agent continues from its record, a
notice is written under the job's own id (so a second run writes nothing new), and watching
compares against what was stored last time.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from agent.jobs import Handler, Job, JobControl, JobQueue

MAX_WATCH_BYTES = 2_000_000


def coding_task(make_agent: Callable[[], Any]) -> Handler:
    """Run a coding task. `make_agent` builds the agent when the job starts, so the model is only loaded when needed."""

    def handle(job: Job, control: JobControl) -> dict[str, Any]:
        from agent.coder import describe

        agent = make_agent()
        control.progress(0.05, "Starting")
        task = agent.run(str(job.payload["task_id"]), cancel=control.cancel)
        return {"task": task.id, "status": task.status, "summary": describe(task)}

    return handle


def reminder(queue: JobQueue) -> Handler:
    def handle(job: Job, control: JobControl) -> dict[str, Any]:
        title = str(job.payload.get("title") or "Reminder")
        notice = queue.notify("reminder", title, str(job.payload.get("body") or ""), {"job": job.id}, notice_id=f"ntc_{job.id}")
        return {"notice": notice, "title": title}

    return handle


def page_fingerprint(html: str) -> tuple[str, str]:
    """(a hash of what a page says, its text) ignoring markup, scripts and whitespace, which change without the content changing."""

    text = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


def watch_url(queue: JobQueue, fetch: Callable[[str], str] | None = None) -> Handler:
    """Tell the user when a public page changes, or when a phrase appears on it or disappears from it."""

    def get(url: str) -> str:
        from modules.url_safety import safe_get  # refuses local and private addresses, also after redirects

        response = safe_get(url, timeout=20, headers={"User-Agent": "CognitiveNexus/2.0 (change monitor)"})
        response.raise_for_status()
        return response.text[:MAX_WATCH_BYTES]

    def handle(job: Job, control: JobControl) -> dict[str, Any]:
        url = str(job.payload["url"])
        phrase = str(job.payload.get("phrase") or "").strip().lower()
        fingerprint, text = page_fingerprint((fetch or get)(url))
        seen = f"{fingerprint}|{int(phrase in text.lower())}" if phrase else fingerprint
        slot = str(job.payload.get("schedule_id") or "")
        before = queue.remember(slot, seen) if slot else ""
        if not before:
            return {"url": url, "changed": False, "first_look": True}
        if before == seen:
            return {"url": url, "changed": False}
        if phrase:
            had, has = before.endswith("|1"), seen.endswith("|1")
            if had == has:
                return {"url": url, "changed": False, "page_changed": True}
            title = f"\"{job.payload['phrase']}\" {'now appears on' if has else 'is no longer on'} {url}"
        else:
            title = f"{url} has changed"
        notice = queue.notify("page_changed", title, str(job.payload.get("note") or ""), {"url": url, "job": job.id}, notice_id=f"ntc_{job.id}")
        return {"url": url, "changed": True, "notice": notice}

    return handle


def snapshot() -> Handler:
    def handle(job: Job, control: JobControl) -> dict[str, Any]:
        from modules.backup import snapshot_if_due

        taken = snapshot_if_due()
        return {"taken": bool(taken), "snapshot": str((taken or {}).get("id", ""))}

    return handle


def default_handlers(queue: JobQueue, make_agent: Callable[[], Any] | None = None) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {"reminder": reminder(queue), "watch_url": watch_url(queue), "snapshot": snapshot()}
    if make_agent is not None:
        handlers["coding_task"] = coding_task(make_agent)
    return handlers
