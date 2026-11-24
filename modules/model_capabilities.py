"""What a model can do, as data: context length, streaming, tool calls, structured output, vision.

The app used to know one thing about a model: its name. Whether it could take a picture, return a
tool call or be held to a JSON Schema was either assumed or not used at all. This module answers
those questions per model, and says where each answer comes from:

* A local model: the Ollama server is asked (`/api/show`). It reports the model's context length
  and a list of capabilities ("completion", "tools", "vision", "embedding").
* A cloud model: the provider's published figures for the models this app knows by name. They are
  not checked against the live service here (that needs a key), and the entry says so.
* Anything else: unknown, which is treated as "no" wherever a feature is needed.

`None` means "not known", never "no". Code that needs a feature calls `supports()`, which is true
only for a known yes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests

FEATURES = ("streaming", "tools", "structured_output", "vision", "embeddings")
FEATURE_MEANING = {
    "streaming": "The answer arrives piece by piece while it is written.",
    "tools": "The model can be given tool definitions and returns calls to them in a set form.",
    "structured_output": "The reply can be held to a JSON Schema by the model server, so it always parses.",
    "vision": "The model accepts pictures as input.",
    "embeddings": "The model turns text into search vectors instead of writing answers.",
}
_CACHE_SECONDS = 300.0


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    context_window: int | None = None  # tokens the model itself can attend to; the app may use less
    max_output: int | None = None  # tokens in one reply, where the provider sets a limit of its own
    streaming: bool | None = None
    tools: bool | None = None
    structured_output: bool | None = None
    vision: bool | None = None
    embeddings: bool | None = None
    chat: bool | None = None  # can write answers at all (an embedding model cannot)
    source: str = "unknown"
    notes: tuple[str, ...] = ()

    def supports(self, feature: str) -> bool:
        """True only when the feature is known to be there."""

        if feature not in FEATURES and feature != "chat":
            raise ValueError(f"{feature!r} is not a feature. Known: {', '.join(FEATURES)}, chat.")
        return getattr(self, feature) is True

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "notes": list(self.notes)}


def unknown(provider: str, model: str, why: str) -> ModelCapabilities:
    return ModelCapabilities(provider=provider, model=model, source="unknown", notes=(why,))


# ---- local models: ask the server ---------------------------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, ModelCapabilities]] = {}
_lock = threading.Lock()


def from_ollama_show(model: str, shown: dict[str, Any]) -> ModelCapabilities:
    """Read the answer of Ollama's /api/show."""

    info = shown.get("model_info") or {}
    architecture = str(info.get("general.architecture") or "")
    window = info.get(f"{architecture}.context_length")
    if window is None:
        window = next((value for key, value in info.items() if key.endswith(".context_length")), None)
    listed = shown.get("capabilities")
    notes: list[str] = []
    if not isinstance(listed, list):
        # Ollama before 0.6 did not report capabilities.
        notes.append("This Ollama version does not say what the model can do; tool calls and vision are not known.")
        families = (shown.get("details") or {}).get("families") or []
        embeds = any(str(family).lower() in {"bert", "nomic-bert"} for family in families)
        return ModelCapabilities(
            provider="ollama",
            model=model,
            context_window=int(window) if window else None,
            streaming=True,
            structured_output=None,
            embeddings=embeds or None,
            chat=None if not embeds else False,
            source="reported by the Ollama server",
            notes=tuple(notes),
        )
    names = {str(item).lower() for item in listed}
    writes = "completion" in names
    if writes and "tools" not in names:
        notes.append("No tool calls of its own: the app asks for a JSON reply held to a schema instead.")
    return ModelCapabilities(
        provider="ollama",
        model=model,
        context_window=int(window) if window else None,
        streaming=writes,
        tools="tools" in names,
        # The server holds any writing model's output to a schema; it is not a property of the model.
        structured_output=writes,
        vision="vision" in names,
        embeddings="embedding" in names,
        chat=writes,
        source="reported by the Ollama server",
        notes=tuple(notes),
    )


def for_ollama(model: str, base_url: str, *, session: Any = None, timeout: float = 4.0) -> ModelCapabilities:
    """Ask the Ollama server about one model. Cached for a few minutes; never raises."""

    key = (base_url.rstrip("/"), model)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]
    try:
        answer = (session or requests).post(f"{key[0]}/api/show", json={"model": model}, timeout=timeout)
        if answer.status_code == 404:
            return unknown("ollama", model, "The Ollama server does not have this model.")
        answer.raise_for_status()
        found = from_ollama_show(model, answer.json())
    except (requests.RequestException, ValueError) as exc:
        return unknown("ollama", model, f"The Ollama server could not be asked ({type(exc).__name__}).")
    with _lock:
        _cache[key] = (now, found)
    return found


def forget_cached() -> None:
    with _lock:
        _cache.clear()


# ---- cloud models: the provider's published figures ---------------------------------------------------------

_PUBLISHED = "the provider's published figures, not checked against the live service"

# (prefix of the model name, context window, max output, vision). Longest prefix wins.
_ANTHROPIC = (
    ("claude-haiku-4-5", 200_000, 64_000, True),
    ("claude-haiku-5", 1_000_000, 128_000, True),
    ("claude-sonnet-4-6", 1_000_000, 128_000, True),
    ("claude-sonnet-5", 1_000_000, 128_000, True),
    ("claude-opus-4-6", 1_000_000, 128_000, True),
    ("claude-opus-4-7", 1_000_000, 128_000, True),
    ("claude-opus-4-8", 1_000_000, 128_000, True),
    ("claude-opus-5", 1_000_000, 128_000, True),
    ("claude-fable-5", 1_000_000, 128_000, True),
)
_OPENAI = (
    ("gpt-4.1", 1_047_576, 32_768, True),
)


def _published(provider: str, model: str, table: tuple[tuple[str, int, int, bool], ...]) -> ModelCapabilities | None:
    matches = [row for row in table if model.startswith(row[0])]
    if not matches:
        return None
    _prefix, window, output, vision = max(matches, key=lambda row: len(row[0]))
    return ModelCapabilities(
        provider=provider,
        model=model,
        context_window=window,
        max_output=output,
        streaming=True,
        tools=True,
        structured_output=True,
        vision=vision,
        embeddings=False,
        chat=True,
        source=_PUBLISHED,
        notes=("This app sends plain prompts to cloud models: it does not use their tool calls or picture input yet.",),
    )


def for_cloud(provider: str, model: str) -> ModelCapabilities:
    table = {"anthropic": _ANTHROPIC, "openai": _OPENAI}.get(provider)
    found = _published(provider, model, table) if table else None
    return found or unknown(provider, model, "This app has no figures for this model.")


# ---- one question for any provider -----------------------------------------------------------------------------


def capabilities(provider: str, model: str, *, ollama_url: str = "", session: Any = None) -> ModelCapabilities:
    """What `model` at `provider` can do, with where the answer comes from."""

    provider = str(provider or "").lower()
    if not model:
        return unknown(provider, model, "No model is selected.")
    if provider == "ollama":
        return for_ollama(model, ollama_url or "http://localhost:11434", session=session)
    if provider in {"anthropic", "openai"}:
        return for_cloud(provider, model)
    if provider == "hf_local":
        return ModelCapabilities(provider=provider, model=model, streaming=False, tools=False, structured_output=False, vision=False, embeddings=False, chat=True, source="how this app runs local Transformers models")
    return unknown(provider, model, "Unknown provider.")


def rows(found: ModelCapabilities) -> list[dict[str, str]]:
    """The capabilities as a table for a person."""

    def said(value: bool | None) -> str:
        return "not known" if value is None else ("yes" if value else "no")

    table = [
        {"What": "Context length", "Value": f"{found.context_window:,} tokens" if found.context_window else "not known", "Meaning": "How much text the model itself can take in at once. The app may use less, to fit this machine's memory."},
        {"What": "Longest reply", "Value": f"{found.max_output:,} tokens" if found.max_output else "limited by the context length", "Meaning": "The provider's own limit on one reply."},
    ]
    table += [{"What": feature.replace("_", " ").capitalize(), "Value": said(getattr(found, feature)), "Meaning": FEATURE_MEANING[feature]} for feature in FEATURES]
    return table


__all__ = ["FEATURES", "ModelCapabilities", "capabilities", "for_cloud", "for_ollama", "forget_cached", "from_ollama_show", "rows", "unknown"]
