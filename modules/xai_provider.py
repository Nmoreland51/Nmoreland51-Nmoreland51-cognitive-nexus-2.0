"""xAI Responses API adapter.

The key is read from the ``XAI_API_KEY`` environment variable at request time and is never
written into a payload, a log line, or an error message. Nothing in this module contacts
xAI unless a caller asks for a completion. Paid use stays off until the owner puts ``xai``
in the provider order (and, when it is not first, turns on cloud fallback).

Documented surface, read 2026-11-23 from https://docs.x.ai/developers/model-capabilities/text/generate-text
and the function-calling and streaming guides:

- ``POST https://api.x.ai/v1/responses``
- ``stream: true`` emits SSE events; text arrives as ``response.output_text.delta``
- a function call is an output item of type ``function_call`` with ``call_id``
- the follow-up sends ``function_call_output`` and, only when the owner has opted into
  server storage, ``previous_response_id``
- ``store`` defaults to true on xAI's side (kept for 30 days). This adapter sends
  ``store: false`` unless ``xai_store_responses`` is on, so prompts are not kept in that
  store unless the owner chose it. The prompt is still sent to xAI when this provider runs.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Generator
from typing import Any

import requests

API_URL = "https://api.x.ai/v1/responses"
DEFAULT_MODEL = "grok-4.7"
# Same budget as the other cloud adapters: the first attempts plus two retries.
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
OUTAGE_STATUS = frozenset({500, 502, 503, 504})


class XAIError(RuntimeError):
    """A failure talking to xAI. ``kind`` is stable for logs and failover decisions."""

    kind = "error"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class XAIAuthError(XAIError):
    kind = "auth"


class XAIRateLimitError(XAIError):
    kind = "rate_limit"


class XAIOutageError(XAIError):
    kind = "outage"


class XAITimeoutError(XAIError):
    kind = "timeout"


class XAIConnectionError(XAIError):
    kind = "connection"


class XAIBadResponseError(XAIError):
    kind = "bad_response"


class XAIStreamError(XAIError):
    kind = "stream"


class XAIToolError(XAIError):
    kind = "tool"


def api_key() -> str:
    """The key from the environment, or an empty string when it is not set."""

    return os.environ.get("XAI_API_KEY", "").strip()


def configured() -> tuple[bool, str]:
    """Whether a key is present. Does not contact xAI."""

    if not api_key():
        return False, "XAI_API_KEY is not set."
    return True, "xAI API key is configured. No request is sent until this provider is asked to answer."


def data_destination(store: bool) -> str:
    """Where the prompt goes, in words the owner can read before and after a request."""

    if store:
        return (
            "xAI (https://api.x.ai). xai_store_responses is on, so xAI may keep this prompt and "
            "reply for up to 30 days."
        )
    return (
        "xAI (https://api.x.ai). xai_store_responses is off, so this request sets store=false and "
        "asks xAI not to keep it in the 30-day response store. The prompt is still sent to xAI to produce the answer."
    )


def _redact(text: str, key: str) -> str:
    cleaned = text or ""
    if key and len(key) >= 8 and key in cleaned:
        cleaned = cleaned.replace(key, "[redacted]")
    return cleaned


def _detail(response: requests.Response, key: str) -> str:
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        elif error:
            detail = str(error)
    if not detail:
        detail = (response.text or "")[:200]
    return _redact(detail or "no details", key)[:300]


def _status_error(response: requests.Response, key: str) -> XAIError:
    status = int(response.status_code)
    detail = _detail(response, key)
    if status in {401, 403}:
        return XAIAuthError(
            f"xAI rejected the credentials (HTTP {status}). The API key is not included in this message. {detail}",
            status=status,
        )
    if status == 429:
        return XAIRateLimitError(f"xAI rate limit (HTTP 429). {detail}", status=status)
    if status in OUTAGE_STATUS:
        return XAIOutageError(f"xAI is unavailable (HTTP {status}). {detail}", status=status)
    return XAIBadResponseError(f"xAI returned HTTP {status}. {detail}", status=status)


def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else None
        name = str(tool.get("name") or (function or {}).get("name") or "").strip()
        if tool.get("type") != "function" or not name:
            continue
        parameters = tool.get("parameters") if function is None else function.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        description = str(tool.get("description") or (function or {}).get("description") or "")
        normalized.append(
            {"type": "function", "name": name, "description": description, "parameters": parameters}
        )
    return normalized


def _input_items(prompt: str, system_prompt: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Responses ``input`` array. Prior turns win; ``prompt`` is the newest user turn."""

    items: list[dict[str, Any]] = []
    if messages:
        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content)
            items.append({"role": role, "content": content})
    else:
        if system_prompt:
            items.append({"role": "system", "content": system_prompt})
        items.append({"role": "user", "content": prompt})
        return items
    if system_prompt and not any(item["role"] == "system" for item in items):
        items.insert(0, {"role": "system", "content": system_prompt})
    if prompt and (not items or items[-1].get("role") != "user" or items[-1].get("content") != prompt):
        items.append({"role": "user", "content": prompt})
    return items


def _payload(
    *,
    model: str,
    input_items: list[dict[str, Any]],
    max_output_tokens: int,
    store: bool,
    reasoning_effort: str,
    tools: list[dict[str, Any]],
    previous_response_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": True,
        "store": bool(store),
        "max_output_tokens": int(max_output_tokens or 512),
    }
    effort = reasoning_effort.strip().lower()
    if effort:
        body["reasoning"] = {"effort": effort}
    if tools:
        body["tools"] = tools
    # previous_response_id only works for a response xAI kept. With store off, resend the turns.
    if store and previous_response_id:
        body["previous_response_id"] = previous_response_id
    return body


def _post(
    session: requests.Session,
    *,
    key: str,
    payload: dict[str, Any],
    timeout: float,
) -> requests.Response:
    """POST once per attempt. Auth failures are not retried. Rate limits and outages are."""

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response: requests.Response | None = None
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            response = session.post(API_URL, headers=headers, json=payload, timeout=(8.0, timeout), stream=True)
        except requests.Timeout as exc:
            if last:
                raise XAITimeoutError("xAI request timed out") from exc
            time.sleep(1.0 + 2.0 * attempt)
            continue
        except requests.ConnectionError as exc:
            if last:
                raise XAIConnectionError(
                    "could not connect to xAI (network or DNS): " + _redact(exc.__class__.__name__, key)
                ) from exc
            time.sleep(1.0 + 2.0 * attempt)
            continue
        if response.status_code in RETRYABLE_STATUS and not last and response.headers.get("x-should-retry") != "false":
            try:
                delay = float(response.headers.get("retry-after", ""))
            except ValueError:
                delay = 1.0 + 2.0 * attempt
            time.sleep(min(max(delay, 0.5), 15.0))
            continue
        if not response.ok:
            raise _status_error(response, key)
        return response
    if response is None:
        raise XAIConnectionError("could not connect to xAI (network or DNS)")
    if not response.ok:
        raise _status_error(response, key)
    return response


def _events(response: requests.Response) -> Generator[dict[str, Any], None, None]:
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = str(raw).strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            if line == "[DONE]":
                return
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise XAIBadResponseError("xAI stream sent a line that was not JSON") from exc
        if not isinstance(payload, dict):
            raise XAIBadResponseError("xAI stream sent a non-object event")
        yield payload


def _as_output(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _run_tool(
    call: dict[str, Any],
    handler: Callable[[str, dict[str, Any]], Any] | None,
    tool_outputs: dict[str, str],
    recorded: list[dict[str, Any]],
) -> dict[str, Any]:
    call_id = str(call.get("call_id") or "").strip()
    name = str(call.get("name") or "").strip()
    if not call_id or not name:
        raise XAIBadResponseError("xAI tool call was missing call_id or name")
    raw_arguments = call.get("arguments") if call.get("arguments") is not None else "{}"
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise XAIBadResponseError("xAI tool arguments were not valid JSON") from exc
    elif isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        raise XAIBadResponseError("xAI tool arguments were not an object")
    if not isinstance(arguments, dict):
        raise XAIBadResponseError("xAI tool arguments were not an object")
    repeated = call_id in tool_outputs
    if repeated:
        output = tool_outputs[call_id]
    else:
        if handler is None:
            raise XAIToolError(f"xAI requested tool {name} and no tool handler is configured")
        # Reserve the id before the handler runs so a retry cannot fire the side effect twice.
        tool_outputs[call_id] = ""
        try:
            output = _as_output(handler(name, arguments))
        except XAIError:
            raise
        except Exception as exc:
            output = json.dumps({"error": "tool failed", "detail": _redact(str(exc), api_key())[:200]})
            tool_outputs[call_id] = output
            raise XAIToolError(f"tool {name} failed") from exc
        tool_outputs[call_id] = output
    recorded.append({"call_id": call_id, "name": name, "repeated": repeated})
    return {"type": "function_call_output", "call_id": call_id, "output": output}


def stream_completion(
    session: requests.Session,
    *,
    model: str,
    prompt: str,
    system_prompt: str = "",
    messages: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    previous_response_id: str = "",
    max_output_tokens: int = 512,
    store: bool = False,
    reasoning_effort: str = "low",
    timeout: float = 120.0,
    tool_outputs: dict[str, str] | None = None,
    usage_out: dict[str, Any] | None = None,
) -> Generator[str, None, None]:
    """Yield text deltas from xAI. Tool calls are executed at most once per ``call_id``.

    ``usage_out`` is filled in as the turn finishes: model, token counts, data destination,
    response id, and the tool calls that ran. A failure raises ``XAIError`` and does not
    yield a substitute sentence.
    """

    key = api_key()
    if not key:
        raise XAIAuthError("XAI_API_KEY is not set.")
    remembered = tool_outputs if tool_outputs is not None else {}
    usage = usage_out if usage_out is not None else {}
    normalized_tools = _normalize_tools(list(tools or []))
    input_items = _input_items(prompt, system_prompt, list(messages or []))
    prior_id = previous_response_id if store else ""
    recorded: list[dict[str, Any]] = list(usage.get("tool_calls") or [])
    usage["data_destination"] = data_destination(store)
    usage["store"] = bool(store)
    yielded_any = False

    for _round in range(4):
        payload = _payload(
            model=model,
            input_items=input_items,
            max_output_tokens=max_output_tokens,
            store=store,
            reasoning_effort=reasoning_effort,
            tools=normalized_tools,
            previous_response_id=prior_id,
        )
        response = _post(session, key=key, payload=payload, timeout=timeout)
        function_calls: list[dict[str, Any]] = []
        output_items: list[dict[str, Any]] = []
        saw_terminal = False
        try:
            for event in _events(response):
                kind = str(event.get("type") or "")
                if kind == "response.output_text.delta":
                    delta = str(event.get("delta") or "")
                    if delta:
                        yielded_any = True
                        yield delta
                elif kind == "response.output_text.done" and not yielded_any:
                    text = str(event.get("text") or "")
                    if text:
                        yielded_any = True
                        yield text
                elif kind == "response.output_item.done":
                    item = event.get("item")
                    if isinstance(item, dict):
                        output_items.append(item)
                        if item.get("type") == "function_call":
                            function_calls.append(item)
                elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                    saw_terminal = True
                    raw_body = event.get("response")
                    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
                    usage["model"] = str(body.get("model") or model)
                    usage["response_id"] = str(body.get("id") or usage.get("response_id") or "")
                    raw_usage = body.get("usage")
                    token_usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
                    usage["input_tokens"] = int(token_usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0)
                    usage["output_tokens"] = int(token_usage.get("output_tokens") or token_usage.get("completion_tokens") or 0)
                    raw_output = body.get("output")
                    if not output_items and isinstance(raw_output, list):
                        output_items = [item for item in raw_output if isinstance(item, dict)]
                        function_calls = [item for item in output_items if item.get("type") == "function_call"]
                    if kind == "response.failed":
                        raw_error = body.get("error")
                        error: dict[str, Any] = raw_error if isinstance(raw_error, dict) else {}
                        message = _redact(str(error.get("message") or "xAI failed while generating"), key)
                        raise XAIBadResponseError(message)
                    if kind == "response.incomplete":
                        raise XAIStreamError("xAI stopped before the answer finished")
        except XAIError:
            raise
        except requests.Timeout as exc:
            if yielded_any:
                raise XAIStreamError("xAI stream dropped before the answer finished") from exc
            raise XAITimeoutError("xAI request timed out") from exc
        except requests.RequestException as exc:
            if yielded_any:
                raise XAIStreamError("xAI stream dropped before the answer finished") from exc
            raise XAIConnectionError("could not connect to xAI (network or DNS)") from exc
        if not saw_terminal:
            raise XAIStreamError("xAI stream ended before response.completed")
        if not yielded_any:
            for item in output_items:
                if item.get("type") != "message":
                    continue
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and part.get("text"):
                        yielded_any = True
                        yield str(part["text"])
        usage["tool_calls"] = recorded
        if not function_calls:
            if not yielded_any:
                raise XAIBadResponseError("xAI returned no text")
            return
        outputs = [_run_tool(call, tool_handler, remembered, recorded) for call in function_calls]
        usage["tool_calls"] = recorded
        if store and usage.get("response_id"):
            input_items = outputs
            prior_id = str(usage["response_id"])
        else:
            input_items = list(input_items) + output_items + outputs
            prior_id = ""
    raise XAIToolError("xAI kept requesting tools without producing an answer")
