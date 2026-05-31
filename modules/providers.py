"""Local AI provider helpers."""

from __future__ import annotations

import os
import importlib.util
import json
from dataclasses import dataclass
from typing import List, Optional

import requests


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_GENERATE_TIMEOUT = float(os.environ.get("OLLAMA_GENERATE_TIMEOUT", "600"))
FALLBACK_RESPONSE = (
    "Fallback: no working text provider returned an answer. Start Ollama with `ollama serve`, "
    "install or select a local model, or configure OpenAI/Anthropic keys. Check Diagnostics for "
    "the provider attempt log."
)
OLLAMA_SESSION = requests.Session()
DEFAULT_OLLAMA_MODEL_PREFERENCES = (
    "llama3.2:3b",
    "llama3.2",
    "llama3.1:8b",
    "llama3.1",
    "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
    "BlackHillsInfoSec/llama-3.1-8b-abliterated",
)


@dataclass
class ProviderStatus:
    """Current provider state shown in the Streamlit sidebar."""

    available: bool
    message: str
    models: List[str]
    base_url: str


def get_ollama_base_url() -> str:
    """Return the configured Ollama URL, defaulting to local Ollama."""

    return os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def get_ollama_model_preferences() -> List[str]:
    """Return preferred Ollama models, allowing local env overrides."""

    configured = os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_PREFERRED_MODEL") or ""
    preferences: List[str] = []
    if configured.strip():
        preferences.append(configured.strip())
    preferences.extend(DEFAULT_OLLAMA_MODEL_PREFERENCES)
    deduped: List[str] = []
    for model in preferences:
        if model and model not in deduped:
            deduped.append(model)
    return deduped


def rank_ollama_models(models: List[str]) -> List[str]:
    """Put the locally preferred chat model first while preserving the rest."""

    cleaned = [model for model in models if model]
    if not cleaned:
        return []

    remaining = list(cleaned)
    ranked: List[str] = []
    for preferred in get_ollama_model_preferences():
        matches = [
            model
            for model in remaining
            if model == preferred or model.split(":", 1)[0] == preferred.split(":", 1)[0]
        ]
        for model in matches:
            if model not in ranked:
                ranked.append(model)
                remaining.remove(model)

    ranked.extend(remaining)
    return ranked


def check_ollama_status(base_url: Optional[str] = None, timeout: float = 2.5) -> ProviderStatus:
    """Check Ollama by calling GET /api/tags and returning installed models."""

    resolved_url = (base_url or get_ollama_base_url()).rstrip("/")
    try:
        response = OLLAMA_SESSION.get(f"{resolved_url}/api/tags", timeout=timeout)
        response.raise_for_status()
        data = response.json()
        models = [model.get("name", "") for model in data.get("models", [])]
        models = rank_ollama_models([name for name in models if name])

        if not models:
            return ProviderStatus(
                available=True,
                message="Ollama is running, but no models are installed.",
                models=[],
                base_url=resolved_url,
            )

        return ProviderStatus(
            available=True,
            message=f"Ollama is running with {len(models)} model(s).",
            models=models,
            base_url=resolved_url,
        )
    except requests.RequestException:
        return ProviderStatus(
            available=False,
            message="Ollama is not running. Start it with: ollama serve",
            models=[],
            base_url=resolved_url,
        )
    except ValueError:
        return ProviderStatus(
            available=False,
            message="Ollama returned an invalid response.",
            models=[],
            base_url=resolved_url,
        )


def generate_with_ollama(
    prompt: str,
    model: str,
    base_url: Optional[str] = None,
    options: Optional[dict] = None,
    timeout: float = DEFAULT_OLLAMA_GENERATE_TIMEOUT,
) -> str:
    """Generate a response with Ollama's /api/generate endpoint."""

    if not model:
        return FALLBACK_RESPONSE

    resolved_url = (base_url or get_ollama_base_url()).rstrip("/")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "30m",
    }
    if options:
        payload["options"] = dict(options)

    try:
        read_timeout = max(float(timeout or 0), DEFAULT_OLLAMA_GENERATE_TIMEOUT, 300.0)
        request_timeout = (10.0, read_timeout)
        response = OLLAMA_SESSION.post(
            f"{resolved_url}/api/generate",
            json=payload,
            timeout=request_timeout,
            stream=True,
        )
        response.raise_for_status()
        chunks: list[str] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            chunks.append(str(data.get("response", "")))
            if data.get("done"):
                break
        answer = "".join(chunks).strip()
        return answer or FALLBACK_RESPONSE
    except requests.RequestException as exc:
        return f"{FALLBACK_RESPONSE}\n\nProvider error: {exc}"
    except ValueError:
        return f"{FALLBACK_RESPONSE}\n\nProvider error: Ollama returned invalid JSON."


def fallback_response() -> str:
    """Return the required fallback response."""

    return FALLBACK_RESPONSE


def optional_dependency_available(module_name: str) -> bool:
    """Check whether an optional Python package can be imported."""

    return importlib.util.find_spec(module_name) is not None


def get_provider_inventory() -> List[dict]:
    """Report detected provider-related integrations."""

    ollama = check_ollama_status(timeout=1.0)
    hf_model = os.environ.get("HF_LOCAL_MODEL", "").strip()
    hf_packages = optional_dependency_available("transformers") and optional_dependency_available("torch")
    return [
        {
            "name": "Ollama",
            "type": "local_llm",
            "available": ollama.available,
            "details": ollama.message,
        },
        {
            "name": "Hugging Face local",
            "type": "local_transformers",
            "available": bool(hf_model) and hf_packages,
            "details": (
                f"Configured model: {hf_model}"
                if hf_model and hf_packages
                else "Optional local Transformers provider; set HF_LOCAL_MODEL and install transformers/torch to enable."
            ),
        },
        {
            "name": "Anthropic",
            "type": "cloud_llm",
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "details": "Optional cloud provider; disabled unless ANTHROPIC_API_KEY is set.",
        },
        {
            "name": "OpenAI images",
            "type": "cloud_image",
            "available": bool(os.environ.get("OPENAI_API_KEY")),
            "details": "Profiles exist in cognitive_nexus/image_generation_profiles.py; disabled unless OPENAI_API_KEY is set.",
        },
    ]
