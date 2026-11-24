"""Talking to the servers on this machine quickly and not more often than needed (item 101).

Measured on the development machine with tools/app_profile.py: a new connection to "localhost"
took 2.05 s instead of 0.04 s (IPv6 tried first), a page asked Ollama for its model list 7 times,
and every click asked a ComfyUI that was not running whether it was there (1.7 s). These tests pin
down the fixes without any server running.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import requests

from modules import embeddings, image_gen, providers
from modules.comfyui_client import ComfyUIClient, ComfyUIStatus
from modules.local_address import loopback_ipv4

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import app_profile  # noqa: E402
import speed_benchmark  # noqa: E402


@pytest.mark.parametrize(
    "given, expected",
    [
        ("http://localhost:11434", "http://127.0.0.1:11434"),
        ("http://LocalHost:11434/api/tags", "http://127.0.0.1:11434/api/tags"),
        ("http://localhost", "http://127.0.0.1"),
        ("https://me:secret@localhost:8443/x?q=1#top", "https://me:secret@127.0.0.1:8443/x?q=1#top"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://ollama.example:11434", "http://ollama.example:11434"),
        ("http://localhost.example.com:11434", "http://localhost.example.com:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
        ("http://localhost:99999", "http://localhost:99999"),  # not a valid port: left for the request to report
        ("", ""),
    ],
)
def test_localhost_is_written_as_the_ipv4_loopback_and_nothing_else_changes(given, expected):
    assert loopback_ipv4(given) == expected


def test_the_configured_ollama_address_is_used_as_ipv4(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/")
    assert providers.get_ollama_base_url() == "http://127.0.0.1:11434"


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


MODEL_LIST = {"models": [{"name": "dolphin3:8b", "details": {"family": "llama"}}, {"name": "all-minilm:latest", "details": {"family": "bert"}}]}


def test_the_model_list_is_asked_for_once_and_shared(monkeypatch):
    asked = []

    def get(url, timeout=None):
        asked.append(url)
        return FakeResponse(MODEL_LIST)

    monkeypatch.setattr(providers.OLLAMA_SESSION, "get", get)
    first = providers.check_ollama_status("http://localhost:11434")
    second = providers.check_ollama_status("http://127.0.0.1:11434")
    assert first.models == second.models == ["dolphin3:8b"]
    # The knowledge search's lookup of embedding models uses the same answer.
    assert embeddings.installed_ollama_embedding_models("http://localhost:11434") == ["all-minilm:latest"]
    assert asked == ["http://127.0.0.1:11434/api/tags"]
    providers.forget_ollama_tags()
    providers.check_ollama_status("http://localhost:11434")
    assert len(asked) == 2


def test_a_failed_request_for_the_model_list_is_not_remembered(monkeypatch):
    answers = [requests.ConnectionError("not yet"), FakeResponse(MODEL_LIST)]

    def get(url, timeout=None):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(providers.OLLAMA_SESSION, "get", get)
    assert providers.check_ollama_status().available is False
    assert providers.check_ollama_status().available is True


def test_the_model_list_is_asked_for_again_after_a_few_seconds(monkeypatch):
    asked = []
    monkeypatch.setattr(providers.OLLAMA_SESSION, "get", lambda url, timeout=None: asked.append(url) or FakeResponse(MODEL_LIST))
    clock = [1000.0]
    monkeypatch.setattr(providers.time, "monotonic", lambda: clock[0])
    providers.ollama_tags("http://127.0.0.1:11434")
    clock[0] += providers.TAGS_CACHE_SECONDS - 0.1
    providers.ollama_tags("http://127.0.0.1:11434")
    clock[0] += 0.2
    providers.ollama_tags("http://127.0.0.1:11434")
    assert len(asked) == 2


def test_comfyui_is_asked_once_per_half_minute_and_a_workflow_always_asks_again(monkeypatch):
    client = ComfyUIClient(base_url="http://localhost:8188")
    assert client.base_url == "http://127.0.0.1:8188"
    probes = []
    answers = [ComfyUIStatus(True, "ComfyUI is reachable.", client.base_url), ComfyUIStatus(False, "ComfyUI is not reachable: refused", client.base_url)]
    monkeypatch.setattr(client, "_probe", lambda: probes.append(1) or answers[min(len(probes), len(answers)) - 1])
    assert client.detect().available and client.detect().available
    assert len(probes) == 1
    # Running a workflow does not trust the kept answer: the server may have stopped since.
    result = client.run_workflow(workflow={}, prompt="a lighthouse")
    assert result.success is False and "not reachable" in result.error and len(probes) == 2
    client.forget_status()
    client.detect()
    assert len(probes) == 3


def test_the_two_image_servers_are_asked_at_the_same_time(monkeypatch):
    def slow_refusal(url, timeout=None):
        time.sleep(0.5)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(image_gen.requests, "get", slow_refusal)
    started = time.perf_counter()
    found = image_gen.detect_image_providers()
    seconds = time.perf_counter() - started
    assert [item["name"] for item in found] == ["automatic1111", "comfyui", "diffusers_local"]
    assert not found[0]["available"] and not found[1]["available"]
    assert seconds < 0.9, f"took {seconds:.2f} s: the servers were asked one after the other"


def test_the_best_image_provider_is_picked_from_a_list_already_found(monkeypatch):
    monkeypatch.setattr(image_gen.requests, "get", lambda *args, **kwargs: pytest.fail("no server should be asked again"))
    listed = [
        {"name": "automatic1111", "available": False, "implemented": True},
        {"name": "diffusers_local", "available": True, "implemented": True, "label": "Local Diffusers"},
    ]
    assert image_gen.detect_image_provider(listed)["name"] == "diffusers_local"


def test_speed_files_measured_with_different_connections_do_not_compare_first_words():
    machine = {"processor": "x", "cores": 6, "threads": 12, "ram_gb": 31.2, "gpu": "none"}
    summary = {"output_tokens_per_second": 5.0, "prompt_tokens_per_second": 58.0, "first_word_seconds_new_prompt": 2.9, "first_word_seconds_follow_up": 2.4}
    old = {"hardware": machine, "model": {"name": "m"}, "summary": summary}
    new = {"hardware": machine, "model": {"name": "m"}, "summary": {**summary, "first_word_seconds_new_prompt": 0.9}, "connection": "one kept-open connection, opened before the first timed run"}
    result = speed_benchmark.compare(old, new)
    first_word = [row for row in result["changes"] if row["what"].startswith("Seconds to the first word")]
    assert first_word and all("not compared" in row.get("note", "") for row in first_word)
    assert result["verdict"] == "not slower"


def test_the_profile_tool_counts_requests_by_address(monkeypatch):
    def send(session, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = b"{}"
        return response

    monkeypatch.setattr(requests.sessions.Session, "send", send)
    with app_profile.HttpLog() as log:
        requests.get("http://127.0.0.1:11434/api/tags?x=1")
        requests.get("http://127.0.0.1:11434/api/tags")
        requests.post("http://127.0.0.1:11434/api/show", json={})
    summary = log.summary()
    assert summary["total"] == 3
    assert summary["by_address"][0] == {"call": "GET http://127.0.0.1:11434/api/tags", "times": 2}
    assert requests.sessions.Session.send is send  # put back as it was



# ---- a streamed answer keeps its connection ---------------------------------------------------


def test_what_is_left_of_a_streamed_answer_is_read_and_a_failure_there_is_harmless():
    from modules.provider_router import _finish_reading

    class Stream:
        def __init__(self):
            self.read_to_end = self.closed = False

        def iter_content(self, chunk_size=1024):
            yield b"0\r\n\r\n"
            self.read_to_end = True

        def close(self):
            self.closed = True

    stream = Stream()
    _finish_reading(stream)
    assert stream.read_to_end and stream.closed

    class Gone:
        def iter_content(self, chunk_size=1024):
            raise requests.ConnectionError("gone")

    _finish_reading(Gone())  # does not raise
    _finish_reading(object())  # nor for something that is not a response at all


def test_two_answers_in_a_row_use_the_same_connection():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from modules.provider_router import ProviderInfo, ProviderRequest, ProviderRouter

    seen_ports: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keeps connections open, as Ollama does

        def log_message(self, *args):
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            if self.path == "/api/show":
                body = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            seen_ports.append(self.client_address[1])
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for message in ({"response": "Hi", "done": False}, {"response": "", "done": True, "eval_count": 1, "eval_duration": 1000000}):
                line = (json.dumps(message) + "\n").encode()
                self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        router = ProviderRouter({"provider_order": ["ollama"], "ollama_url": url})
        info = ProviderInfo(name="ollama", available=True, message="ok", models=["m"], base_url=url)
        for _ in range(2):
            assert "".join(router._stream_ollama(ProviderRequest(prompt="hello", model="m"), info, "m")) == "Hi"
    finally:
        server.shutdown()
        server.server_close()
    assert len(seen_ports) == 2 and seen_ports[0] == seen_ports[1], f"a new connection for the second answer: {seen_ports}"
