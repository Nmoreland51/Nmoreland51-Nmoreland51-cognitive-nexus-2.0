"""Export, back up, restore and wipe the saved data from the command line.

    python tools/data_tool.py list
    python tools/data_tool.py export my_data.zip [--only user_profile chat_history]
    python tools/data_tool.py backup my_data.cnbackup          (asks for a passphrase)
    python tools/data_tool.py verify my_data.cnbackup
    python tools/data_tool.py restore my_data.cnbackup [--only user_profile]
    python tools/data_tool.py snapshot
    python tools/data_tool.py check
    python tools/data_tool.py wipe chat_history search_cache   (asks you to type DELETE)

The passphrase is read from the keyboard, or from the CN_BACKUP_PASSPHRASE environment variable
when the tool is run by a script. It is never taken from the command line, where other programs
and the shell history could see it.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules import backup  # noqa: E402
from modules.data_stores import STORES, summarize_stores  # noqa: E402


def _passphrase(confirm: bool) -> str:
    from_env = os.environ.get("CN_BACKUP_PASSPHRASE")
    if from_env:
        return from_env
    first = getpass.getpass("Passphrase: ")
    if confirm and getpass.getpass("Repeat the passphrase: ") != first:
        raise SystemExit("The two passphrases are different. Nothing was written.")
    return first


def _needs_passphrase(path: Path) -> bool:
    return path.is_file() and backup.is_encrypted(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show every kind of saved data and its size")
    for name, text in (("export", "write an unencrypted zip"), ("backup", "write an encrypted backup")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("file", type=Path)
        sub.add_argument("--only", nargs="+", metavar="STORE", help="limit to these kinds of data")
    sub = commands.add_parser("verify", help="check an archive without changing anything")
    sub.add_argument("file", type=Path)
    sub = commands.add_parser("restore", help="replace current data with an archive's copy")
    sub.add_argument("file", type=Path)
    sub.add_argument("--only", nargs="+", metavar="STORE")
    commands.add_parser("snapshot", help="take a local snapshot now")
    commands.add_parser("check", help="look for saved files that can no longer be read")
    sub = commands.add_parser("wipe", help="permanently delete kinds of data")
    sub.add_argument("stores", nargs="+", metavar="STORE")
    sub.add_argument("--keep-snapshots", action="store_true", help="leave the copies in local snapshots")
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            for row in summarize_stores():
                backed_up = "" if row["in_backup"] else "  (not in backups)"
                print(f"{row['key']:<18} {row['files']:>5} file(s) {row['bytes']:>12} bytes  {row['title']}{backed_up}")
        elif args.command in {"export", "backup"}:
            passphrase = _passphrase(confirm=True) if args.command == "backup" else None
            result = backup.create_archive(args.file, args.only, passphrase=passphrase)
            kind = "Encrypted backup" if result["encrypted"] else "Export"
            print(f"{kind} written: {result['path']} ({result['files']} files)")
        elif args.command == "verify":
            manifest = backup.verify_archive(args.file, _passphrase(confirm=False) if _needs_passphrase(args.file) else None)
            files = sum(len(entry["files"]) for entry in manifest["stores"].values())
            print(f"Intact: {files} files, created {manifest.get('created_at')}")
        elif args.command == "restore":
            passphrase = _passphrase(confirm=False) if _needs_passphrase(args.file) else None
            result = backup.restore_archive(args.file, passphrase=passphrase, store_keys=args.only)
            print(f"Restored {result['files']} files into: {', '.join(result['restored_stores'])}")
            print(f"To undo: the previous data is in snapshot {result['undo_snapshot']}")
        elif args.command == "snapshot":
            result = backup.create_snapshot("taken from the command line")
            print(f"Snapshot {result['id']}: {result['files']} files")
        elif args.command == "check":
            problems = backup.check_integrity()
            for problem in problems:
                recover = f"readable copy in snapshot {problem['snapshot']}" if problem["snapshot"] else "no snapshot has a readable copy"
                print(f"DAMAGED {problem['file']}: {problem['error']} ({recover})")
            print("All saved files can be read." if not problems else f"{len(problems)} damaged file(s).")
            return 1 if problems else 0
        elif args.command == "wipe":
            known = {store.key for store in STORES}
            unknown = [key for key in args.stores if key not in known]
            if unknown:
                raise SystemExit(f"Unknown kind of data: {', '.join(unknown)}. Run 'list' to see the names.")
            word = input(f"This permanently deletes: {', '.join(args.stores)}. Type {backup.WIPE_CONFIRMATION} to confirm: ")
            result = backup.wipe_stores(args.stores, confirm=word.strip(), include_snapshots=not args.keep_snapshots)
            print(f"Deleted {result['files']} files; {result['removed_from_snapshots']} more removed from snapshots.")
    except backup.BackupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
