"""Shared test setup."""

from __future__ import annotations

import pytest

from modules import event_log


@pytest.fixture(autouse=True)
def isolated_event_log(tmp_path, monkeypatch):
    """Each test gets an empty event log in its own folder, so tests do not write into logs/
    and counts from one test never leak into another."""

    monkeypatch.setattr(event_log, "EVENT_LOG_FILE", tmp_path / "events.jsonl")
    event_log.reset_events()
    yield
    event_log.reset_events()
