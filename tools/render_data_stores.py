"""Write docs/DATA_STORES.md from modules/data_stores.py.

    python tools/render_data_stores.py           rewrite the document
    python tools/render_data_stores.py --check   exit 1 if the document is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.data_stores import render_markdown  # noqa: E402

TARGET = REPO_ROOT / "docs" / "DATA_STORES.md"


def main(argv: list[str]) -> int:
    wanted = render_markdown()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != wanted:
            print("docs/DATA_STORES.md is out of date. Run: python tools/render_data_stores.py")
            return 1
        print("docs/DATA_STORES.md is up to date")
        return 0
    TARGET.write_bytes(wanted.encode("utf-8"))
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
