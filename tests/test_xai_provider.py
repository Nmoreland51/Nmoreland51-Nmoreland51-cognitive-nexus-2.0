"""xAI adapter and failover. Every case here uses a stand-in HTTP session.

Live calls (a real Grok reply, three live turns, a live stream, a live tool call) are not
run from this file: no XAI_API_KEY is available. See docs/GROK_TEST_MATRIX.csv.
"""

from __future__ import annotations

import json

import pytest
import requests

from modules.answer_meta import answer_meta, describe_answer
from modules.nexus_config import DEFAULT_CONFIG
from modules.provider_router import CLOUD_SKIPPED, ProviderRequest, ProviderRouter
from modules.providers import FALLBACK_RESPONSE
from modules.xai_provider import API_URL, XAIAuthError, XAIRateLimitError, stream_completion
from tests.test_provider_truth import FakeSession, broken_ollama, make_router

KEY = "unit-test-xai-key"


def sse(*events: dict, status: int = 200, headers: dict | None = None):
    class Response:
        def __init__(self) -> None:
            self.status_code = status
            self.ok = status < 400
            self.headers = headers or {}
            self.text = json.dumps({"error": {"message": "stand-in"}})
            self._events = events

        def json(self) -> dict:
            return json.loads(self.text)

        def iter_lines(self, decode_unicode: bool = False):
            for event in self._events:
                yield "data: " + json.dumps(event)

    return Response()


def text_events(*parts: str, model: str = "grok-4.7", response_id: str = "resp_1") -> list[dict]:
    events = [{"type": "response.output_text.delta", "delta": part} for part in parts]
    events.append(
        {
            "type": "response.completed",
            "response": {
                "id": response_id,
                "model": model,
                "status": "completed",
                "usage": {"input_tokens": 12, "output_tokens": 4},
            },
        }
    )
    return events


def function_events(call_id: str = "call_1") -> list[dict]:
    return [
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": call_id,
                "name": "get_temperature",
                "arguments": json.dumps({"location": "Paris"}),
            },
        },
        {"type": "response.completed", "response": {"id": "resp_tool", "model": "grok-4.7", "status": "completed", "usage": {"input_tokens": 8, "output_tokens": 2}}},
    ]


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", KEY)
    monkeypatch.setattr("modules.xai_provider.time.sleep", lambda _seconds: None)


def test_missing_key_is_unavailable_and_makes_no_request(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    session = FakeSession()
    router = ProviderRouter({"provider_order": ["xai", "fallback"], "xai_model": "grok-4.7"})
    router._session = session  # type: ignore[assignment]

    info = router.detect_provider("xai", ttl=0)
    text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["xai", "fallback"])))

    assert info.available is False
    assert info.message == "XAI_API_KEY is not set."
    assert text.startswith(FALLBACK_RESPONSE)
    assert router.last_stream_metadata["success"] is False
    assert router.last_stream_metadata["fallback_reason"] == "XAI_API_KEY is not set."
    assert router.last_stream_metadata["attempts"][0]["error"] == "XAI_API_KEY is not set."
    # A missing key is "not set up", so the visible notice does not pretend a model answered.
    assert "from grok" not in text.lower()
    assert session.calls == []


def test_default_order_does_not_include_xai_and_store_is_off():
    assert "xai" not in DEFAULT_CONFIG["provider_order"]
    assert DEFAULT_CONFIG["xai_store_responses"] is False
    assert DEFAULT_CONFIG["allow_cloud_fallback"] is False
    order = ProviderRouter({}).provider_order(ProviderRequest(prompt="hello"))
    assert order == ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]


def test_stream_yields_each_delta_and_records_usage(key):
    session = FakeSession(sse(*text_events("Hel", "lo")))
    usage: dict = {}
    chunks = list(
        stream_completion(session, model="grok-4.7", prompt="Say hello", timeout=5, usage_out=usage)  # type: ignore[arg-type]
    )

    assert chunks == ["Hel", "lo"]
    assert usage["model"] == "grok-4.7"
    assert usage["input_tokens"] == 12 and usage["output_tokens"] == 4
    assert usage["response_id"] == "resp_1"
    assert "store=false" in usage["data_destination"]
    assert "https://api.x.ai" in usage["data_destination"]
    body = session.calls[0]["json"]
    assert body["stream"] is True and body["store"] is False
    assert body["model"] == "grok-4.7"
    assert "previous_response_id" not in body
    assert KEY not in json.dumps(body)
    assert session.calls[0]["url"] == API_URL


def test_multi_turn_sends_three_turns(key):
    session = FakeSession(sse(*text_events("4")))
    messages = [
        {"role": "user", "content": "I have 2 cats."},
        {"role": "assistant", "content": "Two cats."},
    ]
    "".join(stream_completion(session, model="grok-4.7", prompt="How many if I get 2 more?", messages=messages, store=False))  # type: ignore[arg-type]
    sent = session.calls[0]["json"]["input"]
    assert [item["content"] for item in sent] == ["I have 2 cats.", "Two cats.", "How many if I get 2 more?"]


def test_tool_call_runs_once_and_is_not_repeated(key):
    session = FakeSession(sse(*function_events()), sse(*text_events("It is 72.")))
    calls: list[tuple[str, dict]] = []

    def handler(name, arguments):
        calls.append((name, arguments))
        return {"temperature": 72}

    remembered: dict[str, str] = {}
    usage: dict = {}
    text = "".join(
        stream_completion(
            session,  # type: ignore[arg-type]
            model="grok-4.7",
            prompt="Temperature in Paris?",
            tools=[{"type": "function", "name": "get_temperature", "parameters": {"type": "object", "properties": {}}}],
            tool_handler=handler,
            tool_outputs=remembered,
            usage_out=usage,
        )
    )

    assert text == "It is 72."
    assert calls == [("get_temperature", {"location": "Paris"})]
    assert usage["tool_calls"][0]["call_id"] == "call_1"
    follow_up = session.calls[1]["json"]["input"]
    assert follow_up[-1]["type"] == "function_call_output"
    assert follow_up[-1]["call_id"] == "call_1"
    assert "72" in follow_up[-1]["output"]

    session.responses.append(sse(*function_events()))
    session.responses.append(sse(*text_events("Still 72.")))
    text2 = "".join(
        stream_completion(
            session,  # type: ignore[arg-type]
            model="grok-4.7",
            prompt="Again?",
            tools=[{"type": "function", "name": "get_temperature", "parameters": {"type": "object", "properties": {}}}],
            tool_handler=handler,
            tool_outputs=remembered,
            usage_out={},
        )
    )
    assert text2 == "Still 72."
    assert calls == [("get_temperature", {"location": "Paris"})]
    assert usage["tool_calls"][0]["repeated"] is False


def test_auth_error_does_not_leak_the_key_or_retry(key):
    session = FakeSession()
    session.responses.append(sse(status=401))
    with pytest.raises(XAIAuthError) as raised:
        "".join(stream_completion(session, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]
    assert raised.value.kind == "auth" and raised.value.status == 401
    assert KEY not in str(raised.value)
    assert len(session.calls) == 1


def test_rate_limit_is_retried_then_reported(key):
    session = FakeSession(sse(status=429, headers={"retry-after": "0"}), sse(*text_events("ok")))
    text = "".join(stream_completion(session, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]
    assert text == "ok"
    assert len(session.calls) == 2

    exhausted = FakeSession(sse(status=429), sse(status=429), sse(status=429))
    with pytest.raises(XAIRateLimitError) as raised:
        "".join(stream_completion(exhausted, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]
    assert raised.value.kind == "rate_limit"
    assert len(exhausted.calls) == 3


def test_outage_timeout_and_connection_keep_their_kinds(key):
    from modules.xai_provider import XAIConnectionError, XAIOutageError, XAITimeoutError

    outage = FakeSession(sse(status=503), sse(status=503), sse(status=503))
    with pytest.raises(XAIOutageError) as outage_error:
        "".join(stream_completion(outage, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]
    assert outage_error.value.status == 503

    timed = FakeSession(requests.Timeout("timed out"), requests.Timeout("timed out"), requests.Timeout("timed out"))
    with pytest.raises(XAITimeoutError):
        "".join(stream_completion(timed, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]

    down = FakeSession(requests.ConnectionError("dns"), requests.ConnectionError("dns"), requests.ConnectionError("dns"))
    with pytest.raises(XAIConnectionError) as connection_error:
        "".join(stream_completion(down, model="grok-4.7", prompt="hello"))  # type: ignore[arg-type]
    assert connection_error.value.kind == "connection"
    assert KEY not in str(connection_error.value)


def test_a_provider_failure_is_not_a_successful_answer(key):
    router = make_router({"xai": ["grok-4.7"]})
    router._session = FakeSession(sse(status=503), sse(status=503), sse(status=503))  # type: ignore[assignment]
    result = router.generate(ProviderRequest(prompt="hello", provider_order=["xai", "fallback"], model="grok-4.7"))

    assert result.success is False
    assert result.provider == "fallback"
    assert result.text.startswith(FALLBACK_RESPONSE)
    assert "unavailable" in result.text.lower() or "503" in result.text
    kinds = [item.get("error_kind") for item in router.last_stream_metadata["attempts"]]
    assert "outage" in kinds


def test_openai_503_routes_to_xai_only_when_fallback_is_enabled(key):
    def fail_openai(_request, _info):
        raise RuntimeError("OpenAI API returned HTTP 503: unavailable")

    router, calls = _router_with_openai_down(fail_openai)
    blocked = "".join(
        router.stream(ProviderRequest(prompt="private notes", provider_order=["openai", "xai", "fallback"], model="grok-4.7"))
    )
    assert calls == []
    assert FALLBACK_RESPONSE in blocked
    assert router.last_stream_metadata["skipped_cloud"] == ["xai"]
    assert any(item.get("error") == CLOUD_SKIPPED and item.get("provider") == "xai" for item in router.last_stream_metadata["attempts"])

    router, calls = _router_with_openai_down(fail_openai)
    router.config["allow_cloud_fallback"] = True
    text = "".join(
        router.stream(
            ProviderRequest(
                prompt="private notes",
                provider_order=["openai", "xai", "fallback"],
                model="grok-4.7",
                allow_cloud_fallback=True,
            )
        )
    )
    assert text == "from grok"
    assert [call["url"] for call in calls] == [API_URL]
    meta = router.last_stream_metadata
    assert meta["success"] is True and meta["provider"] == "xai" and meta["model"] == "grok-4.7"
    assert meta["failover_from"] == "openai"
    assert "503" in meta["failover_reason"]
    assert "store=false" in meta["data_destination"]
    label = describe_answer(answer_meta({"provider": "xai", "model": "grok-4.7", "success": True, **meta}))
    assert "xAI / grok-4.7" in label
    assert "sent to xAI" in label
    assert "Switched from openai" in label


def _router_with_openai_down(fail_openai):
    router = make_router({"openai": ["gpt-4.1-mini"], "xai": ["grok-4.7"]}, {"allow_cloud_fallback": False, "xai_store_responses": False})
    router._generate_openai = fail_openai  # type: ignore[method-assign]
    session = FakeSession(sse(*text_events("from grok")))
    router._session = session  # type: ignore[assignment]
    return router, session.calls


def test_provider_order_is_what_the_owner_set(key):
    first = make_router({"xai": ["grok-4.7"], "openai": ["gpt-4.1-mini"]})
    first._session = FakeSession(sse(*text_events("grok first")))  # type: ignore[assignment]
    first._generate_openai = lambda *_args: (_ for _ in ()).throw(AssertionError("openai was contacted"))  # type: ignore[method-assign]
    text = "".join(first.stream(ProviderRequest(prompt="hello", provider_order=["xai", "openai", "fallback"], allow_cloud_fallback=False)))
    assert text == "grok first"
    assert len(first._session.calls) == 1

    second = make_router({"openai": ["gpt-4.1-mini"], "xai": ["grok-4.7"]}, {"allow_cloud_fallback": True})
    second._generate_openai = lambda *_args: "openai first"  # type: ignore[method-assign]
    second._session = FakeSession(sse(*text_events("should not run")))  # type: ignore[assignment]
    text = "".join(second.stream(ProviderRequest(prompt="hello", provider_order=["openai", "xai", "fallback"], allow_cloud_fallback=True)))
    assert text == "openai first"
    assert second._session.calls == []


def test_grok_model_names_are_not_sent_to_openai():
    from modules.provider_router import ProviderInfo, _cloud_model

    openai = ProviderInfo(name="openai", available=True, message="", models=["gpt-4.1-mini"])
    xai = ProviderInfo(name="xai", available=True, message="", models=["grok-4.7"])
    assert _cloud_model("openai", "grok-4.7", openai) == "gpt-4.1-mini"
    assert _cloud_model("xai", "gpt-4.1-mini", xai) == "grok-4.7"
    assert _cloud_model("xai", "grok-4", xai) == "grok-4"


def test_mid_stream_failure_does_not_splice_another_answer(key):
    from modules.xai_provider import XAIStreamError

    router = make_router({"xai": ["grok-4.7"], "openai": ["gpt-4.1-mini"]}, {"allow_cloud_fallback": True})

    def die_midway(*_args, **_kwargs):
        yield "Partial "
        raise XAIStreamError("xAI stream dropped before the answer finished")

    openai_calls: list[str] = []
    router._stream_xai = die_midway  # type: ignore[method-assign]
    router._generate_openai = lambda *_args: openai_calls.append("openai") or "second answer"  # type: ignore[method-assign]
    text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["xai", "openai", "fallback"], allow_cloud_fallback=True)))

    assert text.startswith("Partial ")
    assert "second answer" not in text
    assert FALLBACK_RESPONSE not in text
    assert openai_calls == []
    assert router.last_stream_metadata["partial"] is True
    assert router.last_stream_metadata["success"] is False


def test_tool_failure_does_not_run_the_tool_twice_or_ask_the_next_provider(key):
    router = make_router({"xai": ["grok-4.7"], "openai": ["gpt-4.1-mini"]}, {"allow_cloud_fallback": True})
    router._session = FakeSession(sse(*function_events()), sse(status=503), sse(status=503), sse(status=503))  # type: ignore[assignment]
    ran: list[str] = []

    def handler(name, _arguments):
        ran.append(name)
        return {"temperature": 1}

    openai_calls: list[str] = []
    router._generate_openai = lambda *_args: openai_calls.append("openai") or "nope"  # type: ignore[method-assign]
    result = router.generate(
        ProviderRequest(
            prompt="temperature?",
            provider_order=["xai", "openai", "fallback"],
            allow_cloud_fallback=True,
            tools=[{"type": "function", "name": "get_temperature", "parameters": {"type": "object", "properties": {}}}],
            tool_handler=handler,
            model="grok-4.7",
        )
    )

    assert ran == ["get_temperature"]
    assert openai_calls == []
    assert result.success is False
    assert router.last_stream_metadata.get("tool_side_effect") is True
    assert "call_1" in router._tool_outputs


def test_disabled_fallback_never_contacts_xai_even_when_the_key_is_set(key):
    router = make_router({"ollama": ["llama3.2:3b"], "xai": ["grok-4.7"]})
    router._stream_ollama = broken_ollama  # type: ignore[method-assign]
    router._session = FakeSession(sse(*text_events("should not be asked")))  # type: ignore[assignment]
    text = "".join(router.stream(ProviderRequest(prompt="notes", provider_order=["ollama", "xai", "fallback"])))
    assert router._session.calls == []
    assert text.startswith(FALLBACK_RESPONSE)
    assert "xai" in router.last_stream_metadata["skipped_cloud"]
