"""Export, encrypted backup, restore, selective wipe and snapshots of the saved data.

Everything here works from the list in modules/data_stores.py, so a kind of data that is saved
is also a kind that can be exported, backed up, restored and wiped.

An archive is a zip file with a manifest (every file with its size and SHA-256) and the files
under `files/<root>/<path>`, where <root> is data, knowledge, config or logs. Paths are stored
relative to those roots, so an archive made on one machine restores on another.

With a passphrase the whole archive is encrypted (AES-256-GCM, key from scrypt, in chunks so a
truncated or reordered file is detected). Without the passphrase nothing can be read back, and
there is no way to recover it.

Restoring never trusts an archive: every file is checked against the manifest before anything
is touched, only paths that belong to a listed store are written, and the data being replaced is
snapshotted first so the restore can be undone.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import IO, Any, Iterable

from modules import data_stores
from modules.data_stores import STORES, Store, get_store
from modules.event_log import record_event
from modules.file_lock import locked
from modules.file_utils import atomic_write_json

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
SNAPSHOT_KEEP = 7
WIPE_CONFIRMATION = "DELETE"

_MAGIC = b"CNBK1\n"
_SCRYPT_LOG2_N, _SCRYPT_R, _SCRYPT_P = 15, 8, 1
_CHUNK = 1024 * 1024
_HEADER = struct.Struct(f">{len(_MAGIC)}s16sBBB7s")


class BackupError(RuntimeError):
    """The archive is damaged, was changed, has the wrong passphrase or is not ours."""


# --- which files belong to which store ---------------------------------------------------------------


def _roots() -> dict[str, Path]:
    return {
        "data": Path(data_stores.DATA_ROOT),
        "knowledge": Path(data_stores.KNOWLEDGE_ROOT),
        "logs": Path(data_stores.LOG_ROOT),
        "config": Path(data_stores.CONFIG_ROOT),
    }


def _snapshot_root() -> Path:
    return get_store("snapshots").paths()[0]


def _archive_name(path: Path) -> str | None:
    """`files/<root>/<relative>` for a file under one of the roots."""

    resolved = path.resolve()
    best: tuple[int, str] | None = None
    for name, root in _roots().items():
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        depth = len(root.resolve().parts)
        if best is None or depth > best[0]:  # the most specific root wins when one contains another
            best = (depth, f"files/{name}/{relative.as_posix()}")
    return best[1] if best else None


_SQLITE_SIDE_FILES = ("-wal", "-shm", "-journal")


def _store_files(store: Store) -> list[tuple[Path, str]]:
    pairs = []
    for path in store.files():
        # The write-ahead files of a SQLite database are not copied: a consistent copy of the
        # database itself is taken instead (see _add_to_archive).
        if path.name.endswith(_SQLITE_SIDE_FILES):
            continue
        name = _archive_name(path)
        if name:
            pairs.append((path, name))
    return pairs


def _consistent_bytes(path: Path) -> bytes | None:
    """For a SQLite database: its content as one consistent file, even while it is in use.

    Copying the file alone can miss changes that are still in the write-ahead log.
    Returns None for any other file.
    """

    if path.suffix not in {".sqlite3", ".sqlite", ".db"}:
        return None
    import sqlite3

    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30.0)
        try:
            target = sqlite3.connect(str(copy))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        return copy.read_bytes()


def _selected(store_keys: Iterable[str] | None, *, for_backup: bool) -> list[Store]:
    if store_keys is None:
        return [store for store in STORES if store.in_backup or not for_backup]
    return [get_store(key) for key in dict.fromkeys(store_keys)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _owner_of(archive_name: str) -> Store | None:
    """The store an archive entry belongs to, or None when no store claims that path."""

    parts = PurePosixPath(archive_name).parts
    if len(parts) < 3 or parts[0] != "files" or parts[1] not in _roots():
        return None
    root, relative = parts[1], "/".join(parts[2:])
    if any(part in {"..", ""} or ":" in part or part.startswith(("/", "\\")) for part in parts[2:]):
        return None
    for store in STORES:
        for store_root, location in store.locations:
            if store_root != root:
                continue
            if location.endswith("/") or location == "":
                if relative.startswith(location) and relative != location.rstrip("/"):
                    return store
            elif relative == location:
                return store
        for store_root, pattern in store.companions:
            if store_root == root and PurePosixPath(relative).match(pattern):
                return store
    return None


def _target_path(archive_name: str) -> Path:
    parts = PurePosixPath(archive_name).parts
    return _roots()[parts[1]].joinpath(*parts[2:])


# --- encryption --------------------------------------------------------------------------------------


def _derive_key(passphrase: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    if not passphrase:
        raise BackupError("A passphrase is needed.")
    return Scrypt(salt=salt, length=32, n=2**log2_n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">IB", counter, 1 if last else 0)


def encrypt_stream(source: IO[bytes], target: IO[bytes], passphrase: str) -> None:
    """Encrypt `source` into `target`. Chunked, so large archives are not held in memory."""

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, prefix = os.urandom(16), os.urandom(7)
    header = _HEADER.pack(_MAGIC, salt, _SCRYPT_LOG2_N, _SCRYPT_R, _SCRYPT_P, prefix)
    cipher = AESGCM(_derive_key(passphrase, salt, _SCRYPT_LOG2_N, _SCRYPT_R, _SCRYPT_P))
    target.write(header)
    counter = 0
    block = source.read(_CHUNK)
    while True:
        following = source.read(_CHUNK)
        last = not following
        sealed = cipher.encrypt(_nonce(prefix, counter, last), block, header)
        target.write(struct.pack(">I", len(sealed)))
        target.write(sealed)
        if last:
            return
        block = following
        counter += 1


def decrypt_stream(source: IO[bytes], target: IO[bytes], passphrase: str) -> None:
    """Reverse of encrypt_stream. Raises BackupError on a wrong passphrase or any change to the file."""

    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    header = source.read(_HEADER.size)
    if len(header) != _HEADER.size:
        raise BackupError("This is not a Cognitive Nexus encrypted backup (the file is too short).")
    magic, salt, log2_n, r, p, prefix = _HEADER.unpack(header)
    if magic != _MAGIC:
        raise BackupError("This is not a Cognitive Nexus encrypted backup.")
    if not (10 <= log2_n <= 20 and 1 <= r <= 16 and 1 <= p <= 4):
        raise BackupError("The backup header is damaged.")
    cipher = AESGCM(_derive_key(passphrase, salt, log2_n, r, p))
    counter = 0
    finished = False
    while True:
        size_bytes = source.read(4)
        if not size_bytes:
            break
        if finished or len(size_bytes) != 4:
            raise BackupError("The backup has extra or damaged data at the end.")
        (size,) = struct.unpack(">I", size_bytes)
        sealed = source.read(size)
        if len(sealed) != size or size > _CHUNK + 64:
            raise BackupError("The backup is cut short or damaged.")
        for last in (False, True):
            try:
                target.write(cipher.decrypt(_nonce(prefix, counter, last), sealed, header))
            except InvalidTag:
                continue
            finished = last
            break
        else:
            raise BackupError("Wrong passphrase, or the backup was changed or damaged.")
        counter += 1
    if not finished:
        raise BackupError("The backup is cut short: its final part is missing.")


def is_encrypted(path: Path) -> bool:
    with Path(path).open("rb") as handle:
        return handle.read(len(_MAGIC)) == _MAGIC


# --- export and backup -------------------------------------------------------------------------------


def _app_version() -> str:
    try:
        from cognitive_nexus.version import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _write_zip(target: IO[bytes], stores: list[Store], note: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": _app_version(),
        "note": note,
        "stores": {},
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for store in stores:
            entries = []
            for path, name in _store_files(store):
                content = _consistent_bytes(path)
                if content is None:
                    archive.write(path, name)
                    entries.append({"path": name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
                else:
                    archive.writestr(name, content)
                    entries.append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            manifest["stores"][store.key] = {"title": store.title, "files": entries}
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    return manifest


def create_archive(
    destination: Path,
    store_keys: Iterable[str] | None = None,
    *,
    passphrase: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Write the chosen stores (default: everything that belongs in a backup) to `destination`.

    Returns the manifest plus "path", "encrypted" and "files". API keys (.env) are never included.
    """

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stores = [store for store in _selected(store_keys, for_backup=True) if store.key != "snapshots"]
    partial = destination.with_name(destination.name + ".partial")
    try:
        if passphrase:
            # The unencrypted archive only ever exists in the system's temporary storage, never
            # next to the destination (which may be a synced or shared folder).
            with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as plain:
                manifest = _write_zip(plain, stores, note)
                plain.seek(0)
                with partial.open("wb") as target:
                    encrypt_stream(plain, target, passphrase)
        else:
            with partial.open("wb") as handle:
                manifest = _write_zip(handle, stores, note)
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return {
        **manifest,
        "path": str(destination),
        "encrypted": bool(passphrase),
        "files": sum(len(entry["files"]) for entry in manifest["stores"].values()),
    }


def _open_zip(source: Path, passphrase: str | None) -> zipfile.ZipFile:
    source = Path(source)
    if not source.is_file():
        raise BackupError(f"No such backup file: {source.name}")
    if is_encrypted(source):
        if not passphrase:
            raise BackupError("This backup is encrypted; enter its passphrase.")
        buffer = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
        try:
            with source.open("rb") as handle:
                decrypt_stream(handle, buffer, passphrase)
        except Exception:
            buffer.close()
            raise
        buffer.seek(0)
        opened: Any = buffer
    else:
        opened = source
    try:
        return zipfile.ZipFile(opened)
    except zipfile.BadZipFile as exc:
        raise BackupError("The file is not a readable backup archive.") from exc


def verify_archive(source: Path, passphrase: str | None = None) -> dict[str, Any]:
    """Check an archive completely without changing anything. Returns its manifest.

    Raises BackupError when a file is missing, has the wrong size or hash, is not listed in the
    manifest, or would be written outside the known stores.
    """

    with _open_zip(source, passphrase) as archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BackupError("The archive has no readable manifest.") from exc
        if int(manifest.get("format_version") or 0) != FORMAT_VERSION:
            raise BackupError(f"Unsupported backup format {manifest.get('format_version')!r}; this app reads format {FORMAT_VERSION}.")
        listed: dict[str, dict[str, Any]] = {}
        for key, entry in (manifest.get("stores") or {}).items():
            store = get_store(key)
            for item in entry.get("files") or []:
                name = str(item.get("path"))
                owner = _owner_of(name)
                if owner is None or owner.key != store.key:
                    raise BackupError(f"The archive lists '{name}' under '{key}', where it does not belong.")
                listed[name] = item
        present = {info.filename for info in archive.infolist() if not info.is_dir()} - {MANIFEST_NAME}
        extra = sorted(present - set(listed))
        if extra:
            raise BackupError(f"The archive contains files its manifest does not list: {', '.join(extra[:3])}")
        missing = sorted(set(listed) - present)
        if missing:
            raise BackupError(f"The archive is missing files its manifest lists: {', '.join(missing[:3])}")
        for name, item in listed.items():
            digest = hashlib.sha256()
            size = 0
            with archive.open(name) as handle:
                for block in iter(lambda: handle.read(_CHUNK), b""):
                    digest.update(block)
                    size += len(block)
            if size != int(item.get("bytes", -1)) or digest.hexdigest() != item.get("sha256"):
                raise BackupError(f"'{name}' does not match its recorded size or checksum; the archive is damaged or was changed.")
    return manifest


# --- snapshots ---------------------------------------------------------------------------------------


def list_snapshots() -> list[dict[str, Any]]:
    """Local snapshots, newest first."""

    rows: list[dict[str, Any]] = []
    root = _snapshot_root()
    if not root.is_dir():
        return rows
    for folder in sorted((item for item in root.iterdir() if item.is_dir()), reverse=True):
        archive = folder / "snapshot.zip"
        if archive.is_file():
            try:
                info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = {}
            rows.append(
                {
                    "id": folder.name,
                    "created_at": info.get("created_at", ""),
                    "reason": info.get("reason", ""),
                    "stores": info.get("stores", []),
                    "files": info.get("files", 0),
                    "bytes": archive.stat().st_size,
                    "path": str(archive),
                }
            )
    return rows


def create_snapshot(reason: str, store_keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Keep a local copy of the current data so a change can be undone. Old snapshots are pruned."""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    folder = _snapshot_root() / stamp
    folder.mkdir(parents=True, exist_ok=True)
    result = create_archive(folder / "snapshot.zip", store_keys, note=f"snapshot: {reason}")
    info = {
        "created_at": result["created_at"],
        "reason": reason,
        "stores": [key for key, entry in result["stores"].items() if entry["files"]],
        "files": result["files"],
    }
    atomic_write_json(folder / "info.json", info)
    prune_snapshots()
    return {"id": stamp, "path": result["path"], **info}


def prune_snapshots(keep: int | None = None) -> int:
    """Delete all but the newest `keep` snapshots (default SNAPSHOT_KEEP)."""

    removed = 0
    for row in list_snapshots()[max(SNAPSHOT_KEEP if keep is None else keep, 0):]:
        shutil.rmtree(Path(row["path"]).parent, ignore_errors=True)
        removed += 1
    return removed


def snapshot_if_due(max_age_hours: float = 24.0) -> dict[str, Any] | None:
    """Take the daily automatic snapshot when there is data and the newest snapshot is old."""

    snapshots = list_snapshots()
    if snapshots:
        try:
            newest = datetime.fromisoformat(snapshots[0]["created_at"])
            if (datetime.now(timezone.utc) - newest).total_seconds() < max_age_hours * 3600:
                return None
        except (ValueError, TypeError):
            pass
    if not any(_store_files(store) for store in _selected(None, for_backup=True)):
        return None
    return create_snapshot("daily automatic snapshot")


# --- restore -----------------------------------------------------------------------------------------


def restore_archive(
    source: Path,
    *,
    passphrase: str | None = None,
    store_keys: Iterable[str] | None = None,
    snapshot_first: bool = True,
) -> dict[str, Any]:
    """Replace the chosen stores (default: every store in the archive) with the archive's copy.

    The archive is verified in full first. The current data of those stores is snapshotted, and
    put back if anything fails part-way.
    """

    manifest = verify_archive(source, passphrase)
    available = [key for key, entry in manifest["stores"].items() if entry.get("files")]
    wanted = [key for key in (store_keys or available) if key in manifest["stores"]]
    if not wanted:
        raise BackupError("The archive holds none of the requested data.")
    snapshot = create_snapshot("before restore", wanted) if snapshot_first else None
    written = 0
    try:
        with _open_zip(source, passphrase) as archive:
            for key in wanted:
                store = get_store(key)
                _delete_store_files(store)
                for item in manifest["stores"][key]["files"]:
                    target = _target_path(item["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    partial = target.with_name(f".{target.name}.restore.tmp")
                    with archive.open(item["path"]) as incoming, partial.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    os.replace(partial, target)
                    written += 1
    except Exception as exc:
        record_event("error", "Restore failed part-way", error=str(exc))
        if snapshot is not None:
            restore_archive(Path(snapshot["path"]), store_keys=wanted, snapshot_first=False)
            raise BackupError(f"The restore failed and your previous data was put back. Cause: {exc}") from exc
        raise
    return {
        "restored_stores": wanted,
        "files": written,
        "archive_created_at": manifest.get("created_at"),
        "undo_snapshot": snapshot["id"] if snapshot else None,
    }


def restore_snapshot(snapshot_id: str, store_keys: Iterable[str] | None = None) -> dict[str, Any]:
    for row in list_snapshots():
        if row["id"] == snapshot_id:
            return restore_archive(Path(row["path"]), store_keys=store_keys)
    raise BackupError(f"No snapshot named {snapshot_id}.")


# --- wipe --------------------------------------------------------------------------------------------


def _delete_store_files(store: Store) -> int:
    removed = 0
    for path, _name in _store_files(store):
        with locked(path, timeout=5.0):
            path.unlink(missing_ok=True)
        path.with_name(path.name + ".lock").unlink(missing_ok=True)
        for side in _SQLITE_SIDE_FILES:  # leftovers would be applied to a restored database
            path.with_name(path.name + side).unlink(missing_ok=True)
        removed += 1
    # Remove folders the store owns once they are empty; keep the roots themselves.
    for location in store.paths():
        if location.is_dir() and location.resolve() not in {root.resolve() for root in _roots().values()}:
            for folder in [*sorted((item for item in location.rglob("*") if item.is_dir()), reverse=True), location]:
                try:
                    folder.rmdir()
                except OSError:
                    pass  # not empty: something that is not ours is in there
    return removed


def _rewrite_snapshot_without(row: dict[str, Any], keys: set[str]) -> int:
    """Remove the given stores from one snapshot. Returns how many files were dropped."""

    archive_path = Path(row["path"])
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
        doomed = {item["path"] for key in keys for item in manifest["stores"].get(key, {}).get("files", [])}
        if not doomed:
            return 0
        kept = {name: archive.read(name) for name in archive.namelist() if name not in doomed and name != MANIFEST_NAME}
    for key in keys:
        if key in manifest["stores"]:
            manifest["stores"][key]["files"] = []
    replacement = archive_path.with_name("snapshot.zip.partial")
    with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in kept.items():
            archive.writestr(name, content)
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    os.replace(replacement, archive_path)
    info_path = archive_path.parent / "info.json"
    remaining = sum(len(entry["files"]) for entry in manifest["stores"].values())
    atomic_write_json(
        info_path,
        {
            "created_at": manifest.get("created_at", ""),
            "reason": row.get("reason", ""),
            "stores": [key for key, entry in manifest["stores"].items() if entry["files"]],
            "files": remaining,
        },
    )
    if remaining == 0:
        shutil.rmtree(archive_path.parent, ignore_errors=True)
    return len(doomed)


def wipe_stores(store_keys: Iterable[str], *, confirm: str, include_snapshots: bool = True) -> dict[str, Any]:
    """Permanently delete the chosen stores, and by default their copies in local snapshots.

    `confirm` must be the word DELETE. Nothing is kept: export first if you may want it back.
    Backups you exported elsewhere are yours to delete.
    """

    if confirm != WIPE_CONFIRMATION:
        raise BackupError(f'Nothing was deleted. Type {WIPE_CONFIRMATION} to confirm a permanent wipe.')
    keys = [get_store(key).key for key in dict.fromkeys(store_keys)]
    if not keys:
        raise BackupError("Choose at least one kind of data to wipe.")
    from_snapshots = 0
    if include_snapshots and "snapshots" not in keys:
        for row in list_snapshots():
            from_snapshots += _rewrite_snapshot_without(row, set(keys))
    removed = {}
    for key in keys:
        store = get_store(key)
        removed[key] = _delete_store_files(store)
        if key == "snapshots":
            shutil.rmtree(_snapshot_root(), ignore_errors=True)
    return {"wiped": removed, "files": sum(removed.values()), "removed_from_snapshots": from_snapshots}


def forget_in_snapshots(terms: list[str]) -> int:
    """Remove saved facts matching a forget request from the profile copies in local snapshots.

    Without this, "forget ..." would leave the fact readable in snapshots for up to a week.
    Only the matching facts (and the earlier values they replaced) are removed; the rest of each
    snapshot is untouched. Returns the number of fact records removed.
    """

    from modules import profile_store

    name = _archive_name(profile_store.PROFILE_FILE)
    if not terms or not name:
        return 0
    removed = 0
    for row in list_snapshots():
        archive_path = Path(row["path"])
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if name not in archive.namelist():
                    continue
                content = {entry: archive.read(entry) for entry in archive.namelist()}
            profile = json.loads(content[name])
            facts = profile.get("facts") or []
            doomed = {fact.get("id") for fact in facts if isinstance(fact, dict) and profile_store.matches_terms(fact.get("text"), terms)}
            doomed |= {
                fact.get("id")
                for fact in facts
                if isinstance(fact, dict) and (fact.get("superseded_by") in doomed or doomed & set(fact.get("supersedes") or []))
            }
            plain = [fact for fact in facts if not isinstance(fact, dict) and profile_store.matches_terms(fact, terms)]
            if not doomed and not plain:
                continue
            profile["facts"] = [
                fact for fact in facts if (fact.get("id") not in doomed if isinstance(fact, dict) else fact not in plain)
            ]
            for section in ("preferences", "patterns"):
                entries = profile.get(section) or {}
                for key in [key for key, value in entries.items() if profile_store.entry_matches(key, value, terms)]:
                    del entries[key]
            content[name] = json.dumps(profile, indent=2, ensure_ascii=False).encode("utf-8")
            manifest = json.loads(content[MANIFEST_NAME])
            for entry in manifest["stores"].get("user_profile", {}).get("files", []):
                if entry["path"] == name:
                    entry["bytes"] = len(content[name])
                    entry["sha256"] = hashlib.sha256(content[name]).hexdigest()
            content[MANIFEST_NAME] = json.dumps(manifest, indent=2).encode("utf-8")
            replacement = archive_path.with_name("snapshot.zip.partial")
            with zipfile.ZipFile(replacement, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for entry, data in content.items():
                    archive.writestr(entry, data)
            os.replace(replacement, archive_path)
            removed += len(doomed) + len(plain)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
            record_event("error", "A snapshot could not be updated while forgetting a fact", snapshot=row["id"], error=str(exc))
    return removed


# --- integrity ---------------------------------------------------------------------------------------


def check_integrity() -> list[dict[str, Any]]:
    """Find saved JSON files that can no longer be read, and whether a snapshot holds a good copy.

    Read-only: nothing is repaired or replaced here.
    """

    problems = []
    for store in STORES:
        if store.sensitivity in {"cache", "log"}:
            continue
        for path, name in _store_files(store):
            if path.suffix != ".json" or ".damaged-" in path.name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                if text.strip():
                    json.loads(text)
                continue
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                problem = {"store": store.key, "title": store.title, "file": str(path), "archive_path": name, "error": str(exc), "snapshot": None}
            for row in list_snapshots():
                try:
                    with zipfile.ZipFile(row["path"]) as archive:
                        json.loads(archive.read(name))
                except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
                    continue
                problem["snapshot"] = row["id"]
                break
            problems.append(problem)
    return problems


def repair_from_snapshot(problem: dict[str, Any]) -> dict[str, Any]:
    """Put back the snapshot's copy of one damaged file. The damaged file is kept beside it."""

    if not problem.get("snapshot"):
        raise BackupError("No snapshot holds a readable copy of this file.")
    row = next((item for item in list_snapshots() if item["id"] == problem["snapshot"]), None)
    if row is None:
        raise BackupError("That snapshot no longer exists.")
    target = Path(problem["file"])
    kept = target.with_name(f"{target.name}.damaged-{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    with locked(target, timeout=5.0):
        if target.exists():
            shutil.copy2(target, kept)
        with zipfile.ZipFile(row["path"]) as archive:
            content = archive.read(problem["archive_path"])
        partial = target.with_name(f".{target.name}.repair.tmp")
        partial.write_bytes(content)
        os.replace(partial, target)
    record_event("error", f"{target.name} was damaged and was repaired from snapshot {row['id']}", kept=kept.name)
    return {"file": str(target), "from_snapshot": row["id"], "damaged_copy": str(kept)}
