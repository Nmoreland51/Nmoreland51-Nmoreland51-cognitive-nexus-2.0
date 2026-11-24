"""Measure how fast a local model answers on this machine, and what it costs in memory and processor.

    python tools/speed_benchmark.py --model dolphin3:8b --save docs/benchmarks/speed_dolphin3-8b.json
    python tools/speed_benchmark.py --model dolphin3:8b --compare docs/benchmarks/speed_dolphin3-8b.json
    python tools/speed_benchmark.py --recommend docs/benchmarks/speed_dolphin3-8b.json

Three fixed prompts are sent straight to the Ollama server: a one-sentence answer, a 150-word
answer, and a long text to summarise. Each is sent twice, because the server keeps what it has
already read: the first time shows the cost of reading a new prompt, the second what a follow-up
costs. Recorded per run: seconds until the first word, total seconds, tokens read per second,
tokens written per second (the server's own counters), the most memory the Ollama processes held
and how busy the processor was. The file also says what machine it was: without that, two files
cannot be compared.

--compare measures again and sets the result against a saved file from the same machine: it exits
1 when writing got more than --tolerance slower or the first word takes that much longer. That is
the check to run before and after a change that could affect speed. It needs the model, so it is
not part of CI.

--recommend prints which model sizes fit this machine. Only the size that was measured carries a
measured speed; the others are arithmetic from it and say so.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules import hardware  # noqa: E402
from modules.local_address import loopback_ipv4  # noqa: E402

_TOWN = " ".join(
    f"In year {1900 + number}, the town of Marrow Ford recorded {300 + 7 * number} households, opened {number % 5 + 1} new workshops along the river and "
    f"sent {40 + 3 * number} barrels of apples to the coast, according to the ledger kept by the harbour clerk."
    for number in range(1, 46)
)
PROMPTS: tuple[tuple[str, str, int], ...] = (
    ("one_sentence", "In one sentence, what is a hash table?", 60),
    ("150_words", "Explain in about 150 words how a refrigerator keeps food cold.", 260),
    ("long_text", f"{_TOWN}\n\nSummarise the text above in three short bullet points.", 160),
)


class Watch(threading.Thread):
    """Samples the memory held by the Ollama processes and how busy the processor is, while a run goes on."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.peak_bytes = 0
        self.cpu: list[float] = []

    def run(self) -> None:
        import psutil

        psutil.cpu_percent(interval=None)
        while not self.stop.wait(0.5):
            held = 0
            for process in psutil.process_iter(["name", "memory_info"]):
                try:
                    if "ollama" in (process.info["name"] or "").lower() or "llama" in (process.info["name"] or "").lower():
                        held += process.info["memory_info"].rss
                except (psutil.Error, TypeError, AttributeError):
                    continue
            self.peak_bytes = max(self.peak_bytes, held)
            self.cpu.append(psutil.cpu_percent(interval=None))


# One kept-open connection, as the app has (modules/providers.OLLAMA_SESSION), opened by the
# warm-up call before anything is timed. Until 2026-11-24 every run opened a new connection, and on
# Windows a new connection to "localhost" waits about 2 s for an IPv6 attempt to fail first; the
# first-word times saved before then include that (docs/benchmarks/README.md says by how much).
SESSION = requests.Session()


def one_run(url: str, model: str, prompt: str, max_tokens: int, num_ctx: int) -> dict[str, Any]:
    watch = Watch()
    watch.start()
    started = time.perf_counter()
    first = None
    final: dict[str, Any] = {}
    text = []
    try:
        with SESSION.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": True, "keep_alive": "24h", "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": num_ctx}},
            stream=True,
            timeout=(10, 1800),
        ) as answer:
            answer.raise_for_status()
            for line in answer.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                if data.get("response") and first is None:
                    first = time.perf_counter() - started
                text.append(str(data.get("response", "")))
                if data.get("done"):
                    final = data
                    break
    finally:
        total = time.perf_counter() - started
        watch.stop.set()
        watch.join(timeout=3)

    def rate(count: str, duration: str) -> float:
        tokens, nanoseconds = int(final.get(count) or 0), int(final.get(duration) or 0)
        return round(tokens / (nanoseconds / 1e9), 1) if tokens and nanoseconds else 0.0

    return {
        "first_word_seconds": round(first if first is not None else total, 2),
        "total_seconds": round(total, 2),
        "load_seconds": round(int(final.get("load_duration") or 0) / 1e9, 2),
        "prompt_tokens": int(final.get("prompt_eval_count") or 0),
        "prompt_tokens_per_second": rate("prompt_eval_count", "prompt_eval_duration"),
        "output_tokens": int(final.get("eval_count") or 0),
        "output_tokens_per_second": rate("eval_count", "eval_duration"),
        "stopped_because": str(final.get("done_reason") or ""),
        "peak_ollama_memory_gb": round(watch.peak_bytes / 2**30, 2),
        "mean_processor_percent": round(statistics.mean(watch.cpu), 0) if watch.cpu else 0.0,
        "characters_written": len("".join(text)),
    }


def measure(model: str, url: str, num_ctx: int = 4096) -> dict[str, Any]:
    url = loopback_ipv4(url.rstrip("/"))
    version = SESSION.get(f"{url}/api/version", timeout=10).json().get("version", "")
    shown = SESSION.post(f"{url}/api/show", json={"model": model}, timeout=20).json()
    one_run(url, model, "Say OK.", 4, num_ctx)  # load the model first, so that loading is not counted as answering
    runs = []
    for name, prompt, max_tokens in PROMPTS:
        for attempt in ("new prompt", "same prompt again"):
            row = {"prompt": name, "sent": attempt, **one_run(url, model, prompt, max_tokens, num_ctx)}
            runs.append(row)
            print(f"{name:<13} {attempt:<18} first word {row['first_word_seconds']:>6.2f}s  total {row['total_seconds']:>6.1f}s  reads {row['prompt_tokens_per_second']:>6.1f}/s  writes {row['output_tokens_per_second']:>5.1f}/s  memory {row['peak_ollama_memory_gb']:.1f} GB  processor {row['mean_processor_percent']:.0f}%", flush=True)
    loaded: dict[str, Any] = next((item for item in SESSION.get(f"{url}/api/ps", timeout=10).json().get("models", []) if item.get("name") == model), {})
    details = shown.get("details") or {}
    fresh = [row for row in runs if row["sent"] == "new prompt"]
    again = [row for row in runs if row["sent"] == "same prompt again"]
    return {
        "measured_at": time.strftime("%Y-%m-%d"),
        "hardware": hardware.describe(),
        "ollama_version": version,
        "connection": "one kept-open connection, opened before the first timed run",
        "model": {
            "name": model,
            "parameters": str(details.get("parameter_size") or ""),
            "quantization": str(details.get("quantization_level") or ""),
            "window_asked_for": num_ctx,
            "held_in_memory_gb": round(int(loaded.get("size") or 0) / 2**30, 2),
            "of_which_on_the_graphics_card_gb": round(int(loaded.get("size_vram") or 0) / 2**30, 2),
        },
        "runs": runs,
        "summary": {
            "first_word_seconds_new_prompt": round(statistics.median(row["first_word_seconds"] for row in fresh), 2),
            "first_word_seconds_follow_up": round(statistics.median(row["first_word_seconds"] for row in again), 2),
            "first_word_seconds_long_new_prompt": max(row["first_word_seconds"] for row in fresh),
            "longest_prompt_tokens": max(row["prompt_tokens"] for row in fresh),
            "output_tokens_per_second": round(statistics.median(row["output_tokens_per_second"] for row in runs if row["output_tokens_per_second"]), 1),
            "prompt_tokens_per_second": round(statistics.median(row["prompt_tokens_per_second"] for row in fresh if row["prompt_tokens_per_second"]), 1),
            "peak_ollama_memory_gb": max(row["peak_ollama_memory_gb"] for row in runs),
            "mean_processor_percent": round(statistics.mean(row["mean_processor_percent"] for row in runs), 0),
        },
    }


def same_machine(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return all(first.get(key) == second.get(key) for key in ("processor", "cores", "threads", "ram_gb", "gpu"))


def compare(before: dict[str, Any], after: dict[str, Any], tolerance: float = 0.2) -> dict[str, Any]:
    """Did it get slower? Only meaningful on the same machine with the same model."""

    if not same_machine(before["hardware"], after["hardware"]) or before["model"]["name"] != after["model"]["name"]:
        return {"verdict": "not comparable", "why": "The saved file is from another machine or another model.", "changes": []}
    changes, slower = [], False
    # A file saved before the tool kept its connection open counted a new connection in every
    # first-word time (about 2 s on Windows with "localhost"); those times cannot be compared.
    same_connection = before.get("connection") == after.get("connection")
    for key, meaning, higher_is_better in (
        ("output_tokens_per_second", "Tokens written per second", True),
        ("prompt_tokens_per_second", "Tokens read per second", True),
        ("first_word_seconds_new_prompt", "Seconds to the first word, new prompt", False),
        ("first_word_seconds_follow_up", "Seconds to the first word, follow-up", False),
    ):
        old, new = float(before["summary"][key]), float(after["summary"][key])
        if not old:
            continue
        change = (new - old) / old
        if key.startswith("first_word") and not same_connection:
            changes.append({"what": meaning, "before": old, "after": new, "change_percent": round(change * 100), "worse": False, "note": "not compared: one file opened a new connection for every run"})
            continue
        worse = change < -tolerance if higher_is_better else change > tolerance and (new - old) > 0.5
        slower = slower or worse
        changes.append({"what": meaning, "before": old, "after": new, "change_percent": round(change * 100), "worse": worse})
    return {"verdict": "slower" if slower else "not slower", "why": "", "changes": changes}


def size_in_billions(text: str) -> float:
    try:
        return float(str(text).upper().rstrip("B"))
    except ValueError:
        return 0.0


def recommendations(saved: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    machine = hardware.describe()
    usable = saved is not None and same_machine(saved["hardware"], machine)
    rows = hardware.recommend(
        machine["ram_gb"],
        measured_size_b=size_in_billions(saved["model"]["parameters"]) if usable and saved else 0.0,
        measured_tokens_per_second=float(saved["summary"]["output_tokens_per_second"]) if usable and saved else 0.0,
        vram_gb=machine["vram_gb"],
    )
    return machine, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--window", type=int, default=4096)
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--compare", type=Path, default=None, help="a saved file from this machine to compare a new measurement with")
    parser.add_argument("--tolerance", type=float, default=0.2)
    parser.add_argument("--recommend", type=Path, nargs="?", const=Path("-"), default=None, help="print which model sizes fit this machine (optionally with a saved measurement for speeds)")
    args = parser.parse_args(argv)
    if args.recommend is not None:
        saved = json.loads(args.recommend.read_text(encoding="utf-8")) if str(args.recommend) != "-" and args.recommend.exists() else None
        machine, rows = recommendations(saved)
        print(f"{machine['processor']}, {machine['cores']} cores, {machine['ram_gb']} GB memory, graphics card: {machine['gpu']}")
        for row in rows:
            speed = f"{row['tokens_per_second']} tokens/s ({row['speed_is']})" if row["tokens_per_second"] is not None else "speed not estimated"
            print(f"  about {row['size_b']:>2}B parameters, 4-bit: needs {row['needs_gb']:>4} GB. {row['verdict']}; {speed}")
        best = hardware.best_fit(rows)
        print(f"Largest size worth trying here: about {best['size_b']}B." if best else "No size class fits comfortably.")
        return 0
    if not args.model:
        parser.error("give --model, or --recommend")
    result = measure(args.model, args.ollama_url, args.window)
    print(json.dumps(result["summary"], indent=1))
    code = 0
    if args.compare:
        outcome = compare(json.loads(args.compare.read_text(encoding="utf-8")), result, args.tolerance)
        print(f"Compared with {args.compare}: {outcome['verdict'].upper()} {outcome['why']}")
        for change in outcome["changes"]:
            print(f"  {change['what']}: {change['before']} -> {change['after']} ({change['change_percent']:+d}%){'  WORSE' if change['worse'] else ''}")
        code = {"not slower": 0, "slower": 1}.get(outcome["verdict"], 2)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(result, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
