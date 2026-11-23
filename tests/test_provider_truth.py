"""A provider counts as working only when it produced text, a failed model is never passed off
as an answer, and prompts do not leave this machine unless the user chose that."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from modules import event_log, nexus_config
from modules.nexus_config import DEFAULT_ANTHROPIC_MODEL, DEFAULT_CONFIG, RETIRED_MODEL_IDS, current_model_id
from modules.provider_router import (
    ANTHROPIC_FALLBACK_BETA,
    ANTHROPIC_MAX_TOKENS,
    CLOUD_SKIPPED,
    ModelUnavailableError,
    ProviderInfo,
    ProviderRequest,
    ProviderRouter,
    _cloud_model,
    estimate_cost_usd,
)
from modules.providers import FALLBACK_RESPONSE

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_router(available: dict[str, list[str]], config: dict | None = None) -> ProviderRouter:
    """A router whose providers are 'set up' exactly as described, with no network access."""

    router = ProviderRouter({"provider_order": list(available) + ["fallback"], **(config or {})})

    def detect(name: str, ttl=None) -> ProviderInfo:
        if name == "fallback":
            return ProviderInfo(name="fallback", available=True, message="fallback")
        if name in available:
            return ProviderInfo(name=name, available=True, message="ok", models=list(available[name]))
        return ProviderInfo(name=name, available=False, message=f"{name} is not set up.")

    router.detect_provider = detect  # type: ignore[method-assign]
    return router


def meta_error(router: ProviderRouter) -> str:
    return str(router.last_stream_metadata["attempts"][0].get("error"))


def broken_ollama(_request, _info, _model):
    raise RuntimeError("connection refused")
    yield ""  # pragma: no cover


class FakeResponse:
    def __init__(self, status: int = 200, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records each request."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None, **_kwargs):
        self.calls.append({"url": url, "headers": dict(headers or {}), "json": json, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def claude_message(text: str = "Paris.", **extra) -> dict:
    body = {
        "model": "claude-sonnet-5-5",
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    body.update(extra)
    return body


# --- the fallback notice is never a model answer ---------------------------------------------------


def test_generate_reports_failure_when_only_the_fallback_notice_was_served():
    router = make_router({"ollama": ["llama3.2:3b"]})
    router._stream_ollama = broken_ollama  # type: ignore[method-assign]

    result = router.generate(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"]))

    assert result.success is False
    assert result.provider == "fallback"
    assert result.text.startswith(FALLBACK_RESPONSE)
    assert "ollama: connection refused" in result.text  # the reply names what failed
    assert result.error == "ollama: connection refused"
    assert router.last_stream_metadata["success"] is False


def test_generate_or_raise_refuses_to_return_the_fallback_notice():
    router = make_router({"ollama": ["llama3.2:3b"]})
    router._stream_ollama = broken_ollama  # type: ignore[method-assign]

    with pytest.raises(ModelUnavailableError) as raised:
        router.generate_or_raise(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"]))

    assert "ollama: connection refused" in str(raised.value)
    assert raised.value.attempts[0]["provider"] == "ollama"


def test_generate_succeeds_only_with_a_real_model_answer():
    router = make_router({"ollama": ["llama3.2:3b"]})
    router._stream_ollama = lambda _request, _info, _model: iter(["Hello ", "there."])  # type: ignore[method-assign]

    result = router.generate_or_raise(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"]))

    assert result.success is True
    assert (result.provider, result.model, result.text) == ("ollama", "llama3.2:3b", "Hello there.")


def test_failures_and_fallbacks_are_recorded_as_separate_events():
    router = make_router({"ollama": ["llama3.2:3b"]})
    router._stream_ollama = broken_ollama  # type: ignore[method-assign]

    "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"])))

    counts = event_log.event_counts()
    assert counts["model_failure"] == 1
    assert counts["provider_fallback"] == 1
    assert counts["tool_failure"] == 0
    assert event_log.recent_events(kind="model_failure")[0]["provider"] == "ollama"


def test_an_answer_cut_off_midway_is_marked_partial_and_not_glued_to_another_answer():
    router = make_router({"ollama": ["llama3.2:3b"], "anthropic": ["claude-sonnet-5-5"]}, {"allow_cloud_fallback": True})

    def dies_midway(_request, _info, _model):
        yield "The capital of France "
        raise requests.ReadTimeout("read timed out")

    cloud_calls: list[str] = []
    router._stream_ollama = dies_midway  # type: ignore[method-assign]
    router._generate_anthropic = lambda request, info: cloud_calls.append("anthropic") or "Paris."  # type: ignore[method-assign]

    text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "anthropic", "fallback"])))

    assert text.startswith("The capital of France ")
    assert "[The answer was cut off: ollama: no reply arrived before the time limit]" in text
    assert "read timed out" in meta_error(router)  # the raw error is kept for Diagnostics
    assert FALLBACK_RESPONSE not in text
    assert cloud_calls == []  # no second answer appended to the first
    meta = router.last_stream_metadata
    assert (meta["provider"], meta["success"], meta["partial"]) == ("ollama", False, True)


# --- cloud providers are never used silently ---------------------------------------------------------


def cloud_router(config: dict | None = None) -> tuple[ProviderRouter, list[str]]:
    router = make_router({"ollama": ["llama3.2:3b"], "anthropic": ["claude-sonnet-5-5"], "openai": ["gpt-4.1-mini"]}, config)
    calls: list[str] = []
    router._stream_ollama = broken_ollama  # type: ignore[method-assign]
    router._generate_anthropic = lambda request, info: calls.append("anthropic") or "cloud answer"  # type: ignore[method-assign]
    router._generate_openai = lambda request, info: calls.append("openai") or "cloud answer"  # type: ignore[method-assign]
    return router, calls


LOCAL_FIRST = ["ollama", "openai", "anthropic", "fallback"]


def test_local_failure_does_not_send_the_prompt_to_a_configured_cloud_provider():
    router, calls = cloud_router()

    text = "".join(router.stream(ProviderRequest(prompt="my private notes", provider_order=LOCAL_FIRST)))

    assert calls == []
    assert text.startswith(FALLBACK_RESPONSE)
    assert "openai, anthropic is set up but was not used" in text
    meta = router.last_stream_metadata
    assert meta["skipped_cloud"] == ["openai", "anthropic"]
    skipped = [item for item in meta["attempts"] if item.get("error") == CLOUD_SKIPPED]
    assert [item["provider"] for item in skipped] == ["openai", "anthropic"]
    assert event_log.event_counts()["provider_skipped"] == 2


def test_cloud_fallback_runs_when_the_saved_setting_allows_it():
    router, calls = cloud_router({"allow_cloud_fallback": True})

    text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=LOCAL_FIRST)))

    assert calls == ["openai"]
    assert text == "cloud answer"
    assert router.last_stream_metadata["provider"] == "openai"


def test_a_request_can_allow_or_forbid_cloud_fallback_regardless_of_the_saved_setting():
    allowed, allowed_calls = cloud_router({"allow_cloud_fallback": False})
    "".join(allowed.stream(ProviderRequest(prompt="hello", provider_order=LOCAL_FIRST, allow_cloud_fallback=True)))
    assert allowed_calls == ["openai"]

    forbidden, forbidden_calls = cloud_router({"allow_cloud_fallback": True})
    "".join(forbidden.stream(ProviderRequest(prompt="hello", provider_order=LOCAL_FIRST, allow_cloud_fallback=False)))
    assert forbidden_calls == []


def test_a_cloud_provider_the_user_put_first_is_used_without_the_fallback_setting():
    router, calls = cloud_router()

    text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["anthropic", "ollama", "fallback"])))

    assert calls == ["anthropic"]
    assert text == "cloud answer"


def test_cloud_fallback_setting_accepts_text_values_from_env_files():
    assert make_router({}, {"allow_cloud_fallback": "true"}).cloud_fallback_allowed() is True
    assert make_router({}, {"allow_cloud_fallback": "false"}).cloud_fallback_allowed() is False
    assert make_router({}).cloud_fallback_allowed() is False


def test_cloud_providers_are_only_asked_for_their_own_models():
    openai = ProviderInfo(name="openai", available=True, message="ok", models=["gpt-4.1-mini"])
    claude = ProviderInfo(name="anthropic", available=True, message="ok", models=["claude-sonnet-5-5"])

    # A local model whose name starts with "o" used to be sent to OpenAI as a model name.
    assert _cloud_model("openai", "orca-mini", openai) == "gpt-4.1-mini"
    assert _cloud_model("openai", "dolphin3:8b", openai) == "gpt-4.1-mini"
    assert _cloud_model("openai", "gpt-5", openai) == "gpt-5"
    assert _cloud_model("openai", "o3", openai) == "o3"
    assert _cloud_model("anthropic", "dolphin3:8b", claude) == "claude-sonnet-5-5"
    assert _cloud_model("anthropic", "claude-opus-5-5", claude) == "claude-opus-5-5"


# --- a provider is "working" only after it produced text ------------------------------------------------


def test_verify_ollama_records_a_real_generation(monkeypatch):
    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": "http://ollama.test"})
    session = FakeSession(FakeResponse(payload={"response": "OK"}))
    monkeypatch.setattr("modules.provider_router.OLLAMA_SESSION", session)

    record = router.verify_ollama("llama3.2:3b")

    assert record["ok"] is True and record["error"] == ""
    assert router.verification("ollama", "llama3.2:3b") == record
    assert router.latest_verification("ollama") == record
    sent = session.calls[0]
    assert sent["url"] == "http://ollama.test/api/generate"
    assert sent["json"]["model"] == "llama3.2:3b"
    assert sent["json"]["options"]["num_predict"] == 4


def test_verify_ollama_fails_when_the_model_is_listed_but_does_not_answer(monkeypatch):
    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": "http://ollama.test"})
    monkeypatch.setattr("modules.provider_router.OLLAMA_SESSION", FakeSession(FakeResponse(payload={"response": "  "})))

    record = router.verify_ollama("llama3.2:3b")

    assert record["ok"] is False
    assert "no text" in record["error"]
    assert event_log.event_counts()["model_failure"] == 1


def test_verify_ollama_reports_a_dead_server(monkeypatch):
    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": "http://ollama.test"})
    monkeypatch.setattr("modules.provider_router.OLLAMA_SESSION", FakeSession(requests.ConnectionError("refused")))

    record = router.verify_ollama("llama3.2:3b")

    assert record["ok"] is False
    assert record["error"] == "Ollama at http://ollama.test: could not connect (is it running?)"
    assert router.verification("ollama", "other-model") is None


def test_a_real_answer_or_failure_updates_what_is_known_about_a_provider():
    router = make_router({"ollama": ["llama3.2:3b"]})
    router._stream_ollama = lambda _request, _info, _model: iter(["hi"])  # type: ignore[method-assign]
    "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"])))
    assert router.latest_verification("ollama")["ok"] is True
    assert router.latest_verification("ollama")["source"] == "answer"

    router._stream_ollama = broken_ollama  # type: ignore[method-assign]
    "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"])))
    latest = router.verification("ollama", "llama3.2:3b")
    assert latest["ok"] is False and "connection refused" in latest["error"]


def test_ollama_connection_refused_is_retried_once(monkeypatch):
    class Stream(FakeResponse):
        def iter_lines(self, decode_unicode=True):
            yield json.dumps({"response": "Hi", "done": False})
            yield json.dumps({"response": "", "done": True, "eval_count": 1, "eval_duration": 1_000_000})

    session = FakeSession(requests.ConnectionError("refused"), Stream())
    monkeypatch.setattr("modules.provider_router.OLLAMA_SESSION", session)
    monkeypatch.setattr("modules.provider_router.time.sleep", lambda _seconds: None)
    router = ProviderRouter({"provider_order": ["ollama", "fallback"]})
    info = ProviderInfo(name="ollama", available=True, message="ok", models=["llama3.2:3b"], base_url="http://ollama.test")

    chunks = list(router._stream_ollama(ProviderRequest(prompt="hello"), info, "llama3.2:3b"))

    assert "".join(chunks) == "Hi"
    assert len(session.calls) == 2


def ollama_stream_router(monkeypatch, *lines: dict) -> tuple[ProviderRouter, ProviderInfo]:
    class Stream(FakeResponse):
        def iter_lines(self, decode_unicode=True):
            for line in lines:
                yield json.dumps(line)

    monkeypatch.setattr("modules.provider_router.OLLAMA_SESSION", FakeSession(Stream()))
    router = ProviderRouter({"provider_order": ["ollama", "fallback"]})
    info = ProviderInfo(name="ollama", available=True, message="ok", models=["llama3.2:3b"], base_url="http://ollama.test")
    return router, info


def test_ollama_stream_that_drops_before_finishing_is_an_error(monkeypatch):
    router, info = ollama_stream_router(monkeypatch, {"response": "The capital", "done": False})

    stream = router._stream_ollama(ProviderRequest(prompt="hello"), info, "llama3.2:3b")

    assert next(stream) == "The capital"
    with pytest.raises(RuntimeError, match="stopped before finishing"):
        next(stream)


def test_ollama_error_message_inside_the_stream_is_raised(monkeypatch):
    router, info = ollama_stream_router(monkeypatch, {"error": "model requires more system memory"})

    with pytest.raises(RuntimeError, match="more system memory"):
        list(router._stream_ollama(ProviderRequest(prompt="hello"), info, "llama3.2:3b"))


def test_ollama_reports_when_an_answer_hit_the_length_limit(monkeypatch):
    router, info = ollama_stream_router(
        monkeypatch,
        {"response": "A long answer", "done": False},
        {"response": "", "done": True, "done_reason": "length", "eval_count": 3, "eval_duration": 1_000_000_000},
    )

    assert "".join(router._stream_ollama(ProviderRequest(prompt="hello"), info, "llama3.2:3b")) == "A long answer"
    assert router._last_ollama_throughput["done_reason"] == "length"


# --- Claude API: current model, current request shape -----------------------------------------------


def anthropic_router(session: FakeSession, config: dict | None = None) -> tuple[ProviderRouter, ProviderInfo]:
    router = ProviderRouter({"provider_order": ["anthropic", "fallback"], **(config or {})})
    router._session = session  # type: ignore[assignment]
    info = ProviderInfo(name="anthropic", available=True, message="ok", models=[DEFAULT_ANTHROPIC_MODEL])
    return router, info


@pytest.fixture
def anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr("modules.provider_router.time.sleep", lambda _seconds: None)


def test_anthropic_request_uses_the_current_model_and_request_shape(anthropic_key):
    session = FakeSession(FakeResponse(payload=claude_message("Paris.")))
    router, info = anthropic_router(session)

    # The chat model picked for Ollama and a small local token budget must not leak into the call.
    request = ProviderRequest(prompt="Capital of France?", model="dolphin3:8b", system_prompt="Be brief.", max_tokens=140, options={"temperature": 0.2})
    text = router._generate_anthropic(request, info)

    assert text == "Paris."  # the thinking block is skipped, only text blocks are read
    sent = session.calls[0]
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    body = sent["json"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] >= ANTHROPIC_MAX_TOKENS  # thinking shares the budget with the reply
    assert body["system"] == "Be brief."
    assert body["messages"] == [{"role": "user", "content": "Capital of France?"}]
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default"
    assert sent["headers"]["anthropic-beta"] == ANTHROPIC_FALLBACK_BETA
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    # Current models reject sampling parameters and budgeted or disabled thinking.
    for rejected in ("temperature", "top_p", "top_k", "thinking"):
        assert rejected not in body


def test_anthropic_usage_and_estimated_cost_are_recorded(anthropic_key):
    router = make_router({"anthropic": ["claude-sonnet-5-5"]})
    router._session = FakeSession(FakeResponse(payload=claude_message("Paris.")))  # type: ignore[assignment]

    text = "".join(router.stream(ProviderRequest(prompt="Capital of France?", provider_order=["anthropic", "fallback"])))

    assert text == "Paris."
    meta = router.last_stream_metadata
    assert (meta["provider"], meta["model"], meta["success"]) == ("anthropic", "claude-sonnet-5-5", True)
    # 1000 input tokens at $2/M plus 200 output tokens at $10/M.
    assert meta["usage"] == {
        "model": "claude-sonnet-5-5",
        "input_tokens": 1000,
        "output_tokens": 200,
        "estimated_cost_usd": 0.004,
    }


def test_anthropic_refusal_is_an_error_not_an_answer(anthropic_key):
    declined = claude_message("", stop_reason="refusal", content=[], stop_details={"category": "cyber"})
    router, info = anthropic_router(FakeSession(FakeResponse(payload=declined)))

    with pytest.raises(RuntimeError, match="declined this request \\(category: cyber\\)"):
        router._generate_anthropic(ProviderRequest(prompt="hello"), info)


def test_anthropic_refusal_without_details_still_fails_cleanly(anthropic_key):
    declined = claude_message("", stop_reason="refusal", content=[], stop_details=None)
    router, info = anthropic_router(FakeSession(FakeResponse(payload=declined)))

    with pytest.raises(RuntimeError, match="category: unspecified"):
        router._generate_anthropic(ProviderRequest(prompt="hello"), info)


def test_anthropic_empty_reply_raises_instead_of_returning_the_fallback_notice(anthropic_key):
    empty = claude_message("", stop_reason="max_tokens", content=[{"type": "thinking", "thinking": ""}])
    router, info = anthropic_router(FakeSession(FakeResponse(payload=empty)))

    with pytest.raises(RuntimeError, match="no text \\(stop_reason: max_tokens\\)"):
        router._generate_anthropic(ProviderRequest(prompt="hello"), info)


def test_anthropic_retries_with_the_plain_request_when_optional_fields_are_rejected(anthropic_key):
    rejected = FakeResponse(400, {"error": {"type": "invalid_request_error", "message": "fallbacks: not supported for this model"}})
    session = FakeSession(rejected, FakeResponse(payload=claude_message("Paris.")))
    router, info = anthropic_router(session)

    assert router._generate_anthropic(ProviderRequest(prompt="hello"), info) == "Paris."
    second = session.calls[1]
    assert "fallbacks" not in second["json"] and "output_config" not in second["json"]
    assert "anthropic-beta" not in second["headers"]


def test_anthropic_error_message_comes_from_the_api(anthropic_key):
    not_found = FakeResponse(404, {"error": {"type": "not_found_error", "message": "model: claude-old"}})
    router, info = anthropic_router(FakeSession(not_found), {"anthropic_refusal_fallback": False, "anthropic_effort": ""})

    with pytest.raises(RuntimeError, match="Anthropic API returned HTTP 404: model: claude-old"):
        router._generate_anthropic(ProviderRequest(prompt="hello"), info)


def test_cloud_requests_retry_rate_limits_and_dropped_connections(anthropic_key):
    session = FakeSession(
        FakeResponse(429, {"error": {"message": "slow down"}}, {"retry-after": "1"}),
        requests.ConnectionError("reset"),
        FakeResponse(payload=claude_message("Paris.")),
    )
    router, info = anthropic_router(session)

    assert router._generate_anthropic(ProviderRequest(prompt="hello"), info) == "Paris."
    assert len(session.calls) == 3


def test_cloud_requests_do_not_retry_when_the_api_says_not_to(anthropic_key):
    session = FakeSession(FakeResponse(500, {"error": {"message": "broken"}}, {"x-should-retry": "false"}))
    router, info = anthropic_router(session)

    with pytest.raises(RuntimeError, match="HTTP 500: broken"):
        router._generate_anthropic(ProviderRequest(prompt="hello"), info)
    assert len(session.calls) == 1


def test_openai_empty_reply_raises_instead_of_returning_the_fallback_notice(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    router = ProviderRouter({"provider_order": ["openai", "fallback"]})
    router._session = FakeSession(FakeResponse(payload={"status": "incomplete", "output": []}))  # type: ignore[assignment]
    info = ProviderInfo(name="openai", available=True, message="ok", models=["gpt-4.1-mini"])

    with pytest.raises(RuntimeError, match="OpenAI returned no text \\(status: incomplete\\)"):
        router._generate_openai(ProviderRequest(prompt="hello"), info)


def test_cost_estimates():
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0
    assert estimate_cost_usd("claude-opus-5-5", 1_000_000, 0) == 4.0
    assert estimate_cost_usd("claude-haiku-5-5", 10_000, 1_000) == 0.0015
    # Haiku costs more once the prompt passes 100,000 tokens.
    assert estimate_cost_usd("claude-haiku-5-5", 200_000, 0) == 0.1
    assert estimate_cost_usd("some-unknown-model", 1000, 1000) is None


# --- configuration ----------------------------------------------------------------------------------


def test_default_claude_model_is_not_a_retired_one():
    assert DEFAULT_CONFIG["anthropic_model"] == DEFAULT_ANTHROPIC_MODEL == "claude-sonnet-5-5"
    assert DEFAULT_ANTHROPIC_MODEL not in RETIRED_MODEL_IDS
    assert not set(RETIRED_MODEL_IDS.values()) & set(RETIRED_MODEL_IDS)
    assert DEFAULT_CONFIG["allow_cloud_fallback"] is False


def test_retired_claude_model_ids_are_replaced_with_a_note():
    model, note = current_model_id("claude-sonnet-4-20250514")
    assert model == "claude-sonnet-5-5"
    assert "retired" in note and "claude-sonnet-4-20250514" in note
    assert current_model_id("claude-opus-5-5") == ("claude-opus-5-5", "")


def test_a_model_with_an_announced_shutdown_is_kept_until_the_date_then_replaced():
    from datetime import date

    before, warning = current_model_id("gpt-4.1-mini", today=date(2026, 11, 23))
    assert before == "gpt-4.1-mini"
    assert "2027-01-14" in warning and "gpt-6-luna" in warning

    after, note = current_model_id("gpt-4.1-mini", today=date(2027, 1, 14))
    assert after == "gpt-6-luna"
    assert "was shut down on 2027-01-14" in note

    assert current_model_id("claude-sonnet-4-5", today=date(2026, 12, 1))[0] == "claude-sonnet-5-5"


def test_a_saved_retired_model_id_is_replaced_when_config_loads(tmp_path, monkeypatch):
    saved = tmp_path / "nexus_config.json"
    saved.write_text(json.dumps({"anthropic_model": "claude-sonnet-4-20250514"}), encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ALLOW_CLOUD_FALLBACK", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(nexus_config, "load_env_file", lambda *args, **kwargs: None)

    config = nexus_config.load_runtime_config(saved)

    assert config["anthropic_model"] == "claude-sonnet-5-5"
    # Only the provider with a key gets a note; the OpenAI shutdown warning is not shown without one.
    assert len(config["model_id_notes"]) == 1 and "retired" in config["model_id_notes"][0]
    assert config["allow_cloud_fallback"] is False


def test_environment_can_turn_cloud_fallback_on(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_CLOUD_FALLBACK", "true")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(nexus_config, "load_env_file", lambda *args, **kwargs: None)

    config = nexus_config.load_runtime_config(tmp_path / "missing.json")

    assert config["allow_cloud_fallback"] is True
    assert config["anthropic_model"] == "claude-opus-5-5"
    assert config["model_id_notes"] == []


def test_shipped_config_files_do_not_name_retired_models():
    for relative in ("config/nexus_config.json", ".env.example", "modules/provider_router.py"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        named = [model for model in RETIRED_MODEL_IDS if model in text]
        assert named == [], f"{relative} still names retired model(s): {named}"
    shipped = json.loads((REPO_ROOT / "config" / "nexus_config.json").read_text(encoding="utf-8"))
    assert shipped["allow_cloud_fallback"] is False
