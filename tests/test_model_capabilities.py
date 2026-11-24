"""What a model can do is asked from the server or taken from published figures, and "not known" is never "yes"."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from modules import model_capabilities
from modules.model_capabilities import capabilities, for_cloud, from_ollama_show, rows
from modules.provider_router import ProviderRequest, ProviderRouter, _prompt_with_schema

# What Ollama 0.40 answered for these two models on the development machine (shortened).
CHAT_MODEL = {
    "capabilities": ["completion"],
    "details": {"family": "llama", "families": ["llama"], "parameter_size": "8.0B", "quantization_level": "Q4_K_M"},
    "model_info": {"general.architecture": "llama", "general.parameter_count": 8030277696, "llama.context_length": 131072, "llama.embedding_length": 4096},
}
EMBEDDING_MODEL = {"capabilities": ["embedding"], "details": {"family": "bert", "families": ["bert"]}, "model_info": {"general.architecture": "bert", "bert.context_length": 512}}
VISION_TOOLS_MODEL = {"capabilities": ["completion", "vision", "tools"], "details": {"family": "gemma3"}, "model_info": {"general.architecture": "gemma3", "gemma3.context_length": 32768}}


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.asked.append((self.path, body))
        known = self.server.models.get(body.get("model"))
        data = json.dumps(known if known is not None else {"error": "model not found"}).encode()
        self.send_response(200 if known is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
    server.asked, server.models = [], {"chat:8b": CHAT_MODEL, "embed": EMBEDDING_MODEL}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    model_capabilities.forget_cached()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()
        model_capabilities.forget_cached()


def test_a_local_chat_model_is_described_from_what_the_server_reports():
    found = from_ollama_show("dolphin3:8b", CHAT_MODEL)

    assert (found.context_window, found.chat, found.streaming, found.tools, found.vision, found.embeddings) == (131072, True, True, False, False, False)
    # Holding a reply to a schema is done by the server for any model that writes.
    assert found.structured_output is True and found.source == "reported by the Ollama server"
    assert found.supports("structured_output") and not found.supports("tools") and not found.supports("vision")
    assert "asks for a JSON reply held to a schema instead" in found.notes[0]


def test_an_embedding_model_cannot_chat_and_a_richer_model_reports_more():
    embeds = from_ollama_show("all-minilm", EMBEDDING_MODEL)
    assert embeds.embeddings and embeds.chat is False and embeds.structured_output is False and embeds.context_window == 512

    rich = from_ollama_show("gemma3", VISION_TOOLS_MODEL)
    assert rich.supports("vision") and rich.supports("tools") and rich.context_window == 32768 and rich.notes == ()


def test_an_older_server_that_reports_nothing_gives_not_known_rather_than_a_guess():
    found = from_ollama_show("old", {"details": {"families": ["llama"]}, "model_info": {"llama.context_length": 4096}})

    assert found.tools is None and found.vision is None and found.structured_output is None
    assert not found.supports("tools") and not found.supports("vision")  # not known is never yes
    assert "does not say what the model can do" in found.notes[0] and found.context_window == 4096


def test_the_server_is_asked_once_and_an_unknown_or_unreachable_one_is_not_guessed_at(ollama):
    address, server = ollama

    first = capabilities("ollama", "chat:8b", ollama_url=address)
    again = capabilities("ollama", "chat:8b", ollama_url=address)

    assert first == again and first.context_window == 131072 and len(server.asked) == 1 and server.asked[0] == ("/api/show", {"model": "chat:8b"})
    missing = capabilities("ollama", "nope", ollama_url=address)
    assert missing.source == "unknown" and "does not have this model" in missing.notes[0] and not missing.supports("chat")
    unreachable = capabilities("ollama", "chat:8b", ollama_url="http://127.0.0.1:9")
    assert unreachable.source == "unknown" and "could not be asked" in unreachable.notes[0]


def test_cloud_models_carry_published_figures_and_say_that_they_were_not_checked():
    sonnet = for_cloud("anthropic", "claude-sonnet-5-5")
    assert (sonnet.context_window, sonnet.max_output, sonnet.vision, sonnet.tools, sonnet.structured_output) == (1_000_000, 128_000, True, True, True)
    assert "not checked against the live service" in sonnet.source
    assert for_cloud("anthropic", "claude-haiku-4-5-20251001").context_window == 200_000  # the longest matching name wins
    assert for_cloud("openai", "gpt-4.1-mini").max_output == 32_768
    unheard = for_cloud("openai", "gpt-99-turbo")
    assert unheard.source == "unknown" and unheard.context_window is None and not unheard.supports("vision")
    assert capabilities("somewhere", "model").source == "unknown" and capabilities("ollama", "").notes == ("No model is selected.",)


def test_the_table_for_a_person_says_not_known_where_it_is_not_known():
    table = {row["What"]: row["Value"] for row in rows(from_ollama_show("old", {"model_info": {}}))}
    assert table["Context length"] == "not known" and table["Tools"] == "not known" and table["Streaming"] == "yes"
    table = {row["What"]: row["Value"] for row in rows(from_ollama_show("dolphin3:8b", CHAT_MODEL))}
    assert table["Context length"] == "131,072 tokens" and table["Tools"] == "no" and table["Structured output"] == "yes" and table["Longest reply"] == "limited by the context length"
    with pytest.raises(ValueError, match="is not a feature"):
        from_ollama_show("x", CHAT_MODEL).supports("telepathy")


def test_the_router_answers_for_its_own_server(ollama):
    address, _server = ollama
    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": address})

    assert router.capabilities("ollama", "chat:8b").context_window == 131072
    assert router.capabilities("anthropic", "claude-opus-5-5").max_output == 128_000


# ---- a reply held to a schema --------------------------------------------------------------------------

SCHEMA = {"type": "object", "properties": {"tool": {"type": "string"}}, "required": ["tool"]}


def test_a_provider_that_cannot_be_held_to_a_schema_is_asked_for_it_in_words():
    plain = ProviderRequest(prompt="Pick a tool.")
    asked = ProviderRequest(prompt="Pick a tool.", response_schema=SCHEMA)

    assert _prompt_with_schema(plain) == "Pick a tool."
    text = _prompt_with_schema(asked)
    assert text.startswith("Pick a tool.\n\nReply with one JSON object that matches this JSON Schema") and json.dumps(SCHEMA) in text


class Generating(BaseHTTPRequestHandler):
    """Stands in for Ollama's /api/generate and records what it was sent."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = json.dumps({"models": [{"name": "chat:8b", "details": {"family": "llama"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.sent.append((self.path, body))
        if self.path == "/api/show":
            data = json.dumps(CHAT_MODEL).encode()
        else:
            data = (json.dumps({"response": '{"tool": "answer"}', "done": False}) + "\n" + json.dumps({"response": "", "done": True, "done_reason": "stop", "eval_count": 5, "eval_duration": 10**9}) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_ollama_is_sent_the_schema_as_the_format_of_the_reply():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Generating)
    server.sent = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": address})
        held = router.generate(ProviderRequest(prompt="Pick a tool.", model="chat:8b", provider_order=["ollama", "fallback"], response_schema=SCHEMA))
        free = router.generate(ProviderRequest(prompt="Say hello.", model="chat:8b", provider_order=["ollama", "fallback"]))
    finally:
        server.shutdown()
        server.server_close()

    assert held.success and held.text == '{"tool": "answer"}' and free.success
    generated = [body for path, body in server.sent if path == "/api/generate"]
    assert generated[0]["format"] == SCHEMA and generated[0]["prompt"] == "Pick a tool."  # the prompt itself is not padded with the schema
    assert "format" not in generated[1]
