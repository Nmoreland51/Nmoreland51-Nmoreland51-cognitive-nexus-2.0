"""The speed measurement and the model-size advice: what is measured, what is arithmetic, and what counts as slower."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from modules import hardware

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import speed_benchmark as bench  # noqa: E402

SAVED = REPO_ROOT / "docs" / "benchmarks" / "speed_dolphin3-8b.json"
MACHINE = {"processor": "Test CPU", "cores": 6, "threads": 12, "ram_gb": 31.2, "ram_free_gb": 20.0, "system": "Windows 11", "gpu": "none found", "vram_gb": 0.0}


def result(writes=4.0, reads=30.0, first_new=6.0, first_again=1.0, machine=None, model="chat:8b"):
    return {
        "hardware": dict(machine or MACHINE),
        "model": {"name": model, "parameters": "8.0B"},
        "summary": {"output_tokens_per_second": writes, "prompt_tokens_per_second": reads, "first_word_seconds_new_prompt": first_new, "first_word_seconds_follow_up": first_again},
    }


# ---- which sizes fit ---------------------------------------------------------------------------------


def test_only_the_measured_size_carries_a_measured_speed():
    rows = {row["size_b"]: row for row in hardware.recommend(31.2, measured_size_b=8, measured_tokens_per_second=4.0)}

    assert rows[8]["tokens_per_second"] == 4.0 and rows[8]["speed_is"] == "measured on this machine"
    assert rows[4]["tokens_per_second"] == 8.0 and rows[4]["speed_is"] == "estimated from the 8B measurement"  # half the size, about twice as fast
    assert rows[8]["verdict"] == rows[14]["verdict"] == "fits, and is fast enough for chat" and rows[14]["tokens_per_second"] == 2.3
    assert rows[24]["tokens_per_second"] == 1.3 and rows[24]["verdict"] == "fits, but too slow for chat on the processor alone"
    assert rows[32]["tokens_per_second"] == 1.0 and rows[32]["fits"] and rows[32]["verdict"] == "fits, but too slow for chat on the processor alone"
    assert rows[70]["verdict"] == "does not fit in memory" and not rows[70]["fits"]
    assert hardware.best_fit(list(rows.values()))["size_b"] == 14


def test_without_a_measurement_no_speed_is_claimed_and_a_small_machine_gets_small_models():
    rows = hardware.recommend(8.0)

    assert all(row["tokens_per_second"] is None and row["speed_is"] == "not estimated" for row in rows)
    fitting = [row["size_b"] for row in rows if row["verdict"] == "fits"]
    assert fitting == [3, 4] and hardware.best_fit(rows)["size_b"] == 4
    assert {row["size_b"]: row["verdict"] for row in rows}[8] == "fits only with little else running"
    assert hardware.best_fit(hardware.recommend(2.0)) is None


def test_with_a_graphics_card_the_processor_estimate_is_not_applied():
    rows = hardware.recommend(32.0, measured_size_b=8, measured_tokens_per_second=4.0, vram_gb=12.0)
    assert all(row["tokens_per_second"] is None for row in rows)


def test_this_machine_can_be_described():
    found = hardware.describe()
    assert found["cores"] >= 1 and found["threads"] >= found["cores"] and found["ram_gb"] > 0.5 and found["system"]
    assert isinstance(found["gpu"], str) and found["vram_gb"] >= 0


# ---- slower or not -----------------------------------------------------------------------------------


def test_a_clear_drop_in_writing_speed_is_slower_and_noise_is_not():
    assert bench.compare(result(), result(writes=3.9, reads=28.0, first_new=6.4))["verdict"] == "not slower"

    outcome = bench.compare(result(), result(writes=3.0))

    assert outcome["verdict"] == "slower"
    assert [change for change in outcome["changes"] if change["worse"]] == [{"what": "Tokens written per second", "before": 4.0, "after": 3.0, "change_percent": -25, "worse": True}]


def test_a_longer_wait_for_the_first_word_is_slower_unless_it_is_a_fraction_of_a_second():
    assert bench.compare(result(), result(first_new=9.0))["verdict"] == "slower"
    assert bench.compare(result(first_again=0.2), result(first_again=0.5))["verdict"] == "not slower"  # 150% more, and 0.3 s
    assert bench.compare(result(), result(writes=6.0, first_new=3.0))["verdict"] == "not slower"


def test_files_from_another_machine_or_model_are_not_compared():
    other = {**MACHINE, "ram_gb": 64.0}
    assert bench.compare(result(), result(machine=other)) == {"verdict": "not comparable", "why": "The saved file is from another machine or another model.", "changes": []}
    assert bench.compare(result(), result(model="other:8b"))["verdict"] == "not comparable"
    assert bench.same_machine(MACHINE, {**MACHINE, "ram_free_gb": 3.0})  # how much memory is free right now does not make it another machine


# ---- one run against a stand-in server ----------------------------------------------------------------


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.sent.append(body)
        lines = [
            {"response": "Cold ", "done": False},
            {"response": "air.", "done": False},
            {"response": "", "done": True, "done_reason": "stop", "load_duration": 2_000_000_000, "prompt_eval_count": 60, "prompt_eval_duration": 2_000_000_000, "eval_count": 8, "eval_duration": 2_000_000_000},
        ]
        data = "".join(json.dumps(line) + "\n" for line in lines).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_one_run_reads_the_servers_own_counters():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
    server.sent = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        row = bench.one_run(f"http://127.0.0.1:{server.server_address[1]}", "chat:8b", "Why is it cold?", 40, 4096)
    finally:
        server.shutdown()
        server.server_close()

    assert server.sent[0]["options"] == {"temperature": 0, "num_predict": 40, "num_ctx": 4096} and server.sent[0]["prompt"] == "Why is it cold?"
    assert (row["prompt_tokens"], row["prompt_tokens_per_second"], row["output_tokens"], row["output_tokens_per_second"]) == (60, 30.0, 8, 4.0)
    assert row["load_seconds"] == 2.0 and row["stopped_because"] == "stop" and row["characters_written"] == 9
    assert 0 <= row["first_word_seconds"] <= row["total_seconds"]


def test_the_three_prompts_are_fixed_and_the_long_one_is_long():
    names = [name for name, _prompt, _limit in bench.PROMPTS]
    assert names == ["one_sentence", "150_words", "long_text"]
    assert len(bench.PROMPTS[2][1]) > 8000 and bench.PROMPTS[2][1].endswith("Summarise the text above in three short bullet points.")
    assert bench.size_in_billions("8.0B") == 8.0 and bench.size_in_billions("") == 0.0


# ---- the saved measurement -------------------------------------------------------------------------------


@pytest.mark.skipif(not SAVED.exists(), reason="no saved speed measurement yet")
def test_the_saved_measurement_says_what_machine_it_was_and_adds_up():
    saved = json.loads(SAVED.read_text(encoding="utf-8"))

    assert saved["hardware"]["cores"] >= 1 and saved["hardware"]["ram_gb"] > 1 and saved["model"]["name"] and saved["ollama_version"]
    assert len(saved["runs"]) == 6 and {row["sent"] for row in saved["runs"]} == {"new prompt", "same prompt again"}
    assert all(row["output_tokens"] > 0 and row["output_tokens_per_second"] > 0 and row["peak_ollama_memory_gb"] > 0 for row in saved["runs"])
    writes = sorted(row["output_tokens_per_second"] for row in saved["runs"])
    assert writes[0] <= saved["summary"]["output_tokens_per_second"] <= writes[-1]
    assert bench.compare(saved, saved)["verdict"] == "not slower"
