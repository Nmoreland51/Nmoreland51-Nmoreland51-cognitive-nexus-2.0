"""Export, encrypted backup, restore, wipe, snapshots and repair, on real files."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from modules import backup, data_stores
from modules.backup import (
    BackupError,
    check_integrity,
    create_archive,
    create_snapshot,
    decrypt_stream,
    encrypt_stream,
    list_snapshots,
    repair_from_snapshot,
    restore_archive,
    restore_snapshot,
    snapshot_if_due,
    verify_archive,
    wipe_stores,
)

SECRET = "The launch code is swordfish"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A separate set of data folders for one test."""

    return _use_home(tmp_path / "home", monkeypatch)


def _use_home(root: Path, monkeypatch) -> Path:
    for name, part in (("data", "data"), ("knowledge", "knowledge_bank"), ("logs", "logs"), ("config", "config")):
        folder = root / part
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setitem(data_stores._ROOT_NAMES, name, folder)
    monkeypatch.setattr(data_stores, "DATA_ROOT", root / "data")
    monkeypatch.setattr(data_stores, "KNOWLEDGE_ROOT", root / "knowledge_bank")
    monkeypatch.setattr(data_stores, "LOG_ROOT", root / "logs")
    monkeypatch.setattr(data_stores, "CONFIG_ROOT", root / "config")
    return root


def fill(home: Path) -> dict[str, str]:
    """Create a little of every kind of data. Returns {relative path: content}."""

    files = {
        "data/chat_history.json": json.dumps({"messages": [{"role": "user", "content": SECRET}]}),
        "data/user_profile.json": json.dumps({"schema_version": 2, "facts": [{"text": "My cat is named Pixel"}]}),
        "data/user_profile.v1.backup.json": json.dumps({"facts": ["old"]}),
        "data/memory_candidates.json": "{}",
        "data/knowledge_notes/project/note.md": "# Note\nremember the milk",
        "data/web_research/20261123_query.json": json.dumps({"query": "streamlit"}),
        "data/images/generated/cat.png": "\x89PNG fake image bytes",
        "data/images/metadata/cat.json": json.dumps({"prompt": "a cat"}),
        "data/search_cache/abc.json": json.dumps({"cached": True}),
        "knowledge_bank/web_research/chunks.json": json.dumps({"a": {"c1": {"text": "chunk"}}}),
        "config/nexus_config.json": json.dumps({"provider_order": ["ollama", "fallback"]}),
        "logs/events.jsonl": '{"kind": "error"}\n',
        "data/user_profile.json.lock": "",
    }
    for relative, content in files.items():
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    return files


def tree(home: Path) -> dict[str, bytes]:
    """Every data file under the home, except snapshots and lock files."""

    found = {}
    for path in home.rglob("*"):
        relative = path.relative_to(home).as_posix()
        if path.is_file() and "_snapshots" not in relative and not relative.endswith(".lock"):
            found[relative] = path.read_bytes()
    return found


def entries(archive_path: Path) -> set[str]:
    with zipfile.ZipFile(archive_path) as archive:
        return set(archive.namelist())


def rewrite(archive_path: Path, change) -> None:
    """Rebuild a zip after letting `change` edit {name: bytes}."""

    with zipfile.ZipFile(archive_path) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    change(content)
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in content.items():
            archive.writestr(name, data)


# --- export ------------------------------------------------------------------------------------------


def test_export_contains_the_data_with_a_checksummed_manifest(home, tmp_path):
    fill(home)

    result = create_archive(tmp_path / "export.zip")

    names = entries(tmp_path / "export.zip")
    assert "files/data/chat_history.json" in names
    assert "files/data/user_profile.v1.backup.json" in names  # companions of a store travel with it
    assert "files/data/knowledge_notes/project/note.md" in names
    assert "files/knowledge/web_research/chunks.json" in names
    assert "files/config/nexus_config.json" in names
    # Caches, logs and lock files are not part of a backup.
    assert not any("search_cache" in name or name.startswith("files/logs") or name.endswith(".lock") for name in names)
    assert result["encrypted"] is False and result["files"] == len(names) - 1
    chat = next(item for item in result["stores"]["chat_history"]["files"] if item["path"] == "files/data/chat_history.json")
    assert chat["bytes"] == (home / "data/chat_history.json").stat().st_size and len(chat["sha256"]) == 64
    assert verify_archive(tmp_path / "export.zip")["format_version"] == 1


def test_export_can_be_limited_to_chosen_kinds_of_data(home, tmp_path):
    fill(home)

    create_archive(tmp_path / "facts.zip", ["user_profile"])

    assert entries(tmp_path / "facts.zip") == {"manifest.json", "files/data/user_profile.json", "files/data/user_profile.v1.backup.json"}
    with pytest.raises(KeyError, match="Unknown data store"):
        create_archive(tmp_path / "bad.zip", ["no_such_store"])


def test_stored_credentials_never_travel(home, tmp_path):
    """Linked accounts are left out of every archive, cannot be asked for by name, and cannot come in through one."""

    fill(home)
    (home / "config" / "accounts.json").write_text(json.dumps({"github": {"source": "stored", "secret": {"how": "plain", "value": "c2VjcmV0"}}}), encoding="utf-8")

    create_archive(tmp_path / "export.zip")
    assert not any("accounts" in name for name in entries(tmp_path / "export.zip"))
    snapshot = create_snapshot("test")
    assert not any("accounts" in name for name in entries(Path(snapshot["path"])))
    with pytest.raises(BackupError, match="hold credentials and are never copied"):
        create_archive(tmp_path / "asked.zip", ["linked_accounts"])
    assert not (tmp_path / "asked.zip").exists()

    planted = tmp_path / "planted.zip"
    create_archive(planted)

    def plant(content: dict[str, bytes]) -> None:
        manifest = json.loads(content["manifest.json"])
        body = b'{"github": {"source": "stored"}}'
        manifest["stores"]["settings"]["files"].append({"path": "files/config/accounts.json", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        content["manifest.json"] = json.dumps(manifest).encode()
        content["files/config/accounts.json"] = body

    rewrite(planted, plant)
    before = (home / "config" / "accounts.json").read_bytes()
    with pytest.raises(BackupError):
        restore_archive(planted)
    assert (home / "config" / "accounts.json").read_bytes() == before


# --- verification refuses anything it cannot vouch for ----------------------------------------------


def test_a_changed_file_inside_the_archive_is_detected(home, tmp_path):
    fill(home)
    archive = tmp_path / "export.zip"
    create_archive(archive)

    rewrite(archive, lambda content: content.__setitem__("files/data/chat_history.json", b'{"messages": []}'))

    with pytest.raises(BackupError, match="does not match its recorded size or checksum"):
        verify_archive(archive)


def test_unlisted_missing_and_misplaced_files_are_refused(home, tmp_path):
    fill(home)

    extra = tmp_path / "extra.zip"
    create_archive(extra)
    rewrite(extra, lambda content: content.__setitem__("files/data/planted.json", b"{}"))
    with pytest.raises(BackupError, match="files its manifest does not list"):
        verify_archive(extra)

    missing = tmp_path / "missing.zip"
    create_archive(missing)
    rewrite(missing, lambda content: content.pop("files/data/chat_history.json"))
    with pytest.raises(BackupError, match="missing files its manifest lists"):
        verify_archive(missing)

    def point_outside(content: dict[str, bytes]) -> None:
        manifest = json.loads(content["manifest.json"])
        manifest["stores"]["chat_history"]["files"].append({"path": "files/data/../../outside.txt", "bytes": 1, "sha256": "0" * 64})
        content["manifest.json"] = json.dumps(manifest).encode()
        content["files/data/../../outside.txt"] = b"x"

    escaping = tmp_path / "escaping.zip"
    create_archive(escaping)
    rewrite(escaping, point_outside)
    with pytest.raises(BackupError, match="where it does not belong"):
        verify_archive(escaping)

    def wrong_store(content: dict[str, bytes]) -> None:
        manifest = json.loads(content["manifest.json"])
        moved = manifest["stores"]["settings"]["files"].pop()
        manifest["stores"]["chat_history"]["files"].append(moved)
        content["manifest.json"] = json.dumps(manifest).encode()

    misfiled = tmp_path / "misfiled.zip"
    create_archive(misfiled)
    rewrite(misfiled, wrong_store)
    with pytest.raises(BackupError, match="where it does not belong"):
        verify_archive(misfiled)

    not_ours = tmp_path / "random.zip"
    with zipfile.ZipFile(not_ours, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(BackupError, match="no readable manifest"):
        verify_archive(not_ours)


# --- encryption --------------------------------------------------------------------------------------


def test_encrypted_backup_hides_the_data_and_needs_the_passphrase(home, tmp_path):
    fill(home)
    archive = tmp_path / "backup.cnbackup"

    result = create_archive(archive, passphrase="correct horse battery staple")

    raw = archive.read_bytes()
    assert result["encrypted"] is True and backup.is_encrypted(archive)
    assert SECRET.encode() not in raw and b"chat_history" not in raw and b"PK" != raw[:2]
    assert not list(tmp_path.glob("*.partial"))  # no unencrypted leftovers next to the backup
    assert verify_archive(archive, "correct horse battery staple")["stores"]["chat_history"]["files"]

    with pytest.raises(BackupError, match="Wrong passphrase"):
        verify_archive(archive, "wrong passphrase")
    with pytest.raises(BackupError, match="encrypted; enter its passphrase"):
        verify_archive(archive)


def test_any_change_to_an_encrypted_backup_is_detected(home, tmp_path):
    fill(home)
    archive = tmp_path / "backup.cnbackup"
    create_archive(archive, passphrase="pw")
    raw = archive.read_bytes()

    flipped = bytearray(raw)
    flipped[len(raw) // 2] ^= 0x01
    archive.write_bytes(bytes(flipped))
    with pytest.raises(BackupError, match="Wrong passphrase, or the backup was changed"):
        verify_archive(archive, "pw")

    archive.write_bytes(raw[:-20])
    with pytest.raises(BackupError, match="cut short"):
        verify_archive(archive, "pw")

    archive.write_bytes(raw + b"extra bytes after the end")
    with pytest.raises(BackupError):
        verify_archive(archive, "pw")

    archive.write_bytes(b"not a backup at all")
    with pytest.raises(BackupError, match="not a readable backup archive"):
        verify_archive(archive, "pw")


def _encrypt(data: bytes, passphrase: str = "pw") -> bytes:
    target = io.BytesIO()
    encrypt_stream(io.BytesIO(data), target, passphrase)
    return target.getvalue()


def _decrypt(blob: bytes, passphrase: str = "pw") -> bytes:
    target = io.BytesIO()
    decrypt_stream(io.BytesIO(blob), target, passphrase)
    return target.getvalue()


def test_stream_encryption_round_trips_across_chunks(monkeypatch):
    monkeypatch.setattr(backup, "_SCRYPT_LOG2_N", 10)  # fast key derivation; the format records it
    monkeypatch.setattr(backup, "_CHUNK", 1000)
    for size in (0, 1, 999, 1000, 1001, 2500, 4000):
        data = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
        assert _decrypt(_encrypt(data)) == data, size


def test_dropped_or_reordered_chunks_are_detected(monkeypatch):
    monkeypatch.setattr(backup, "_SCRYPT_LOG2_N", 10)
    monkeypatch.setattr(backup, "_CHUNK", 1000)
    blob = _encrypt(b"A" * 1000 + b"B" * 1000 + b"C" * 500)
    header, body = blob[: backup._HEADER.size], blob[backup._HEADER.size :]
    size = 4 + 1000 + 16  # length prefix + chunk + authentication tag
    first, second, last = body[:size], body[size : 2 * size], body[2 * size :]

    assert _decrypt(header + first + second + last) == b"A" * 1000 + b"B" * 1000 + b"C" * 500
    for damaged in (header + second + first + last, header + first + last, header + first + second, header + last):
        with pytest.raises(BackupError):
            _decrypt(damaged)


# --- restore -----------------------------------------------------------------------------------------


def test_restore_brings_back_exactly_what_was_backed_up(home, tmp_path):
    fill(home)
    before = tree(home)
    archive = tmp_path / "backup.cnbackup"
    create_archive(archive, passphrase="pw")

    (home / "data/chat_history.json").write_text('{"messages": []}', encoding="utf-8")
    (home / "data/knowledge_notes/project/note.md").unlink()
    (home / "data/knowledge_notes/added_later.md").write_text("new", encoding="utf-8")
    changed = tree(home)

    result = restore_archive(archive, passphrase="pw")

    after = tree(home)
    # Caches and logs are not in a backup, so restoring leaves them as they are.
    assert {name: data for name, data in after.items() if "search_cache" not in name and not name.startswith("logs/")} == {
        name: data for name, data in before.items() if "search_cache" not in name and not name.startswith("logs/")
    }
    assert "data/knowledge_notes/added_later.md" not in after
    assert result["files"] > 5 and result["undo_snapshot"]

    # The restore itself can be undone.
    restore_snapshot(result["undo_snapshot"])
    undone = tree(home)
    assert undone["data/chat_history.json"] == changed["data/chat_history.json"]
    assert "data/knowledge_notes/added_later.md" in undone


def test_restoring_one_kind_of_data_leaves_the_rest_alone(home, tmp_path):
    fill(home)
    archive = tmp_path / "export.zip"
    create_archive(archive)
    (home / "data/chat_history.json").write_text('{"messages": ["newer"]}', encoding="utf-8")
    (home / "data/user_profile.json").write_text('{"schema_version": 2, "facts": []}', encoding="utf-8")

    result = restore_archive(archive, store_keys=["user_profile"])

    assert result["restored_stores"] == ["user_profile"]
    assert "Pixel" in (home / "data/user_profile.json").read_text(encoding="utf-8")
    assert (home / "data/chat_history.json").read_text(encoding="utf-8") == '{"messages": ["newer"]}'


def test_a_failed_restore_puts_the_previous_data_back(home, tmp_path, monkeypatch):
    fill(home)
    archive = tmp_path / "export.zip"
    create_archive(archive)
    (home / "data/chat_history.json").write_text('{"messages": ["newer"]}', encoding="utf-8")
    before = tree(home)
    real_copy = shutil.copyfileobj
    calls = {"count": 0}

    def failing_copy(source, target, *args):
        # Fail on the third file the restore writes, after it has replaced some data.
        if str(getattr(target, "name", "")).endswith(".restore.tmp") and not calls.get("undoing"):
            calls["count"] += 1
            if calls["count"] == 3:
                calls["undoing"] = True
                raise OSError("disk full")
        return real_copy(source, target, *args)

    monkeypatch.setattr(backup.shutil, "copyfileobj", failing_copy)

    with pytest.raises(BackupError, match="previous data was put back"):
        restore_archive(archive)

    assert tree(home) == before


def test_a_damaged_archive_changes_nothing(home, tmp_path):
    fill(home)
    archive = tmp_path / "export.zip"
    create_archive(archive)
    rewrite(archive, lambda content: content.__setitem__("files/data/user_profile.json", b"{}"))
    (home / "data/chat_history.json").write_text('{"messages": ["newer"]}', encoding="utf-8")
    before = tree(home)

    with pytest.raises(BackupError):
        restore_archive(archive)

    assert tree(home) == before
    assert list_snapshots() == []  # nothing was even started


def test_a_backup_restores_on_another_machine_layout(tmp_path, monkeypatch):
    first = _use_home(tmp_path / "old machine", monkeypatch)
    fill(first)
    archive = tmp_path / "moving.cnbackup"
    create_archive(archive, passphrase="pw")

    second = _use_home(tmp_path / "new machine" / "nested", monkeypatch)
    restore_archive(archive, passphrase="pw")

    assert SECRET in (second / "data/chat_history.json").read_text(encoding="utf-8")
    assert (second / "knowledge_bank/web_research/chunks.json").is_file()
    assert (second / "config/nexus_config.json").is_file()


# --- wipe --------------------------------------------------------------------------------------------


def test_wipe_needs_the_confirmation_word(home):
    fill(home)
    before = tree(home)

    for wrong in ("", "delete", "yes"):
        with pytest.raises(BackupError, match="Nothing was deleted"):
            wipe_stores(["chat_history"], confirm=wrong)

    assert tree(home) == before


def test_wipe_removes_the_chosen_data_its_companions_and_its_snapshot_copies(home):
    fill(home)
    create_snapshot("before wipe")

    result = wipe_stores(["user_profile", "knowledge_notes"], confirm="DELETE")

    remaining = tree(home)
    assert not any(name.startswith("data/user_profile") or "knowledge_notes" in name for name in remaining)
    assert "data/chat_history.json" in remaining  # other kinds of data are untouched
    assert not (home / "data/knowledge_notes").exists()
    assert not (home / "data/user_profile.json.lock").exists()
    assert result["wiped"] == {"user_profile": 2, "knowledge_notes": 1}
    assert result["removed_from_snapshots"] == 3

    snapshot = list_snapshots()[0]
    names = entries(Path(snapshot["path"]))
    assert not any("user_profile" in name or "knowledge_notes" in name for name in names)
    assert "files/data/chat_history.json" in names
    assert "user_profile" not in snapshot["stores"] and "chat_history" in snapshot["stores"]
    verify_archive(Path(snapshot["path"]))  # still a consistent archive


def test_wiping_everything_including_snapshots_leaves_no_private_data(home):
    fill(home)
    create_snapshot("one")

    wipe_stores([store.key for store in data_stores.STORES], confirm="DELETE")

    assert tree(home) == {}
    assert not (home / "data/_snapshots").exists()


# --- snapshots and repair ----------------------------------------------------------------------------


def test_snapshots_are_listed_newest_first_and_pruned(home, monkeypatch):
    fill(home)
    monkeypatch.setattr(backup, "SNAPSHOT_KEEP", 2)
    ids = [create_snapshot(f"snapshot {index}")["id"] for index in range(4)]

    listed = list_snapshots()

    assert [row["id"] for row in listed] == [ids[3], ids[2]]
    assert listed[0]["reason"] == "snapshot 3" and listed[0]["files"] > 5
    assert "chat_history" in listed[0]["stores"]


def test_daily_snapshot_is_taken_once_and_only_when_there_is_data(home):
    assert snapshot_if_due() is None  # nothing to protect yet

    fill(home)
    first = snapshot_if_due()
    second = snapshot_if_due()

    assert first is not None and first["reason"] == "daily automatic snapshot"
    assert second is None
    assert len(list_snapshots()) == 1


def test_a_damaged_file_is_found_and_repaired_from_a_snapshot(home):
    fill(home)
    good = (home / "data/user_profile.json").read_text(encoding="utf-8")
    create_snapshot("good state")
    (home / "data/user_profile.json").write_text('{"facts": [{"text": "half-writ', encoding="utf-8")

    problems = check_integrity()

    assert [problem["store"] for problem in problems] == ["user_profile"]
    assert problems[0]["snapshot"] == list_snapshots()[0]["id"]
    assert (home / "data/user_profile.json").read_text(encoding="utf-8").startswith('{"facts": [{"text": "half')  # read-only check

    result = repair_from_snapshot(problems[0])

    assert (home / "data/user_profile.json").read_text(encoding="utf-8") == good
    assert Path(result["damaged_copy"]).read_text(encoding="utf-8").startswith('{"facts": [{"text": "half')
    assert check_integrity() == []


def test_forgetting_a_fact_removes_it_from_snapshots_too(home, monkeypatch):
    from modules import profile_store
    from modules.context_manager import forget_user_fact, load_user_facts, remember_user_fact

    profile = home / "data" / "user_profile.json"
    monkeypatch.setattr(profile_store, "PROFILE_FILE", profile)
    remember_user_fact("My favorite color is teal", path=profile)
    remember_user_fact("My favorite color is red", path=profile)
    remember_user_fact("My sister lives in Seattle", path=profile)
    (home / "data" / "chat_history.json").write_text('{"messages": []}', encoding="utf-8")
    create_snapshot("with the fact")

    result = forget_user_fact("favorite color", path=profile)

    assert result["removed_from_snapshots"] == 2  # the current value and the one it replaced
    assert "in local snapshots" in result["message"]
    snapshot = Path(list_snapshots()[0]["path"])
    with zipfile.ZipFile(snapshot) as archive:
        saved = archive.read("files/data/user_profile.json").decode("utf-8")
    assert "favorite color" not in saved and "teal" not in saved
    assert "My sister lives in Seattle" in saved
    verify_archive(snapshot)  # the snapshot's checksums were updated with it

    # Restoring that snapshot cannot bring the forgotten fact back.
    restore_snapshot(list_snapshots()[0]["id"], ["user_profile"])
    assert load_user_facts(profile) == ["My sister lives in Seattle"]


def test_a_damaged_file_without_a_snapshot_is_reported_and_left_alone(home):
    fill(home)
    (home / "data/chat_history.json").write_text("{broken", encoding="utf-8")

    problems = check_integrity()

    assert len(problems) == 1 and problems[0]["snapshot"] is None
    with pytest.raises(BackupError, match="No snapshot holds a readable copy"):
        repair_from_snapshot(problems[0])
    assert (home / "data/chat_history.json").read_text(encoding="utf-8") == "{broken"
