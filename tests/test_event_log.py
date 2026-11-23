"""The event log keeps model failures, fallbacks, search failures and tool failures apart."""

from __future__ import annotations

import json

from modules import event_log


def test_events_are_counted_by_kind():
    event_log.record_event("model_failure", "ollama timed out", provider="ollama")
    event_log.record_event("model_failure", "ollama timed out again", provider="ollama")
    event_log.record_event("tool_failure", "pytest exited 1", tool="run_tests")
    event_log.record_event("search_source_failure", "ddgs rate limited", source="ddgs")

    counts = event_log.event_counts()

    assert counts["model_failure"] == 2
    assert counts["tool_failure"] == 1
    assert counts["search_source_failure"] == 1
    assert counts["provider_fallback"] == 0
    assert set(counts) == set(event_log.EVENT_KINDS)


def test_unknown_kinds_are_kept_as_errors():
    event = event_log.record_event("something_new", "odd")

    assert event["kind"] == "error"
    assert event_log.event_counts()["error"] == 1


def test_recent_events_are_newest_first_and_can_be_filtered():
    event_log.record_event("model_failure", "first")
    event_log.record_event("tool_failure", "second")
    event_log.record_event("model_failure", "third")

    assert [event["message"] for event in event_log.recent_events()] == ["third", "second", "first"]
    assert [event["message"] for event in event_log.recent_events(kind="model_failure")] == ["third", "first"]
    assert len(event_log.recent_events(limit=1)) == 1


def test_events_are_written_as_json_lines():
    event_log.record_event("degraded_mode", "hash embeddings in use", backend="hash", chunks=12)

    lines = event_log.EVENT_LOG_FILE.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["kind"] == "degraded_mode"
    assert saved["backend"] == "hash" and saved["chunks"] == 12
    assert saved["time"].endswith("+00:00")


def test_long_values_are_cut_so_a_prompt_cannot_end_up_in_the_log():
    event = event_log.record_event("error", "x" * 5000, detail="y" * 5000)

    assert len(event["message"]) == 500
    assert len(event["detail"]) == 300


def test_an_unwritable_log_folder_does_not_break_the_app(tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setattr(event_log, "EVENT_LOG_FILE", blocker / "events.jsonl")

    event_log.record_event("error", "still counted")

    assert event_log.event_counts()["error"] == 1
