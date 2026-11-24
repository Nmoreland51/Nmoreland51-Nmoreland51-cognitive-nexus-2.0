"""Which of Ollama's installed models may be offered for chat.

Found in the running app on 2026-11-23: after an embedding model (all-minilm) was installed for
searching saved knowledge, the chat-model picker chose it as the default, because it sorts first.
An embedding model turns text into numbers and cannot answer anything.
"""

from __future__ import annotations

import app
from modules import providers
from modules.provider_router import ProviderRequest, ProviderRouter

# As returned by GET /api/tags on this machine.
ALL_MINILM = {"name": "all-minilm:latest", "details": {"family": "bert", "families": ["bert"], "parameter_size": "23M"}}
DOLPHIN = {"name": "dolphin3:8b", "details": {"family": "llama", "families": ["llama"], "parameter_size": "8.0B"}}


class FakeResponse:
    def __init__(self, models):
        self.models = models

    def raise_for_status(self):
        return None

    def json(self):
        return {"models": self.models}


def status_for(monkeypatch, models) -> providers.ProviderStatus:
    monkeypatch.setattr(providers.OLLAMA_SESSION, "get", lambda *_args, **_kwargs: FakeResponse(models))
    return providers.check_ollama_status("http://127.0.0.1:11434")


def test_an_embedding_model_is_not_offered_as_a_chat_model(monkeypatch):
    status = status_for(monkeypatch, [ALL_MINILM, DOLPHIN])

    assert status.models == ["dolphin3:8b"]
    assert status.embedding_models == ["all-minilm:latest"]
    assert "1 chat model(s)" in status.message and "all-minilm:latest" in status.message
    assert app.get_chat_model(status.models) == "dolphin3:8b"


def test_only_an_embedding_model_installed_means_no_chat_model(monkeypatch):
    status = status_for(monkeypatch, [ALL_MINILM])

    assert status.available and status.models == []
    assert "no chat model is installed" in status.message and "cannot chat" in status.message


def test_the_router_never_substitutes_an_embedding_model(monkeypatch):
    status_for(monkeypatch, [ALL_MINILM, DOLPHIN])
    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": "http://127.0.0.1:11434"})
    info = router.detect_provider("ollama")

    # No model named in the request (the content rule's check does this): the first CHAT model is used.
    assert router._resolve_model(ProviderRequest(prompt="x", model=""), info) == ("dolphin3:8b", "")
    chosen, note = router._resolve_model(ProviderRequest(prompt="x", model="all-minilm:latest"), info)
    assert chosen == "dolphin3:8b" and "all-minilm:latest" in note


def test_what_counts_as_an_embedding_model():
    families = [
        ({"name": "nomic-embed-text:latest", "details": {"family": "nomic-bert"}}, True),
        ({"name": "bge-m3:latest", "details": {"family": "bert", "families": ["bert"]}}, True),
        ({"name": "llama3.2:3b", "details": {"family": "llama"}}, False),
        ({"name": "qwen2.5-coder:7b", "details": {"family": "qwen2"}}, False),
        # A chat model whose name happens to contain a hint is still a chat model when Ollama says what it is.
        ({"name": "my-embedded-systems-tutor:latest", "details": {"family": "llama"}}, False),
        # An Ollama too old to report a family: fall back to the name.
        ({"name": "mxbai-embed-large:latest"}, True),
        ({"name": "all-minilm:latest", "details": {}}, True),
        ({"name": "mistral:7b"}, False),
    ]
    for entry, expected in families:
        assert providers.is_embedding_model(entry) is expected, entry["name"]
