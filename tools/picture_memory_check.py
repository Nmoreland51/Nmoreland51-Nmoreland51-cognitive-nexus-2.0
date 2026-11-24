"""Measure how much memory making a picture takes on this machine (items 098 and 105).

    python tools/picture_memory_check.py --path pipeline --sizes 512 768 --save docs/benchmarks/picture_memory.json
    python tools/picture_memory_check.py --path app --sizes 512 768 --save docs/benchmarks/picture_memory_app.json

Each size runs in a fresh Python process that makes one picture with the local Stable Diffusion
pipeline (modules/image_gen.py: Stable Diffusion 1.5, its half-size files widened to full precision
on the processor). Recorded per size: the most memory that process held (on Windows its peak
working set, as the system counts it; elsewhere its resident size at the end), the largest resident
size sampled from outside, the seconds to load and to make the picture, the memory available to the
whole system before, at its lowest and after, and which chat models Ollama had in memory.

--path pipeline loads the pipeline and makes the picture directly, as the app did before
modules/heavy_work.py: nothing is done about the chat model, so the lowest available memory is what
the app faced then. --path app goes through modules.image_gen.generate_images, the way the app makes
a picture now (one picture slot, room made in memory as --policy allows, the time limit); its
report of what it did is recorded. When that took the chat model out of memory, the tool then asks
Ollama for a few words from it, the way the next chat answer would, and records how long Ollama
took to load it again (the cost of making room). Afterwards the chat model is loaded as before.

It does not download anything (the image model must already be on disk) and takes a few minutes
per size on a processor.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GB = 1024**3
PROMPT = "a lighthouse on a cliff at dusk, waves below"


def _own_peak_bytes() -> int:
    import psutil

    info = psutil.Process().memory_info()
    return int(getattr(info, "peak_wset", 0) or info.rss)


def _child(size: int, steps: int, path: str, policy: str, ollama_url: str) -> None:
    """Runs in the measured process: make one picture, print the figures as JSON."""

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    started = time.perf_counter()
    from modules.image_gen import ImageGenerationRequest, LocalStableDiffusionGenerator, generate_images, generate_with_diffusers

    request = ImageGenerationRequest(
        prompt=PROMPT, width=size, height=size, steps=steps, seed=7, provider="diffusers_local", style="none", save_outputs=False
    )
    figures: dict[str, Any] = {}
    if path == "pipeline":
        generator = LocalStableDiffusionGenerator()
        generator._ensure_initialized()
        loaded = time.perf_counter()
        figures["peak_after_load_bytes"] = _own_peak_bytes()
        figures["load_seconds"] = round(loaded - started, 1)
        generate_with_diffusers(request, generator=generator)
        figures["picture_seconds"] = round(time.perf_counter() - loaded, 1)
        figures["device"] = generator.device
    else:
        result = generate_images(request, memory_policy=policy, ollama_url=ollama_url)
        figures["seconds"] = round(time.perf_counter() - started, 1)
        figures["success"] = bool(result.get("success"))
        figures["error"] = result.get("error")
        figures["memory_report"] = result.get("memory")
        figures["waited_seconds"] = result.get("waited_seconds")
        figures["device"] = (result.get("saved") or [{}])[0].get("device", "")
    import torch

    figures["peak_bytes"] = _own_peak_bytes()
    figures["peak_is"] = "peak working set" if sys.platform == "win32" else "resident size at the end"
    figures["torch"] = torch.__version__
    print(json.dumps(figures))


class _Watch(threading.Thread):
    """Samples the measured process tree's memory and the memory available to the system."""

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        import psutil

        self.process = psutil.Process(pid)
        self.stop = threading.Event()
        self.peak_rss = 0
        self.lowest_available = psutil.virtual_memory().available

    def run(self) -> None:
        import psutil

        while not self.stop.is_set():
            # The whole tree: on Windows a virtual environment's python.exe is a launcher that runs
            # the real interpreter as its child.
            total = 0
            try:
                for member in [self.process, *self.process.children(recursive=True)]:
                    try:
                        total += member.memory_info().rss
                    except psutil.Error:
                        continue
            except psutil.Error:
                pass
            self.peak_rss = max(self.peak_rss, total)
            self.lowest_available = min(self.lowest_available, psutil.virtual_memory().available)
            self.stop.wait(0.25)


def _loaded_chat_models(base_url: str) -> list[dict[str, Any]]:
    import requests

    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/ps", timeout=3)
        response.raise_for_status()
        return [
            {
                "name": item.get("name"),
                "size_gb": round(int(item.get("size") or 0) / GB, 2),
                "in_graphics_memory_gb": round(int(item.get("size_vram") or 0) / GB, 2),
                "context_length": item.get("context_length"),
            }
            for item in response.json().get("models") or []
        ]
    except Exception as exc:  # the measurement does not need Ollama; it only records what it held
        return [{"error": f"Ollama not reachable: {exc}"}]


def _reload_cost(base_url: str, model: dict[str, Any]) -> dict[str, Any]:
    """Ask the chat model for a few words, as the next chat answer would, and report Ollama's load time."""

    import requests

    options = {"num_predict": 4, "temperature": 0}
    if model.get("context_length"):
        options["num_ctx"] = int(model["context_length"])  # the same window, so Ollama loads it as before
    started = time.perf_counter()
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model["name"], "prompt": "Reply with the single word OK.", "stream": False, "keep_alive": "24h", "options": options},
            timeout=(5, 300),
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {"model": model["name"], "error": str(exc)[:300]}
    return {
        "model": model["name"],
        "load_seconds": round(int(data.get("load_duration") or 0) / 1e9, 1),
        "answer_seconds": round(time.perf_counter() - started, 1),
    }


def measure(size: int, steps: int, path: str, policy: str, base_url: str) -> dict[str, Any]:
    import psutil

    before = psutil.virtual_memory()
    chat_models = _loaded_chat_models(base_url)
    env = dict(os.environ, HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8")
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--child", str(size), str(steps), path, policy, base_url],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )  # fmt: skip
    watch = _Watch(child.pid)
    watch.start()
    stdout, stderr = child.communicate()
    watch.stop.set()
    watch.join()
    after = psutil.virtual_memory()
    row: dict[str, Any] = {
        "path": path,
        "size": f"{size}x{size}",
        "steps": steps,
        "chat_models_in_memory": chat_models,
        "available_before_gb": round(before.available / GB, 2),
        "available_lowest_gb": round(watch.lowest_available / GB, 2),
        "available_after_gb": round(after.available / GB, 2),
        "sampled_peak_rss_gb": round(watch.peak_rss / GB, 2),
    }
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if child.returncode != 0 or not lines:
        row["error"] = (stderr.strip().splitlines() or ["the process ended without a result"])[-1][:400]
        return row
    figures = json.loads(lines[-1])
    for key in ("peak_after_load_bytes", "peak_bytes"):
        if key in figures:
            figures[key.replace("_bytes", "_gb")] = round(figures.pop(key) / GB, 2)
    row.update(figures)
    report = figures.get("memory_report") or {}
    if path == "app" and report.get("unloaded"):
        loaded_before = {item.get("name"): item for item in chat_models if item.get("name")}
        row["chat_model_reload"] = [_reload_cost(base_url, loaded_before.get(name, {"name": name})) for name in report["unloaded"]]
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", choices=("pipeline", "app"), default="pipeline")
    parser.add_argument("--policy", default="free_chat_model", help="for --path app: picture_memory setting to use")
    parser.add_argument("--sizes", type=int, nargs="+", default=[512, 768])
    parser.add_argument("--steps", type=int, default=4, help="denoising steps; memory does not grow with them, time does")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    parser.add_argument("--save", type=Path)
    parser.add_argument("--child", nargs=5, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        size, steps, path, policy, url = args.child
        _child(int(size), int(steps), path, policy, url)
        return 0

    from modules import hardware

    rows = []
    for size in args.sizes:
        print(f"{size}x{size} ({args.path}): making one picture ...", flush=True)
        row = measure(size, args.steps, args.path, args.policy, args.ollama_url)
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = {
        "what": f"Memory taken by making one picture with the local Stable Diffusion pipeline, path '{args.path}', one fresh process per size",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": hardware.describe(),
        "runs": rows,
    }
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"saved {args.save}")
    return 0 if all(not row.get("error") and row.get("success", True) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
