"""The "Your data" panel: its helpers, and that it renders and wipes through the real UI."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules import backup, data_stores
from ui import data_panel


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "home"
    for name, part in (("data", "data"), ("knowledge", "knowledge_bank"), ("logs", "logs"), ("config", "config")):
        (root / part).mkdir(parents=True, exist_ok=True)
        monkeypatch.setitem(data_stores._ROOT_NAMES, name, root / part)
    monkeypatch.setattr(data_stores, "DATA_ROOT", root / "data")
    monkeypatch.setattr(data_stores, "KNOWLEDGE_ROOT", root / "knowledge_bank")
    monkeypatch.setattr(data_stores, "LOG_ROOT", root / "logs")
    monkeypatch.setattr(data_stores, "CONFIG_ROOT", root / "config")
    (root / "data" / "chat_history.json").write_text(json.dumps({"messages": [{"role": "user", "content": "hello"}]}), encoding="utf-8")
    (root / "data" / "user_profile.json").write_text(json.dumps({"schema_version": 2, "facts": []}), encoding="utf-8")
    return root


def test_sizes_are_written_for_people():
    assert data_panel.format_size(0) == "0 bytes"
    assert data_panel.format_size(1023) == "1023 bytes"
    assert data_panel.format_size(1536) == "1.5 KB"
    assert data_panel.format_size(5 * 1024 * 1024) == "5.0 MB"
    assert data_panel.format_size(3 * 1024**3) == "3.0 GB"


def test_archive_names_say_what_they_are():
    now = datetime(2026, 11, 23, 9, 5)
    assert data_panel.archive_file_name(False, now) == "cognitive_nexus_export_20261123_0905.zip"
    assert data_panel.archive_file_name(True, now) == "cognitive_nexus_backup_20261123_0905.cnbackup"


def test_store_table_lists_every_kind_of_data(home):
    rows = {row["Data"]: row for row in data_panel.store_rows()}

    assert set(rows) == {store.title for store in data_stores.STORES}
    assert rows["Chat history"]["Files"] == 1 and rows["Chat history"]["Size"].endswith("bytes")
    assert rows["Search cache"]["In backups"] == "no"


def test_building_an_export_returns_a_readable_archive(home):
    name, content, summary = data_panel.build_archive_bytes(["chat_history"], "")

    assert name.endswith(".zip") and summary["files"] == 1
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert "files/data/chat_history.json" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert data_panel.describe_manifest(manifest) == [{"Data": "Chat history", "Files": 1}]


def test_building_an_encrypted_backup_hides_the_content(home, tmp_path):
    name, content, _summary = data_panel.build_archive_bytes(["chat_history"], "a passphrase")

    assert name.endswith(".cnbackup") and b"hello" not in content
    saved = tmp_path / name
    saved.write_bytes(content)
    assert backup.verify_archive(saved, "a passphrase")["stores"]["chat_history"]["files"]


def _panel_app():
    from ui.data_panel import render_data_panel

    render_data_panel(False)


def _demo_panel_app():
    from ui.data_panel import render_data_panel

    render_data_panel(True)


def test_panel_renders_and_shows_a_damaged_file(home):
    (home / "data" / "chat_history.json").write_text("{broken", encoding="utf-8")

    app = AppTest.from_function(_panel_app, default_timeout=30).run()

    assert not app.exception
    assert any("Your data" in item.value for item in app.markdown)
    assert any("chat_history.json is damaged" in item.value for item in app.error)
    assert [button.label for button in app.button if "Delete permanently" in button.label]


def test_panel_hides_destructive_actions_in_demo_safe_mode(home):
    app = AppTest.from_function(_demo_panel_app, default_timeout=30).run()

    assert not app.exception
    assert not [button for button in app.button if "Delete" in button.label or "Restore" in button.label]
    assert any("hidden in Demo Safe Mode" in item.value for item in app.info)


def test_wipe_through_the_panel_needs_the_word_and_then_deletes(home):
    app = AppTest.from_function(_panel_app, default_timeout=30).run()
    app.multiselect(key="data_wipe_keys").select("chat_history").run()

    app.button(key="data_wipe_go").click().run()
    assert any("Nothing was deleted" in item.value for item in app.error)
    assert (home / "data" / "chat_history.json").exists()

    app.text_input(key="data_wipe_word").input("DELETE").run()
    app.button(key="data_wipe_go").click().run()

    assert not app.exception
    assert not (home / "data" / "chat_history.json").exists()
    assert (home / "data" / "user_profile.json").exists()
    assert any("Deleted 1 file(s)" in item.value for item in app.success)
