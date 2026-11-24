"""Local AI provider helpers."""

from __future__ import annotations

import os
import importlib.util
import json
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from modules import accounts
from modules.local_address import loopback_ipv4


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_GENERATE_TIMEOUT = float(os.environ.get("OLLAMA_GENERATE_TIMEOUT", "600"))
FALLBACK_RESPONSE = (
    "Fallback: no working text provider returned an answer. Start Ollama with `ollama serve`, "
    "install or select a local model, or configure OpenAI/Anthropic keys. Check Diagnostics for "
    "the provider attempt log."
)
OLLAMA_SESSION = requests.Session()
DEFAULT_OLLAMA_MODEL_PREFERENCES = (
    "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
    "BlackHillsInfoSec/llama-3.1-8b-abliterated",
    "llama3.2:3b",
    "llama3.2",
    "llama3.1:8b",
    "llama3.1",
)


@dataclass
class ProviderStatus:
    """Current provider state shown in the Streamlit sidebar.

    `models` holds only models that can write. A model that only turns text into vectors (used
    for searching saved knowledge) is listed in `embedding_models`, so it is never offered or
    picked as a chat model.
    """

    available: bool
    message: str
    models: List[str]
    base_url: str
    embedding_models: List[str] = field(default_factory=list)


# How Ollama describes models that produce vectors, not text.
EMBEDDING_FAMILIES = frozenset({"bert", "nomic-bert", "xlm-roberta", "roberta", "mpnet"})
# For an Ollama too old to say what family a model is.
EMBEDDING_NAME_HINTS = ("embed", "minilm", "bge-", "bge:", "-e5", "e5-", "gte-", "paraphrase-")


def is_embedding_model(entry: dict) -> bool:
    """True for an entry of Ollama's model list that cannot be used for chat."""

    details = entry.get("details") or {}
    families = {str(details.get("family") or "").lower(), *(str(item).lower() for item in details.get("families") or [])}
    families.discard("")
    if families:
        return bool(families & EMBEDDING_FAMILIES)
    name = str(entry.get("name") or "").lower()
    return any(hint in name for hint in EMBEDDING_NAME_HINTS)


def get_ollama_base_url() -> str:
    """Return the configured Ollama URL, defaulting to local Ollama."""

    return loopback_ipv4(os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"))


# The model list is asked for from several places while one page is drawn (7 times on a first
# visit, measured with tools/app_profile.py); within a few seconds the answer is the same.
TAGS_CACHE_SECONDS = 5.0
_tags_cache: dict[str, tuple[float, dict]] = {}
_tags_guard = threading.Lock()


def ollama_tags(base_url: Optional[str] = None, timeout: float = 2.5) -> dict:
    """Ollama's list of installed models (GET /api/tags), asked at most once in TAGS_CACHE_SECONDS per server.

    Raises what the request raises; a failure is not remembered, so the next call asks again.
    """

    url = loopback_ipv4((base_url or get_ollama_base_url()).rstrip("/"))
    with _tags_guard:
        cached = _tags_cache.get(url)
        if cached is not None and time.monotonic() - cached[0] < TAGS_CACHE_SECONDS:
            return cached[1]
    response = OLLAMA_SESSION.get(f"{url}/api/tags", timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Ollama's model list is not a JSON object")
    with _tags_guard:
        _tags_cache[url] = (time.monotonic(), data)
    return data


def forget_ollama_tags() -> None:
    """Ask Ollama again next time (after a model was installed or removed, and between tests)."""

    with _tags_guard:
        _tags_cache.clear()


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

    resolved_url = loopback_ipv4((base_url or get_ollama_base_url()).rstrip("/"))
    try:
        data = ollama_tags(resolved_url, timeout=timeout)
        entries = [entry for entry in data.get("models", []) if entry.get("name")]
        embedding = [str(entry["name"]) for entry in entries if is_embedding_model(entry)]
        models = rank_ollama_models([str(entry["name"]) for entry in entries if not is_embedding_model(entry)])

        if not models:
            only = f" Only embedding models are installed ({', '.join(embedding)}); they cannot chat." if embedding else ""
            return ProviderStatus(
                available=True,
                message=f"Ollama is running, but no chat model is installed.{only}",
                models=[],
                base_url=resolved_url,
                embedding_models=embedding,
            )

        return ProviderStatus(
            available=True,
            message=f"Ollama is running with {len(models)} chat model(s)." + (f" Also installed for search: {', '.join(embedding)}." if embedding else ""),
            models=models,
            base_url=resolved_url,
            embedding_models=embedding,
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

    resolved_url = loopback_ipv4((base_url or get_ollama_base_url()).rstrip("/"))
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "24h",
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
            "available": accounts.available("anthropic", "chat")[0],
            "details": "Optional cloud provider. " + accounts.available("anthropic", "chat")[1],
        },
        {
            "name": "OpenAI images",
            "type": "cloud_image",
            "available": accounts.available("openai", "chat")[0],
            "details": "Profiles exist in cognitive_nexus/image_generation_profiles.py. " + accounts.available("openai", "chat")[1],
        },
    ]
