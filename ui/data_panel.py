"""The "Your data" panel: what is saved, export, encrypted backup, restore, snapshots, wipe."""

from __future__ import annotations

import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from modules import backup
from modules.backup import BackupError
from modules.data_stores import STORES, get_store, summarize_stores


def format_size(count: int) -> str:
    size = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def store_rows() -> list[dict[str, Any]]:
    """The table of saved data, in plain words."""

    return [
        {
            "Data": row["title"],
            "Files": row["files"],
            "Size": format_size(row["bytes"]),
            "Last changed": row["last_changed"].replace("T", " "),
            "Kind": row["kind"],
            "In backups": "yes" if row["in_backup"] else "no",
        }
        for row in summarize_stores()
    ]


def archive_file_name(encrypted: bool, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    return f"cognitive_nexus_backup_{stamp}.cnbackup" if encrypted else f"cognitive_nexus_export_{stamp}.zip"


def build_archive_bytes(store_keys: list[str], passphrase: str) -> tuple[str, bytes, dict[str, Any]]:
    """Create an archive in temporary storage and return (file name, content, summary)."""

    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / archive_file_name(bool(passphrase))
        summary = backup.create_archive(target, store_keys, passphrase=passphrase or None)
        return target.name, target.read_bytes(), summary


def describe_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"Data": entry.get("title", key), "Files": len(entry.get("files") or [])}
        for key, entry in (manifest.get("stores") or {}).items()
        if entry.get("files")
    ]


def start_daily_snapshot() -> None:
    """Take the automatic daily snapshot in the background; a failure only shows in the event log."""

    def run() -> None:
        try:
            backup.snapshot_if_due()
        except Exception as exc:  # never let housekeeping stop the app
            from modules.event_log import record_event

            record_event("error", "The automatic snapshot failed", error=str(exc))

    threading.Thread(target=run, daemon=True).start()


def render_integrity_warnings() -> None:
    """Tell the user about saved files that can no longer be read, and offer the repair."""

    for index, problem in enumerate(backup.check_integrity()):
        name = Path(problem["file"]).name
        if problem["snapshot"]:
            st.error(f"{problem['title']}: the file {name} is damaged. A readable copy exists in snapshot {problem['snapshot']}.")
            if st.button(f"Repair {name} from that snapshot", key=f"repair_store_{index}"):
                result = backup.repair_from_snapshot(problem)
                st.success(f"Repaired. The damaged file was kept as {Path(result['damaged_copy']).name}.")
                st.rerun()
        else:
            st.error(
                f"{problem['title']}: the file {name} is damaged and no snapshot holds a readable copy. "
                "It was left untouched; restore it from a backup if you have one."
            )


def render_data_panel(demo_safe: bool = False) -> None:
    st.markdown("### Your data")
    st.caption(
        "Everything the app saves on this computer. Locations and details are in docs/DATA_STORES.md. "
        "API keys in .env are never exported."
    )
    st.dataframe(store_rows(), width="stretch", hide_index=True)
    render_integrity_warnings()
    if demo_safe:
        st.info("Export, restore and wipe are hidden in Demo Safe Mode.")
        return

    backup_keys = [store.key for store in STORES if store.in_backup]

    with st.expander("Export or back up", expanded=False):
        chosen = st.multiselect(
            "What to include", backup_keys, default=backup_keys, format_func=lambda key: get_store(key).title, key="data_export_keys"
        )
        first = st.text_input("Passphrase (leave empty for an export anyone can open)", type="password", key="data_export_pass")
        second = st.text_input("Repeat the passphrase", type="password", key="data_export_pass_again") if first else ""
        st.caption("An encrypted backup cannot be opened without its passphrase. There is no way to recover a lost one.")
        if st.button("Create the file", key="data_export_create", disabled=not chosen):
            if first and first != second:
                st.error("The two passphrases are different.")
            else:
                with st.spinner("Collecting your data..."):
                    name, content, summary = build_archive_bytes(chosen, first)
                st.session_state["data_export_ready"] = {"name": name, "content": content, "files": summary["files"], "encrypted": bool(first)}
        ready = st.session_state.get("data_export_ready")
        if ready:
            kind = "Encrypted backup" if ready["encrypted"] else "Export"
            st.success(f"{kind} ready: {ready['files']} file(s), {format_size(len(ready['content']))}.")
            st.download_button("Save it to your computer", ready["content"], file_name=ready["name"], key="data_export_download")

    with st.expander("Restore from a file", expanded=False):
        uploaded = st.file_uploader("Backup or export file", type=["zip", "cnbackup"], key="data_restore_file")
        passphrase = st.text_input("Passphrase, if the file is encrypted", type="password", key="data_restore_pass")
        if uploaded is not None:
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "upload.bin"
                source.write_bytes(uploaded.getvalue())
                try:
                    manifest = backup.verify_archive(source, passphrase or None)
                except BackupError as exc:
                    st.error(str(exc))
                else:
                    st.success(f"The file is intact. Created {str(manifest.get('created_at', ''))[:16].replace('T', ' ')} UTC.")
                    st.dataframe(describe_manifest(manifest), width="stretch", hide_index=True)
                    available = [key for key, entry in manifest["stores"].items() if entry.get("files")]
                    wanted = st.multiselect(
                        "What to restore", available, default=available, format_func=lambda key: get_store(key).title, key="data_restore_keys"
                    )
                    st.caption("What you restore replaces the current data of that kind. A snapshot is taken first, so it can be undone.")
                    if st.button("Restore now", key="data_restore_go", disabled=not wanted):
                        try:
                            result = backup.restore_archive(source, passphrase=passphrase or None, store_keys=wanted)
                        except BackupError as exc:
                            st.error(str(exc))
                        else:
                            st.cache_data.clear()
                            st.cache_resource.clear()
                            st.success(
                                f"Restored {result['files']} file(s). To undo, restore snapshot {result['undo_snapshot']} below. "
                                "Reload the page to see the restored data."
                            )

    with st.expander("Snapshots (local copies for undo)", expanded=False):
        snapshots = backup.list_snapshots()
        if st.button("Take a snapshot now", key="data_snapshot_now"):
            backup.create_snapshot("taken by hand")
            st.rerun()
        if not snapshots:
            st.caption("No snapshots yet. One is taken automatically each day the app runs, and before every restore.")
        else:
            st.dataframe(
                [
                    {"Snapshot": row["id"], "Why": row["reason"], "Files": row["files"], "Size": format_size(row["bytes"])}
                    for row in snapshots
                ],
                width="stretch",
                hide_index=True,
            )
            selected = st.selectbox("Snapshot to restore", [row["id"] for row in snapshots], key="data_snapshot_pick")
            if st.button("Restore this snapshot", key="data_snapshot_restore"):
                result = backup.restore_snapshot(selected)
                st.cache_data.clear()
                st.cache_resource.clear()
                st.success(f"Restored {result['files']} file(s) from {selected}. Reload the page to see them.")

    with st.expander("Wipe data permanently", expanded=False):
        all_keys = [store.key for store in STORES]
        doomed = st.multiselect("What to delete", all_keys, format_func=lambda key: get_store(key).title, key="data_wipe_keys")
        also_snapshots = st.checkbox("Also remove these from local snapshots", value=True, key="data_wipe_snapshots")
        word = st.text_input(f"Type {backup.WIPE_CONFIRMATION} to confirm", key="data_wipe_word")
        st.caption("This cannot be undone. Export first if you may want the data back. Backup files you saved elsewhere are not touched.")
        if st.button("Delete permanently", key="data_wipe_go", disabled=not doomed):
            try:
                result = backup.wipe_stores(doomed, confirm=word, include_snapshots=also_snapshots)
            except BackupError as exc:
                st.error(str(exc))
            else:
                st.cache_data.clear()
                st.cache_resource.clear()
                if "chat_history" in doomed:
                    st.session_state["messages"] = []
                st.success(f"Deleted {result['files']} file(s); {result['removed_from_snapshots']} more removed from snapshots.")
