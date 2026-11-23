"""Central provider fallback and streaming router."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator, Optional

import requests

from modules.event_log import record_event
from modules.nexus_config import DEFAULT_ANTHROPIC_MODEL, load_runtime_config
from modules.providers import FALLBACK_RESPONSE, OLLAMA_SESSION, check_ollama_status, get_ollama_base_url


@dataclass
class ProviderInfo:
    """Cached availability state for one provider."""

    name: str
    available: bool
    message: str
    models: list[str] = field(default_factory=list)
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderRequest:
    """Provider-agnostic text generation request."""

    prompt: str
    model: str = ""
    provider_order: list[str] = field(default_factory=list)
    base_url: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    timeout: float = 300.0
    system_prompt: str = ""
    max_tokens: int = 512
    # None = use the configured allow_cloud_fallback setting.
    allow_cloud_fallback: bool | None = None


@dataclass
class ProviderResult:
    """Normalized provider response."""

    text: str
    provider: str
    model: str = ""
    success: bool = True
    error: str = ""
    elapsed: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelUnavailableError(RuntimeError):
    """No real model produced an answer. Carries the provider attempts that were made."""

    def __init__(self, reason: str = "", attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(reason or "No model provider returned an answer.")
        self.attempts = list(attempts or [])


def _optional_available(module_name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module_name) is not None


def _needs_slow_startup_timeout(model: str) -> bool:
    """Return True for local Ollama models that often need a longer first-token window."""

    normalized = str(model or "").lower()
    return "blackhillsinfosec/" in normalized or "abliterated" in normalized


SLOW_STARTUP_OLLAMA_READ_TIMEOUT = 180.0

# Floor for Ollama's per-chunk read timeout. Intent-based caps (12s for casual chat) are
# too short for the first token on CPU-only machines, where loading the model and reading
# the prompt can take far longer. The read timeout applies between streamed chunks, so this
# floor only changes how long a stalled request waits, not how fast a healthy one answers.
OLLAMA_MIN_READ_TIMEOUT = float(os.environ.get("OLLAMA_MIN_READ_TIMEOUT", "120"))

# Ollama reloads the model whenever num_ctx changes (~6s on CPU). Using one minimum size for
# everyday chat and web answers keeps a single loaded copy; only long research prompts go larger.
OLLAMA_MIN_NUM_CTX = 2048
# How long Ollama keeps the model in memory after the last request (was 30m, which meant a
# reload after a short break). Override with ollama_keep_alive in config/nexus_config.json.
OLLAMA_DEFAULT_KEEP_ALIVE = "24h"


# Providers that send the prompt (and any memory or document text inside it) to another company.
CLOUD_PROVIDERS = frozenset({"openai", "anthropic"})
CLOUD_SKIPPED = "Skipped: cloud fallback is off, so the prompt stays on this machine."
FALLBACK_SERVED = "No model answered; this is the app's fallback notice."

# Current Claude models think before answering and thinking shares max_tokens with the reply, so
# the small budgets used for local models (140 tokens for casual chat) would be spent before any
# text is written. The cap is set high and answer length is steered by the prompt instead.
ANTHROPIC_MAX_TOKENS = 16000
ANTHROPIC_VERSION = "2023-06-01"
# Lets the API re-run a request on another model when a safety classifier declines it.
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
CLOUD_RETRIES = 2
# USD per million tokens (input, output), from Anthropic's model reference, read 2026-11-23.
# Prices change; treat the result as an estimate and check the provider's bill for the real cost.
CLOUD_PRICES = {
    "claude-fable-5-2": (8.0, 40.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
# Claude Haiku 5.5 is priced higher when the prompt is over 100,000 tokens.
HAIKU_LONG_PROMPT_TOKENS = 100_000
HAIKU_LONG_PROMPT_PRICE = (0.50, 2.50)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Rough cost of one request, or None when the model's price is not known."""

    price = CLOUD_PRICES.get(str(model or ""))
    if price is None:
        return None
    if model == "claude-haiku-5-5" and input_tokens > HAIKU_LONG_PROMPT_TOKENS:
        price = HAIKU_LONG_PROMPT_PRICE
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 6)


def _is_openai_model(name: str) -> bool:
    """True for names OpenAI serves; a local model called "orca-mini" must not be sent there."""

    return bool(re.match(r"^(gpt-|chatgpt-|o\d)", str(name or "")))


def _cloud_model(provider: str, requested: str, info: "ProviderInfo") -> str:
    """The model to ask a cloud provider for: the requested one if it belongs to that provider,
    otherwise the provider's configured default (the chat model picked for Ollama does not)."""

    requested = str(requested or "").strip()
    belongs = requested.startswith("claude") if provider == "anthropic" else _is_openai_model(requested)
    if belongs:
        return requested
    return info.models[0] if info.models else ""


def _plain_error(exc: Exception) -> str:
    """A short reason a person can read. The raw exception stays in the attempt log."""

    if isinstance(exc, requests.ConnectTimeout):
        return "the connection timed out"
    if isinstance(exc, requests.ReadTimeout):
        return "no reply arrived before the time limit"
    if isinstance(exc, requests.ConnectionError):
        return "could not connect (is it running?)"
    return str(exc)


def _describe_failure(result: "ProviderResult") -> str:
    """Why no model answered, including a configured cloud provider that was not allowed."""

    reason = result.error or "No model provider returned an answer."
    skipped = [str(item.get("provider")) for item in result.attempts if item.get("error") == CLOUD_SKIPPED]
    if skipped:
        reason += f" ({', '.join(skipped)} is set up but cloud fallback is off.)"
    return reason


def _fallback_text(failures: list[str], skipped_cloud: list[str] | None = None) -> str:
    """The fallback reply, naming the providers that were tried and why each failed."""

    text = FALLBACK_RESPONSE
    if failures:
        shown = "; ".join(failure if len(failure) <= 200 else failure[:199] + "…" for failure in failures[:3])
        text += f"\n\nWhat failed: {shown}"
    if skipped_cloud:
        text += (
            f"\n\n{', '.join(skipped_cloud)} is set up but was not used: cloud fallback is off, so your prompt "
            "stays on this machine. Turn on 'Allow cloud fallback' if you want it used when the local model fails."
        )
    return text


class ProviderRouter:
    """Detect and call configured providers with graceful fallback."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or load_runtime_config()
        self._status_cache: dict[str, tuple[float, ProviderInfo]] = {}
        self._hf_pipeline = None
        self._session = requests.Session()
        self.last_stream_metadata: dict[str, Any] = {}
        self._last_ollama_throughput: dict[str, Any] = {}
        self._last_cloud_usage: dict[str, Any] = {}
        # (provider, model) -> result of the last real test generation.
        self._verification: dict[tuple[str, str], dict[str, Any]] = {}

    def invalidate_status_cache(self) -> None:
        self._status_cache.clear()

    def warm_ollama(self, model: str, base_url: str = "") -> bool:
        """Load the chat model into Ollama before the first message (an empty prompt only loads it).

        Uses the same num_ctx and keep_alive as chat requests so the loaded copy gets reused.
        """

        if not model:
            return False
        url = (base_url or str(self.config.get("ollama_url") or get_ollama_base_url())).rstrip("/")
        try:
            response = OLLAMA_SESSION.post(
                f"{url}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "keep_alive": str(self.config.get("ollama_keep_alive", OLLAMA_DEFAULT_KEEP_ALIVE)),
                    "options": {"num_ctx": OLLAMA_MIN_NUM_CTX},
                },
                timeout=(5.0, 180.0),
            )
            return response.ok
        except requests.RequestException:
            return False

    def verify_ollama(self, model: str, base_url: str = "") -> dict[str, Any]:
        """Run a tiny real generation and record whether the model actually answers.

        Being listed by Ollama only proves the model file exists. This loads it (with the same
        context size and keep-alive as chat, so the copy is reused) and asks for a few tokens.
        """

        record: dict[str, Any] = {
            "provider": "ollama",
            "model": model,
            "ok": False,
            "seconds": 0.0,
            "error": "",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if not model:
            record["error"] = "No model selected."
            return record
        url = (base_url or str(self.config.get("ollama_url") or get_ollama_base_url())).rstrip("/")
        started = time.perf_counter()
        try:
            response = OLLAMA_SESSION.post(
                f"{url}/api/generate",
                json={
                    "model": model,
                    "prompt": "Reply with the single word OK.",
                    "stream": False,
                    "keep_alive": str(self.config.get("ollama_keep_alive", OLLAMA_DEFAULT_KEEP_ALIVE)),
                    "options": {"num_ctx": OLLAMA_MIN_NUM_CTX, "num_predict": 4, "temperature": 0},
                },
                timeout=(5.0, 180.0),
            )
            response.raise_for_status()
            if str(response.json().get("response", "")).strip():
                record["ok"] = True
            else:
                record["error"] = "The model returned no text."
        except (requests.RequestException, ValueError) as exc:
            record["error"] = f"Ollama at {url}: {_plain_error(exc)}"
        record["seconds"] = round(time.perf_counter() - started, 2)
        record["source"] = "test"
        self._verification[("ollama", model)] = record
        if not record["ok"]:
            record_event("model_failure", f"ollama/{model} failed its test generation", provider="ollama", model=model, error=record["error"])
        return record

    def verify_provider(self, name: str, model: str = "") -> dict[str, Any]:
        """Send one minimal real request to a provider. Cloud providers bill for it, so call this
        only when the user asks for a test."""

        info = self.detect_provider(name, ttl=0)
        chosen = model or (info.models[0] if info.models else "")
        if name == "ollama":
            return self.verify_ollama(chosen)
        record: dict[str, Any] = {
            "provider": name,
            "model": chosen,
            "ok": False,
            "seconds": 0.0,
            "error": "",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if not info.available:
            record["error"] = info.message
            return record
        request = ProviderRequest(prompt="Reply with the single word OK.", model=chosen, max_tokens=16, timeout=60.0)
        started = time.perf_counter()
        try:
            generator = getattr(self, f"_generate_{name}")
            record["ok"] = bool(str(generator(request, info)).strip())
            if not record["ok"]:
                record["error"] = "The provider returned no text."
        except Exception as exc:
            record["error"] = str(exc)
        record["seconds"] = round(time.perf_counter() - started, 2)
        record["source"] = "test"
        self._verification[(name, chosen)] = record
        if not record["ok"]:
            record_event("model_failure", f"{name}/{chosen} failed its test request", provider=name, model=chosen, error=record["error"])
        return record

    def verification(self, provider: str, model: str) -> dict[str, Any] | None:
        """Result of the last test generation for this provider and model, if one ran."""

        return self._verification.get((provider, model))

    def latest_verification(self, provider: str) -> dict[str, Any] | None:
        """The most recent proof (test prompt or real answer) for any model of this provider."""

        records = [record for (name, _model), record in self._verification.items() if name == provider]
        return max(records, key=lambda record: str(record.get("checked_at") or "")) if records else None

    def _note_outcome(self, provider: str, model: str, ok: bool, error: str = "") -> None:
        """A real request is the best evidence of whether a provider works; keep the latest."""

        self._verification[(provider, model)] = {
            "provider": provider,
            "model": model,
            "ok": ok,
            "seconds": None,
            "error": "" if ok else error,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "answer",
        }

    def cloud_fallback_allowed(self, request: ProviderRequest | None = None) -> bool:
        """Whether a cloud provider may be used when it is not the user's first choice."""

        if request is not None and request.allow_cloud_fallback is not None:
            return bool(request.allow_cloud_fallback)
        value = self.config.get("allow_cloud_fallback", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def detect_provider(self, name: str, ttl: Optional[float] = None) -> ProviderInfo:
        ttl = float(ttl if ttl is not None else self.config.get("provider_status_ttl_seconds", 45))
        cached = self._status_cache.get(name)
        now = time.time()
        if cached and now - cached[0] < ttl:
            return cached[1]

        detector = getattr(self, f"_detect_{name}", None)
        if detector is None:
            info = ProviderInfo(name=name, available=False, message="Unknown provider.")
        else:
            info = detector()
        self._status_cache[name] = (now, info)
        return info

    def detect_all(self, provider_order: Optional[list[str]] = None) -> list[ProviderInfo]:
        order = provider_order or list(self.config.get("provider_order", []))
        return [self.detect_provider(name) for name in order]

    def _detect_ollama(self) -> ProviderInfo:
        status = check_ollama_status(base_url=str(self.config.get("ollama_url") or get_ollama_base_url()), timeout=1.2)
        return ProviderInfo(
            name="ollama",
            available=status.available and bool(status.models),
            message=status.message,
            models=status.models,
            base_url=status.base_url,
        )

    def _detect_openai(self) -> ProviderInfo:
        if not os.environ.get("OPENAI_API_KEY"):
            return ProviderInfo(name="openai", available=False, message="OPENAI_API_KEY is not set.")
        return ProviderInfo(
            name="openai",
            available=True,
            message="OpenAI API key is configured.",
            models=[str(self.config.get("openai_model", "gpt-4.1-mini"))],
            base_url="https://api.openai.com/v1",
        )

    def _detect_anthropic(self) -> ProviderInfo:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return ProviderInfo(name="anthropic", available=False, message="ANTHROPIC_API_KEY is not set.")
        return ProviderInfo(
            name="anthropic",
            available=True,
            message="Anthropic API key is configured.",
            models=[str(self.config.get("anthropic_model") or DEFAULT_ANTHROPIC_MODEL)],
            base_url="https://api.anthropic.com/v1",
        )

    def _detect_huggingface_local(self) -> ProviderInfo:
        model = str(self.config.get("hf_local_model") or "").strip()
        if not model:
            return ProviderInfo(
                name="huggingface_local",
                available=False,
                message="HF_LOCAL_MODEL is not configured; local Transformers will stay lazy-disabled.",
            )
        packages = _optional_available("transformers") and _optional_available("torch")
        if not packages:
            return ProviderInfo(
                name="huggingface_local",
                available=False,
                message="Optional transformers/torch packages are not installed.",
            )
        return ProviderInfo(
            name="huggingface_local",
            available=True,
            message="Local Transformers backend is configured and will load on first use.",
            models=[model],
        )

    def _detect_fallback(self) -> ProviderInfo:
        return ProviderInfo(name="fallback", available=True, message="Fallback text provider is always available.")

    def provider_order(self, request: ProviderRequest) -> list[str]:
        order = request.provider_order or list(self.config.get("provider_order", []))
        return order or ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]

    def _resolve_model(self, request: ProviderRequest, info: ProviderInfo) -> tuple[str, str]:
        """Choose a usable model for a provider and explain stale selections."""

        requested = str(request.model or "").strip()
        if info.name == "ollama":
            if requested and requested in info.models:
                return requested, ""
            if info.models:
                selected = info.models[0]
                if requested:
                    return selected, f"Requested Ollama model '{requested}' is not installed; using '{selected}'."
                return selected, ""
            return "", "Ollama is running but no models are installed."
        if info.name in CLOUD_PROVIDERS:
            return _cloud_model(info.name, requested, info), ""
        if requested:
            return requested, ""
        if info.models:
            return info.models[0], ""
        return "", ""

    def generate(self, request: ProviderRequest) -> ProviderResult:
        """Generate text with the first provider that works.

        `success` is True only when a real model answered. When every provider failed the result
        carries the fallback text with success=False, so callers cannot mistake it for an answer.
        """

        started = time.perf_counter()
        try:
            text = "".join(self.stream(request)).strip()
        except Exception as exc:  # stream() reports provider errors itself; this is a last resort
            text = ""
            self.last_stream_metadata = {"provider": "fallback", "success": False, "attempts": [], "fallback_reason": str(exc)}
        meta = dict(self.last_stream_metadata or {})
        provider = str(meta.get("provider") or "fallback")
        answered = bool(text) and bool(meta.get("success")) and provider != "fallback"
        return ProviderResult(
            text=text or FALLBACK_RESPONSE,
            provider=provider,
            model=str(meta.get("model") or request.model or ""),
            success=answered,
            error="" if answered else str(meta.get("fallback_reason") or "No provider returned a usable response."),
            elapsed=time.perf_counter() - started,
            attempts=list(meta.get("attempts") or []),
        )

    def generate_or_raise(self, request: ProviderRequest) -> ProviderResult:
        """generate(), but raise ModelUnavailableError when no real model answered in full.

        Use this wherever the text is stored or shown as a model's work (summaries, reports,
        knowledge answers), so the fallback notice can never be saved as if it were an answer.
        """

        result = self.generate(request)
        if not result.success:
            raise ModelUnavailableError(_describe_failure(result), result.attempts)
        return result

    def stream(
        self,
        request: ProviderRequest,
        preferred_provider: str | None = None,
    ) -> Generator[str, None, None]:
        """Stream chunks from the first working provider.

        last_stream_metadata["success"] is True only when a real model answered in full. It is
        False when the fallback notice was served, and False with "partial": True when a model
        stopped part-way through an answer that had already started to appear.
        """

        order = [preferred_provider] if preferred_provider else self.provider_order(request)

        last_error = ""
        tried_failures: list[str] = []  # providers that were set up but failed, with the reason
        skipped_cloud: list[str] = []  # cloud providers that are set up but may not be used
        # The first real provider in the order is the user's choice; a cloud provider further
        # down is only a fallback, and using it would send the prompt off this machine.
        primary = next((name for name in order if name and name != "fallback"), "")
        attempts: list[dict[str, Any]] = []

        def finish(provider: str, model: str, *, success: bool, **extra: Any) -> None:
            if success:
                self._note_outcome(provider, model, True)
            self.last_stream_metadata = {
                "provider": provider,
                "model": model,
                "success": success,
                "attempts": attempts,
                "fallback_reason": "" if success else last_error,
                "skipped_cloud": list(skipped_cloud),
                **extra,
            }

        finish("", request.model, success=False)
        for provider in order:
            if not provider:
                continue
            info = self.detect_provider(provider)
            if not info.available:
                last_error = info.message
                attempts.append({"provider": provider, "success": False, "error": info.message})
                continue
            if provider in CLOUD_PROVIDERS and provider != primary and not preferred_provider and not self.cloud_fallback_allowed(request):
                skipped_cloud.append(provider)
                attempts.append({"provider": provider, "success": False, "error": CLOUD_SKIPPED})
                record_event("provider_skipped", f"{provider} not used: cloud fallback is off", provider=provider)
                continue
            if provider == "fallback":
                # Not a model. Say which provider was tried and why it failed, instead of
                # sending the reader to the Diagnostics tab to find out.
                attempts.append({"provider": provider, "success": False, "error": FALLBACK_SERVED})
                record_event("provider_fallback", "No model answered; fallback notice served", reason=last_error)
                finish(provider, "", success=False, model_note="")
                yield _fallback_text(tried_failures, skipped_cloud)
                return
            model, model_note = request.model, ""
            emitted = False
            try:
                model, model_note = self._resolve_model(request, info)
                extra: dict[str, Any] = {}
                if provider == "ollama":
                    for chunk in self._stream_ollama(request, info, model):
                        emitted = True
                        yield chunk
                    extra["throughput"] = dict(self._last_ollama_throughput or {})
                else:
                    self._last_cloud_usage = {}
                    if provider == "openai":
                        text = self._generate_openai(request, info)
                    elif provider == "anthropic":
                        text = self._generate_anthropic(request, info)
                    elif provider == "huggingface_local":
                        text = self._generate_hf_local(request, info)
                    else:
                        raise RuntimeError(f"Provider '{provider}' has no generator.")
                    model = str(self._last_cloud_usage.get("model") or model or (info.models[0] if info.models else ""))
                    if provider in CLOUD_PROVIDERS:
                        extra["usage"] = dict(self._last_cloud_usage)
                    if text:
                        # Recorded before the text is handed over: a caller that stops reading
                        # after this one chunk still finds the right metadata.
                        attempts.append({"provider": provider, "success": True})
                        finish(provider, model, success=True, model_note=model_note, **extra)
                        emitted = True
                        yield text
                        return
                if not emitted:
                    last_error = model_note or f"{provider}: empty response from model '{model or request.model or 'unknown'}'."
                    tried_failures.append(last_error)
                    record_event("model_failure", last_error, provider=provider, model=model)
                    attempts.append({"provider": provider, "success": False, "error": last_error})
                    continue
                attempt: dict[str, Any] = {"provider": provider, "success": True}
                if model_note:
                    attempt["note"] = model_note
                attempts.append(attempt)
                finish(provider, model, success=True, model_note=model_note, **extra)
                return
            except Exception as exc:
                last_error = f"{provider}: {_plain_error(exc)}"
                tried_failures.append(last_error)
                record_event("model_failure", last_error, provider=provider, model=model)
                attempts.append({"provider": provider, "success": False, "error": str(exc)})
                self._note_outcome(provider, model, False, str(exc))
                if emitted:
                    # Part of an answer is already on screen. Moving to the next provider now
                    # would glue a second answer, or the fallback notice, onto it.
                    finish(provider, model, success=False, partial=True, model_note=model_note)
                    shown = last_error if len(last_error) <= 200 else last_error[:199] + "…"
                    yield f"\n\n[The answer was cut off: {shown}]"
                    return
                continue
        record_event("provider_fallback", "No model answered; fallback notice served", reason=last_error)
        finish("fallback", "", success=False, model_note="")
        yield f"{FALLBACK_RESPONSE}\n\nProvider error: {last_error}".strip()

    def _stream_ollama(self, request: ProviderRequest, info: ProviderInfo, model: str = "") -> Generator[str, None, None]:
        self._last_ollama_throughput = {}
        model = model or self._resolve_model(request, info)[0]
        if not model:
            raise RuntimeError("Ollama is available but no usable model could be selected.")
        base_url = (request.base_url or info.base_url or str(self.config.get("ollama_url"))).rstrip("/")
        payload: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "stream": True,
            "keep_alive": str(self.config.get("ollama_keep_alive", OLLAMA_DEFAULT_KEEP_ALIVE)),
        }
        options = dict(request.options or {})
        if options.get("keep_alive"):
            payload["keep_alive"] = str(options.pop("keep_alive"))
        options.setdefault("num_predict", int(request.max_tokens or 512))
        options["num_ctx"] = max(int(options.get("num_ctx") or OLLAMA_MIN_NUM_CTX), OLLAMA_MIN_NUM_CTX)
        payload["options"] = options

        read_timeout = max(float(request.timeout or 0), OLLAMA_MIN_READ_TIMEOUT)
        if _needs_slow_startup_timeout(model):
            read_timeout = max(read_timeout, SLOW_STARTUP_OLLAMA_READ_TIMEOUT)
        for attempt in range(2):
            try:
                response = OLLAMA_SESSION.post(
                    f"{base_url}/api/generate",
                    json=payload,
                    timeout=(5.0, read_timeout),
                    stream=True,
                )
                break
            except requests.ConnectionError:
                # Ollama restarting or still starting up: one short retry. Timeouts are not
                # retried; the read timeout is already generous.
                if attempt:
                    raise
                time.sleep(float(self.config.get("ollama_connect_retry_seconds", 1.5)))
        response.raise_for_status()
        yielded_any = False
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            chunk = str(data.get("response", ""))
            if chunk:
                yielded_any = True
                yield chunk
            if data.get("done"):
                if not yielded_any:
                    raise RuntimeError(f"Ollama model '{model}' returned an empty response.")
                eval_count = int(data.get("eval_count") or 0)
                eval_duration = int(data.get("eval_duration") or 0)
                prompt_eval_count = int(data.get("prompt_eval_count") or 0)
                prompt_eval_duration = int(data.get("prompt_eval_duration") or 0)
                tokens_per_second = 0.0
                if eval_count > 0 and eval_duration > 0:
                    tokens_per_second = eval_count / (eval_duration / 1_000_000_000)
                self._last_ollama_throughput = {
                    "eval_count": eval_count,
                    "eval_duration_ns": eval_duration,
                    "prompt_eval_count": prompt_eval_count,
                    "prompt_eval_duration_ns": prompt_eval_duration,
                    "tokens_per_second": round(tokens_per_second, 2) if tokens_per_second else 0.0,
                    # "length" means the answer hit the token limit rather than finishing.
                    "done_reason": str(data.get("done_reason") or ""),
                }
                return
        if not yielded_any:
            raise RuntimeError(f"Ollama model '{model}' stream ended without text.")
        # Text arrived but the closing message never did: the connection dropped mid-answer.
        raise RuntimeError(f"Ollama model '{model}' stopped before finishing its answer.")

    def _post_with_retry(self, url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> requests.Response:
        """POST to a cloud API, retrying rate limits, overloads and dropped connections."""

        for attempt in range(CLOUD_RETRIES + 1):
            last_try = attempt == CLOUD_RETRIES
            try:
                response = self._session.post(url, headers=headers, json=payload, timeout=(8.0, timeout))
            except (requests.ConnectionError, requests.Timeout):
                if last_try:
                    raise
                time.sleep(1.0 + 2.0 * attempt)
                continue
            if response.status_code in RETRYABLE_STATUS and not last_try and response.headers.get("x-should-retry") != "false":
                try:
                    delay = float(response.headers.get("retry-after", ""))
                except ValueError:
                    delay = 1.0 + 2.0 * attempt
                time.sleep(min(max(delay, 0.5), 15.0))
                continue
            return response
        return response

    @staticmethod
    def _raise_for_api_error(provider: str, response: requests.Response) -> None:
        """Raise with the API's own error message instead of a bare status code."""

        if response.ok:
            return
        detail = ""
        try:
            error = response.json().get("error") or {}
            detail = str(error.get("message") or error) if error else ""
        except ValueError:
            detail = response.text[:200]
        raise RuntimeError(f"{provider} API returned HTTP {response.status_code}: {detail or 'no details'}")

    def _generate_openai(self, request: ProviderRequest, info: ProviderInfo) -> str:
        api_key = os.environ["OPENAI_API_KEY"]
        model = _cloud_model("openai", request.model, info)
        payload = {
            "model": model,
            "input": request.prompt,
            "instructions": request.system_prompt or None,
            "max_output_tokens": int(request.max_tokens or request.options.get("num_predict", 512)),
        }
        response = self._post_with_retry(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            payload={key: value for key, value in payload.items() if value is not None},
            timeout=float(request.timeout or 120.0),
        )
        self._raise_for_api_error("OpenAI", response)
        data = response.json()
        usage = data.get("usage") or {}
        self._last_cloud_usage = {
            "model": str(data.get("model") or model),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        }
        if data.get("output_text"):
            return str(data["output_text"])
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(str(content["text"]))
        text = "\n".join(chunks).strip()
        if not text:
            raise RuntimeError(f"OpenAI returned no text (status: {data.get('status') or 'unknown'}).")
        return text

    def _generate_anthropic(self, request: ProviderRequest, info: ProviderInfo) -> str:
        """Call the Claude Messages API.

        Written for the current models (Claude Sonnet 5.5 by default): thinking is on by default,
        sampling parameters are not sent, and a safety classifier can decline a request with
        stop_reason "refusal". Older models that reject the newer fields are retried once with
        the basic request.
        """

        api_key = os.environ["ANTHROPIC_API_KEY"]
        model = _cloud_model("anthropic", request.model, info)
        base: dict[str, Any] = {
            "model": model,
            "max_tokens": max(int(request.max_tokens or 0), ANTHROPIC_MAX_TOKENS),
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system_prompt:
            base["system"] = request.system_prompt
        headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        payload = dict(base)
        extra_headers: dict[str, str] = {}
        effort = str(self.config.get("anthropic_effort", "low") or "").strip().lower()
        if effort:
            # "low" suits chat and summaries; raise it in config for harder work.
            payload["output_config"] = {"effort": effort}
        if self.config.get("anthropic_refusal_fallback", True):
            payload["fallbacks"] = "default"
            extra_headers["anthropic-beta"] = ANTHROPIC_FALLBACK_BETA

        timeout = float(request.timeout or 120.0)
        response = self._post_with_retry("https://api.anthropic.com/v1/messages", headers={**headers, **extra_headers}, payload=payload, timeout=timeout)
        if response.status_code == 400 and payload != base:
            # A model or account that does not accept the optional fields: send the plain request.
            response = self._post_with_retry("https://api.anthropic.com/v1/messages", headers=headers, payload=base, timeout=timeout)
        self._raise_for_api_error("Anthropic", response)
        data = response.json()
        usage = data.get("usage") or {}
        used_model = str(data.get("model") or model)
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        self._last_cloud_usage = {
            "model": used_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimate_cost_usd(used_model, input_tokens, output_tokens),
        }
        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            # Check before reading content: a declined request is not an answer.
            category = (data.get("stop_details") or {}).get("category") or "unspecified"
            raise RuntimeError(f"Claude declined this request (category: {category}).")
        text = "\n".join(str(item.get("text", "")) for item in data.get("content", []) if item.get("type") == "text").strip()
        if not text:
            raise RuntimeError(f"Claude returned no text (stop_reason: {stop_reason or 'unknown'}).")
        return text

    def _generate_hf_local(self, request: ProviderRequest, info: ProviderInfo) -> str:
        if self._hf_pipeline is None:
            from transformers import pipeline

            self._hf_pipeline = pipeline("text-generation", model=info.models[0])
        result = self._hf_pipeline(
            request.prompt,
            max_new_tokens=int(request.max_tokens or request.options.get("num_predict", 256)),
            do_sample=True,
            temperature=float(request.options.get("temperature", 0.7)),
        )
        if isinstance(result, list) and result:
            text = str(result[0].get("generated_text", ""))
            return text.removeprefix(request.prompt).strip() or text.strip()
        return FALLBACK_RESPONSE
