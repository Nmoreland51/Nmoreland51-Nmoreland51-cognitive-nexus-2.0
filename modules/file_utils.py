"""Crash-safe file writes for memory, settings and knowledge files.

`Path.write_text` truncates the file first, so a crash or power loss mid-write - or another
process (the phone backend) reading at the wrong moment - leaves an empty or half-written JSON
file, and the saved memory is gone. These helpers write a temporary file next to the target and
swap it in with one atomic rename, so readers see either the old file or the new one.

This does not stop two writers from overwriting each other's changes; that needs a lock or a
database.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_REPLACE_ATTEMPTS = 6


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Replace `path` with `text` atomically."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding=encoding) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temp_name, target)
                return
            except PermissionError:
                # Windows refuses the swap while another process has the file open; that clears
                # within milliseconds for a reader.
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def atomic_write_json(path: Path | str, payload: Any, *, indent: int | None = 2, ensure_ascii: bool = False) -> None:
    """Serialize `payload` first (so a failure leaves the old file alone), then replace `path` atomically."""

    atomic_write_text(path, json.dumps(payload, indent=indent, ensure_ascii=ensure_ascii))
