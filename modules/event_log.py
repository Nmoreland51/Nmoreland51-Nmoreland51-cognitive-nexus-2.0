"""Structured event log that keeps different kinds of trouble apart.

A model that timed out, a tool that failed, a search source that was rate-limited and an answer
that had to be served in degraded mode are different problems. Plain logger lines mix them
together; this records each as a typed event so Diagnostics can count them and a person can see
what actually went wrong.

Events go to memory (for the running app) and to logs/events.jsonl. Prompts and answers are
never recorded here, only what failed and why.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any

from modules.data_stores import LOG_ROOT
from modules.redaction import redact

logger = logging.getLogger(__name__)

EVENT_KINDS = (
    "model_failure",  # a provider was set up and tried, and failed
    "provider_fallback",  # no model answered; the fallback text was served
    "provider_skipped",  # a provider was deliberately not used (for example cloud fallback is off)
    "search_source_failure",  # a web search source errored or was rate-limited
    "tool_failure",  # a tool or command the agent ran failed
    "degraded_mode",  # a feature ran with reduced quality (for example hash embeddings)
    "content_rule",  # a message was not answered under the app's one content rule
    "account",  # a linked account was added, changed, renewed, refused or removed (never the secret)
    "error",  # anything else unexpected
)
EVENT_LOG_FILE = LOG_ROOT / "events.jsonl"
_MAX_RECENT = 300

_lock = threading.Lock()
_counts: Counter[str] = Counter()
_recent: deque[dict[str, Any]] = deque(maxlen=_MAX_RECENT)


def record_event(kind: str, message: str, **fields: Any) -> dict[str, Any]:
    """Record one event. Unknown kinds are stored as "error" so nothing is lost."""

    event: dict[str, Any] = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind if kind in EVENT_KINDS else "error",
        "message": redact(str(message))[:500],
    }
    event.update({key: (value if isinstance(value, (int, float, bool)) or value is None else redact(str(value))[:300]) for key, value in fields.items()})
    with _lock:
        _counts[event["kind"]] += 1
        _recent.append(event)
        try:
            EVENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with EVENT_LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as exc:  # a read-only folder must not break the app
            logger.debug("Could not write %s: %s", EVENT_LOG_FILE, exc)
    return event


def event_counts() -> dict[str, int]:
    """Events seen since the app started, by kind."""

    with _lock:
        return {kind: _counts.get(kind, 0) for kind in EVENT_KINDS}


def recent_events(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    """Most recent events first."""

    with _lock:
        events = [event for event in _recent if kind is None or event["kind"] == kind]
    return list(reversed(events))[: max(0, limit)]


def reset_events() -> None:
    """Clear the in-memory view (used by tests)."""

    with _lock:
        _counts.clear()
        _recent.clear()
