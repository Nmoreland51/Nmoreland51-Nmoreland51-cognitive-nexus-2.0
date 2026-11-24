"""What this machine is, and which local models are worth trying on it.

Two things are kept strictly apart here:

* measured: what tools/speed_benchmark.py recorded on this machine with a model that is installed;
* estimated: arithmetic from that one measurement (bigger models are slower roughly in proportion
  to their size, and need about their file size plus working memory). An estimate is labelled as
  one everywhere it is shown. Nothing here downloads or changes a model.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

# Typical download sizes of 4-bit (Q4_K_M) builds, in GB, by parameter count in billions.
# From the sizes Ollama lists for common models of each class; a particular model may differ.
Q4_SIZES_GB = {3: 2.0, 4: 2.6, 8: 4.9, 12: 7.5, 14: 9.0, 24: 14.5, 32: 20.0, 70: 43.0}
WORKING_MEMORY_GB = 1.5  # context and overhead at the window sizes this app asks for
USABLE_TOKENS_PER_SECOND = 2.0  # below this a chat answer of 150 words takes over a minute and a half


def describe() -> dict[str, Any]:
    """Processor, memory and graphics card of this machine, as far as they can be read without extra packages."""

    import psutil

    memory = psutil.virtual_memory()
    found: dict[str, Any] = {
        "processor": platform.processor() or platform.machine(),
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count() or 0,
        "ram_gb": round(memory.total / 2**30, 1),
        "ram_free_gb": round(memory.available / 2**30, 1),
        "system": f"{platform.system()} {platform.release()}",
        "gpu": "none found",
        "vram_gb": 0.0,
    }
    tool = shutil.which("nvidia-smi")
    if tool:
        try:
            listed = subprocess.run([tool, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            if listed:
                name, megabytes = [part.strip() for part in listed[0].split(",")[:2]]
                found.update(gpu=name, vram_gb=round(float(megabytes) / 1024, 1))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return found


def recommend(ram_gb: float, *, measured_size_b: float = 0.0, measured_tokens_per_second: float = 0.0, vram_gb: float = 0.0) -> list[dict[str, Any]]:
    """For each size class: does it fit in memory, and how fast would it write here?

    `measured_*` is one real measurement on this machine (size in billions of parameters, and
    tokens written per second). Speeds for other sizes are estimated from it; without it no speed
    is given at all. With a graphics card the estimate does not apply and is left out.
    """

    rows = []
    for size, file_gb in sorted(Q4_SIZES_GB.items()):
        needed = round(file_gb + WORKING_MEMORY_GB, 1)
        fits = needed <= ram_gb * 0.6  # leave room for the app, the browser and an image backend
        tight = not fits and needed <= ram_gb * 0.85
        speed = None
        basis = "not estimated"
        if measured_size_b and measured_tokens_per_second and not vram_gb:
            if abs(size - measured_size_b) < 0.5:
                speed, basis = round(measured_tokens_per_second, 1), "measured on this machine"
            else:
                speed, basis = round(measured_tokens_per_second * measured_size_b / size, 1), f"estimated from the {measured_size_b:g}B measurement"
        if not fits and not tight:
            verdict = "does not fit in memory"
        elif speed is not None and speed < USABLE_TOKENS_PER_SECOND:
            verdict = "fits, but too slow for chat on the processor alone"
        elif tight:
            verdict = "fits only with little else running"
        else:
            verdict = "fits" if speed is None else "fits, and is fast enough for chat"
        rows.append({"size_b": size, "needs_gb": needed, "fits": fits or tight, "tokens_per_second": speed, "speed_is": basis, "verdict": verdict})
    return rows


def best_fit(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The largest size class that fits and is fast enough for chat."""

    good = [row for row in rows if row["verdict"] in {"fits, and is fast enough for chat", "fits"}]
    return max(good, key=lambda row: row["size_b"]) if good else None


__all__ = ["Q4_SIZES_GB", "USABLE_TOKENS_PER_SECOND", "best_fit", "describe", "recommend"]
