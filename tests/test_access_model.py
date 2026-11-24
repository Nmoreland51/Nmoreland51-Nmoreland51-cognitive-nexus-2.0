"""The single-owner access model (docs/ACCESS_MODEL.md, item 114): the defaults it states, and that no
way in exists that it does not list."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCESS_MODEL = (REPO_ROOT / "docs" / "ACCESS_MODEL.md").read_text(encoding="utf-8")
# What starting a server looks like in this repository's code.
SERVER_START = re.compile(r"FastAPI\(|uvicorn\.run\(|HTTPServer\(\(|serve_forever\(|Flask\(__name__|[\"']--server\.address")
NOT_SCANNED = ("tests", "legacy", ".git", "docs", "node_modules")


def test_streamlit_run_listens_on_this_computer_only_and_sends_no_usage_statistics():
    config = tomllib.loads((REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["server"]["address"] in {"localhost", "127.0.0.1"}
    assert config["browser"]["gatherUsageStats"] is False


def test_the_launchers_listen_on_this_computer_only(monkeypatch):
    assert "--server.address=localhost" in (REPO_ROOT / "run.py").read_text(encoding="utf-8")
    monkeypatch.delenv("COGNITIVE_NEXUS_HOST", raising=False)
    from cognitive_nexus import config
    from cognitive_nexus.launcher import streamlit_args

    config.get_settings.cache_clear()
    try:
        args = streamlit_args(REPO_ROOT / "app.py", config.get_settings())
    finally:
        config.get_settings.cache_clear()
    assert args[args.index("--server.address") + 1] in {"localhost", "127.0.0.1"}


def test_the_experimental_fullstack_backend_answers_only_its_own_page():
    source = (REPO_ROOT / "fullstack-local" / "backend" / "app.py").read_text(encoding="utf-8")
    assert 'allow_origins=["*"]' not in source and "allow_origins=ALLOWED_ORIGINS" in source
    default = re.search(r'FULLSTACK_ALLOWED_ORIGINS", "([^"]*)"', source)
    assert default and default.group(1).split(",") == ["http://127.0.0.1:8000", "http://localhost:8000"]
    assert '!= "*"' in source  # a "*" put in the setting is ignored


def test_every_file_that_starts_a_server_is_in_the_access_model():
    starting: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.split("/")[0] in NOT_SCANNED or "__pycache__" in relative:
            continue
        if SERVER_START.search(path.read_text(encoding="utf-8", errors="replace")):
            starting.append(relative)
    assert sorted(starting) == ["cognitive_nexus/launcher.py", "fullstack-local/backend/app.py", "run.py"]
    named = {"cognitive_nexus/launcher.py": "cognitive_nexus/launcher.py", "fullstack-local/backend/app.py": "fullstack-local/", "run.py": "python run.py"}
    for relative in starting:
        assert named[relative] in ACCESS_MODEL, f"{relative} starts a server and docs/ACCESS_MODEL.md does not list it"
