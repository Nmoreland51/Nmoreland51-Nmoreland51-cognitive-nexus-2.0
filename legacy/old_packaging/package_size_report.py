#!/usr/bin/env python3
"""Report package size totals and the largest files/directories in a build output."""

from __future__ import annotations

import sys
from pathlib import Path


def iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/CognitiveNexusAI")
    if not target.exists():
        sys.stderr.write(f"Target does not exist: {target}\n")
        return 1

    files = list(iter_files(target))
    total_size = sum(path.stat().st_size for path in files)
    top_level_sizes = {}
    for path in files:
        rel = path.relative_to(target)
        top_level = rel.parts[0] if rel.parts else "."
        top_level_sizes[top_level] = top_level_sizes.get(top_level, 0) + path.stat().st_size

    print(f"Package target: {target}")
    print(f"Total files: {len(files)}")
    print(f"Total size: {format_size(total_size)}")
    print()
    print("Largest top-level paths:")
    for name, size in sorted(top_level_sizes.items(), key=lambda item: item[1], reverse=True)[:15]:
        print(f"{format_size(size):>10}  {name}")
    print()
    print("Largest files:")
    for path in sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:20]:
        rel = path.relative_to(target)
        print(f"{format_size(path.stat().st_size):>10}  {rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
