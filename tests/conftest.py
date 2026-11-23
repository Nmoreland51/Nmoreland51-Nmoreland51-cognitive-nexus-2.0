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
