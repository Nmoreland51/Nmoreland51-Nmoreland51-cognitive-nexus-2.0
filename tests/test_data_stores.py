"""The list of saved-data families is complete, documented, and relocatable."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from modules import data_stores
from modules.data_stores import STORES, get_store, render_markdown, summarize_stores

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FOLDERS = ("modules", "core", "search", "cognitive_nexus")
SOURCE_FILES = ("app.py", "web_research_module.py")


def test_tests_run_against_a_throwaway_data_folder_not_the_real_one():
    for root in (data_stores.DATA_ROOT, data_stores.KNOWLEDGE_ROOT, data_stores.LOG_ROOT, data_stores.CONFIG_ROOT):
        resolved = Path(root).resolve()
        assert REPO_ROOT not in resolved.parents and resolved != REPO_ROOT, f"{root} is inside the repository"
    assert "cognitive-nexus-tests-" in str(data_stores.DATA_ROOT)


def test_store_keys_are_unique_and_described():
    keys = [store.key for store in STORES]
    assert len(keys) == len(set(keys))
    for store in STORES:
        assert store.title and store.holds and store.written_by and store.locations
        assert store.sensitivity in {"private", "learned", "settings", "cache", "log"}
    assert get_store("user_profile").title == "Saved facts and preferences"


def _saved_paths_in_code() -> set[tuple[str, str]]:
    """Every `DATA_ROOT / "x"` and `KNOWLEDGE_ROOT / "x"` written in the app's code."""

    pattern = re.compile(r'\b(DATA_ROOT|KNOWLEDGE_ROOT)\s*/\s*"([^"]+)"')
    found: set[tuple[str, str]] = set()
    files = [REPO_ROOT / name for name in SOURCE_FILES]
    for folder in SOURCE_FOLDERS:
        files.extend((REPO_ROOT / folder).rglob("*.py"))
    for path in files:
        if path.name == "data_stores.py":
            continue
        for root, first in pattern.findall(path.read_text(encoding="utf-8")):
            found.add(("data" if root == "DATA_ROOT" else "knowledge", first))
    return found


def test_every_path_the_code_saves_to_belongs_to_a_registered_store():
    """A file saved outside the list would be missed by backup, export and wipe."""

    registered = {(root, relative.rstrip("/").split("/")[0]) for store in STORES for root, relative in store.locations}
    used = _saved_paths_in_code()

    assert used, "the scan found nothing; the pattern no longer matches the code"
    unregistered = sorted(item for item in used if item not in registered)
    assert unregistered == [], f"saved to but not listed in modules/data_stores.py: {unregistered}"


def test_no_module_spells_out_a_data_path_itself():
    offenders = []
    pattern = re.compile(r'Path\(\s*["\'](?:data|ai_system|logs)[/\\"\']')
    files = [REPO_ROOT / name for name in SOURCE_FILES]
    for folder in ("modules", "core", "search"):
        files.extend((REPO_ROOT / folder).rglob("*.py"))
    for path in files:
        if path.name == "data_stores.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_documentation_matches_the_registry():
    document = (REPO_ROOT / "docs" / "DATA_STORES.md").read_text(encoding="utf-8")

    assert document == render_markdown(), "run: python tools/render_data_stores.py"
    for store in STORES:
        assert f"`{store.key}`" in document
    assert "D:\\" not in document and "C:\\" not in document  # no machine-specific paths


def test_store_files_include_companions_and_skip_lock_files():
    data = Path(data_stores.DATA_ROOT)
    data.mkdir(parents=True, exist_ok=True)
    made = [data / "user_profile.json", data / "user_profile.v1.backup.json", data / "user_profile.json.damaged-20261123_010101"]
    lock = data / "user_profile.json.lock"
    notes = data / "knowledge_notes" / "a" / "note.md"
    try:
        for path in [*made, lock, notes]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

        profile_files = get_store("user_profile").files()
        assert {path.name for path in profile_files} == {path.name for path in made}
        assert get_store("knowledge_notes").files() == [notes]

        rows = {row["key"]: row for row in summarize_stores()}
        assert rows["user_profile"]["files"] == 3 and rows["user_profile"]["bytes"] == 3
        assert rows["user_profile"]["last_changed"]
        assert rows["search_cache"]["in_backup"] is False
    finally:
        for path in [*made, lock, notes]:
            path.unlink(missing_ok=True)


def _roots_with(env: dict[str, str]) -> list[str]:
    clean = {key: value for key, value in os.environ.items() if not key.startswith("COGNITIVE_NEXUS_")}
    script = "from modules import data_stores as d; print(d.DATA_ROOT); print(d.KNOWLEDGE_ROOT); print(d.LOG_ROOT); print(d.CONFIG_ROOT)"
    output = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, env={**clean, **env}, capture_output=True, text=True, check=True
    ).stdout
    return [line.strip() for line in output.splitlines()]


def test_default_locations_are_the_ones_the_app_always_used():
    data, knowledge, logs, config = _roots_with({})

    assert Path(data) == Path("data")
    assert Path(knowledge) == Path("ai_system/knowledge_bank")
    assert Path(logs) == REPO_ROOT / "logs"
    assert Path(config) == REPO_ROOT / "config"


def test_home_variable_moves_everything_and_single_folders_can_be_overridden(tmp_path):
    home = tmp_path / "nexus home"
    elsewhere = tmp_path / "logs elsewhere"

    data, knowledge, logs, config = _roots_with({"COGNITIVE_NEXUS_HOME": str(home), "COGNITIVE_NEXUS_LOG_DIR": str(elsewhere)})

    assert Path(data) == home / "data"
    assert Path(knowledge) == home / "knowledge_bank"
    assert Path(config) == home / "config"
    assert Path(logs) == elsewhere
