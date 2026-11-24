"""Shared test setup. Tests never read or change the real saved data."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# This must happen before any app module is imported: modules/data_stores.py decides where
# data, knowledge, logs and settings live when it is first loaded.
_TEST_HOME = tempfile.mkdtemp(prefix="cognitive-nexus-tests-")
os.environ["COGNITIVE_NEXUS_HOME"] = _TEST_HOME
for _name in ("COGNITIVE_NEXUS_DATA_DIR", "COGNITIVE_NEXUS_KNOWLEDGE_DIR", "COGNITIVE_NEXUS_LOG_DIR", "COGNITIVE_NEXUS_CONFIG_DIR"):
    os.environ.pop(_name, None)
atexit.register(shutil.rmtree, _TEST_HOME, ignore_errors=True)
# Nothing in the suite may depend on a model server that happens to run on the developer's
# machine. Tests that need Ollama for real read CN_LIVE_OLLAMA_URL and are skipped without it.
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"
os.environ["KNOWLEDGE_EMBEDDING_BACKEND"] = "hash"
os.environ.pop("KNOWLEDGE_EMBEDDING_MODEL", None)

import pytest  # noqa: E402

from modules import event_log  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_event_log(tmp_path, monkeypatch):
    """Each test gets an empty event log in its own folder, so counts from one test never leak
    into another."""

    monkeypatch.setattr(event_log, "EVENT_LOG_FILE", tmp_path / "events.jsonl")
    event_log.reset_events()
    yield
    event_log.reset_events()


@pytest.fixture(autouse=True)
def default_handling_of_outside_text():
    """How outside text is handled is a process-wide setting; every test starts from the default."""

    from core.reality_grounding.prompt_firewall import set_untrusted_mode

    set_untrusted_mode("remove_and_fence")
    yield
    set_untrusted_mode("remove_and_fence")


@pytest.fixture(autouse=True)
def accounts_file_per_test(tmp_path, monkeypatch):
    """Linked accounts are saved in one file; every test gets an empty one of its own."""

    from modules import accounts

    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")


def _workflow_text(text: str, *, for_property: bool = False) -> str:
    """Escape text for a GitHub Actions workflow command."""

    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if for_property else text


def failure_annotations(reports: list, limit: int = 10) -> list[str]:
    """One GitHub Actions error line per failed test: the test's name, and the end of its failure text."""

    lines = []
    for report in reports[:limit]:
        detail = str(getattr(report, "longreprtext", "") or getattr(report, "longrepr", "") or "").strip().splitlines()
        text = "\n".join(detail[-30:])[-3500:] or "failed"
        path, line, _name = report.location
        lines.append(f"::error file={_workflow_text(str(path), for_property=True)},line={int(line or 0) + 1},title={_workflow_text(report.nodeid[-180:], for_property=True)}::{_workflow_text(text)}")
    return lines


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """On GitHub Actions, put each failure on the run's summary page instead of only deep in the log."""

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    failed = list(terminalreporter.stats.get("failed", [])) + list(terminalreporter.stats.get("error", []))
    for line in failure_annotations(failed):
        terminalreporter.write_line(line)
