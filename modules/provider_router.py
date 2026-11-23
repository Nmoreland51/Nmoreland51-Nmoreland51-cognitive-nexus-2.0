"""Central provider fallback and streaming router."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Generator, Optional

import requests

from modules.nexus_config import load_runtime_config
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


def _fallback_text(failures: list[str]) -> str:
    """The fallback reply, naming the providers that were tried and why each failed."""

    if not failures:
        return FALLBACK_RESPONSE
    shown = "; ".join(failure if len(failure) <= 200 else failure[:199] + "…" for failure in failures[:3])
    return f"{FALLBACK_RESPONSE}\n\nWhat failed: {shown}"


class ProviderRouter:
    """Detect and call configured providers with graceful fallback."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or load_runtime_config()
        self._status_cache: dict[str, tuple[float, ProviderInfo]] = {}
        self._hf_pipeline = None
        self._session = requests.Session()
        self.last_stream_metadata: dict[str, Any] = {}
        self._last_ollama_throughput: dict[str, Any] = {}

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
            models=[str(self.config.get("anthropic_model", "claude-sonnet-4-20250514"))],
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
        if requested:
            return requested, ""
        if info.models:
            return info.models[0], ""
        return "", ""

    def generate(self, request: ProviderRequest) -> ProviderResult:
        """Generate text using the first working provider in the configured order."""

        started = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        for provider in self.provider_order(request):
            info = self.detect_provider(provider)
            if not info.available:
                attempts.append({"provider": provider, "success": False, "error": info.message})
                continue
            try:
                text = "".join(self.stream(request, preferred_provider=provider))
                stream_meta = dict(self.last_stream_metadata or {})
                elapsed = time.perf_counter() - started
                stream_success = bool(stream_meta.get("success", bool(text.strip())))
                if text.strip() and stream_success:
                    return ProviderResult(
                        text=text.strip(),
                        provider=str(stream_meta.get("provider") or provider),
                        model=str(stream_meta.get("model") or request.model or (info.models[0] if info.models else "")),
                        success=True,
                        elapsed=elapsed,
                        attempts=stream_meta.get("attempts", attempts),
                    )
                if text.strip() and not stream_success:
                    attempts.extend(stream_meta.get("attempts", []))
                    return ProviderResult(
                        text=text.strip(),
                        provider=str(stream_meta.get("provider") or provider),
                        model=str(stream_meta.get("model") or request.model or (info.models[0] if info.models else "")),
                        success=False,
                        error=str(stream_meta.get("fallback_reason") or "No provider returned a usable response."),
                        elapsed=elapsed,
                        attempts=attempts,
                    )
                attempts.append({"provider": provider, "success": False, "error": "Empty response."})
            except Exception as exc:
                attempts.append({"provider": provider, "success": False, "error": str(exc)})

        return ProviderResult(
            text=FALLBACK_RESPONSE,
            provider="fallback",
            success=False,
            error="No provider returned a usable response.",
            elapsed=time.perf_counter() - started,
            attempts=attempts,
        )

    def stream(
        self,
        request: ProviderRequest,
        preferred_provider: str | None = None,
    ) -> Generator[str, None, None]:
        """Stream chunks from the first working provider."""

        order = [preferred_provider] if preferred_provider else self.provider_order(request)
        if not preferred_provider:
            order = self.provider_order(request)

        last_error = ""
        tried_failures: list[str] = []  # providers that were set up but failed, with the reason
        attempts: list[dict[str, Any]] = []
        self.last_stream_metadata = {
            "provider": "",
            "model": request.model,
            "success": False,
            "attempts": attempts,
            "fallback_reason": "",
        }
        for provider in order:
            if not provider:
                continue
            info = self.detect_provider(provider)
            if not info.available:
                last_error = info.message
                attempts.append({"provider": provider, "success": False, "error": info.message})
                continue
            try:
                model, model_note = self._resolve_model(request, info)
                if provider == "ollama":
                    yielded_any = False
                    for chunk in self._stream_ollama(request, info, model):
                        yielded_any = True
                        yield chunk
                    if not yielded_any:
                        last_error = model_note or f"{provider}: empty response from model '{model or request.model or 'unknown'}'."
                        tried_failures.append(last_error)
                        attempts.append({"provider": provider, "success": False, "error": last_error})
                        continue
                    attempt = {"provider": provider, "success": True}
                    if model_note:
                        attempt["note"] = model_note
                    attempts.append(attempt)
                    self.last_stream_metadata = {
                        "provider": provider,
                        "model": model,
                        "success": True,
                        "attempts": attempts,
                        "fallback_reason": "",
                        "model_note": model_note,
                        "throughput": dict(self._last_ollama_throughput or {}),
                    }
                    return
                if provider == "openai":
                    yield self._generate_openai(request, info)
                    attempts.append({"provider": provider, "success": True})
                    self.last_stream_metadata = {
                        "provider": provider,
                        "model": model or info.models[0],
                        "success": True,
                        "attempts": attempts,
                        "fallback_reason": "",
                        "model_note": model_note,
                    }
                    return
                if provider == "anthropic":
                    yield self._generate_anthropic(request, info)
                    attempts.append({"provider": provider, "success": True})
                    self.last_stream_metadata = {
                        "provider": provider,
                        "model": model or info.models[0],
                        "success": True,
                        "attempts": attempts,
                        "fallback_reason": "",
                        "model_note": model_note,
                    }
                    return
                if provider == "huggingface_local":
                    yield self._generate_hf_local(request, info)
                    attempts.append({"provider": provider, "success": True})
                    self.last_stream_metadata = {
                        "provider": provider,
                        "model": model or info.models[0],
                        "success": True,
                        "attempts": attempts,
                        "fallback_reason": "",
                        "model_note": model_note,
                    }
                    return
                if provider == "fallback":
                    # Say which provider was tried and why it failed, instead of sending the
                    # reader to the Diagnostics tab to find out.
                    yield _fallback_text(tried_failures)
                    attempts.append({"provider": provider, "success": True})
                    self.last_stream_metadata = {
                        "provider": provider,
                        "model": "",
                        "success": True,
                        "attempts": attempts,
                        "fallback_reason": last_error,
                        "model_note": model_note,
                    }
                    return
            except Exception as exc:
                last_error = f"{provider}: {exc}"
                tried_failures.append(last_error)
                attempts.append({"provider": provider, "success": False, "error": str(exc)})
                continue
        self.last_stream_metadata = {
            "provider": "fallback",
            "model": "",
            "success": False,
            "attempts": attempts,
            "fallback_reason": last_error,
            "model_note": "",
        }
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
        response = OLLAMA_SESSION.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=(5.0, read_timeout),
            stream=True,
        )
        response.raise_for_status()
        yielded_any = False
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
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
                }
                return
        if not yielded_any:
            raise RuntimeError(f"Ollama model '{model}' stream ended without text.")

    def _generate_openai(self, request: ProviderRequest, info: ProviderInfo) -> str:
        api_key = os.environ["OPENAI_API_KEY"]
        model = request.model if request.model and request.model.startswith(("gpt", "o")) else info.models[0]
        payload = {
            "model": model,
            "input": request.prompt,
            "instructions": request.system_prompt or None,
            "max_output_tokens": int(request.max_tokens or request.options.get("num_predict", 512)),
        }
        response = self._session.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={key: value for key, value in payload.items() if value is not None},
            timeout=(8.0, float(request.timeout or 120.0)),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("output_text"):
            return str(data["output_text"])
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(str(content["text"]))
        return "\n".join(chunks).strip() or FALLBACK_RESPONSE

    def _generate_anthropic(self, request: ProviderRequest, info: ProviderInfo) -> str:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        model = request.model if request.model.startswith("claude") else info.models[0]
        payload = {
            "model": model,
            "max_tokens": int(request.max_tokens or request.options.get("num_predict", 512)),
            "system": request.system_prompt or None,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        response = self._session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={key: value for key, value in payload.items() if value is not None},
            timeout=(8.0, float(request.timeout or 120.0)),
        )
        response.raise_for_status()
        data = response.json()
        chunks = [item.get("text", "") for item in data.get("content", []) if item.get("type") == "text"]
        return "\n".join(chunks).strip() or FALLBACK_RESPONSE

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
