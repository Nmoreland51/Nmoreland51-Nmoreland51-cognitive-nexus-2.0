"""Embedding backends for knowledge search.

An embedding turns a piece of text into numbers so that texts with similar meaning are close
together, even when they share no words ("how do I reset my password" and "steps to recover
account access"). The app can get embeddings from three places:

    ollama                 a small embedding model served by Ollama (for example all-minilm, 45 MB)
    sentence_transformers  the optional sentence-transformers package
    hash                   word-hash vectors: no model, and no understanding of meaning

Hash vectors only match shared words. They remain as an explicit, labelled fallback for a machine
with no embedding model, so that search still works; the status says so and a degraded-mode
event is recorded. With the default setting ("auto") an installed Ollama embedding model is used
when there is one.

Vectors from different models cannot be compared, so every stored vector carries the name of the
backend that made it, and a search only uses vectors made by the backend in use.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import math
import os
import re
import time
from typing import Any, Protocol, Sequence

import requests

from modules.event_log import record_event
from modules.local_address import loopback_ipv4

logger = logging.getLogger(__name__)

HASH_DIMENSIONS = 384
DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Ollama models that are embedding models, best first for this app (small and fast on CPU first).
OLLAMA_EMBEDDING_FAMILIES = (
    "all-minilm",
    "nomic-embed-text",
    "bge-small",
    "snowflake-arctic-embed",
    "embeddinggemma",
    "granite-embedding",
    "mxbai-embed-large",
    "bge-m3",
    "bge-large",
    "paraphrase-multilingual",
)
EMBED_BATCH = 32
_STOPWORDS = frozenset(
    """a an and are as at be by can did do does for from how i in is it me of on or say says should that the this to
    was what when where which who why with about answer question""".split()
)


class EmbeddingError(RuntimeError):
    """The embedding backend could not produce vectors."""


class Embedder(Protocol):
    name: str  # stored with every vector, for example "ollama:all-minilm"
    semantic: bool

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def terms(text: str) -> list[str]:
    """Words worth matching on."""

    return [term for term in re.findall(r"[a-zA-Z0-9_@.-]{3,}", (text or "").lower()) if term not in _STOPWORDS]


def normalize(vector: Sequence[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    return [float(value) / length for value in vector] if length else [0.0 for _ in vector]


class HashEmbedder:
    """Word-hash vectors. Matches shared words only; kept as the labelled fallback."""

    name = f"hash-{HASH_DIMENSIONS}"
    semantic = False

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * HASH_DIMENSIONS
            for term in terms(text):
                vector[int(hashlib.md5(term.encode("utf-8")).hexdigest()[:8], 16) % HASH_DIMENSIONS] += 1.0
            vectors.append(normalize(vector))
        return vectors


class OllamaEmbedder:
    """Vectors from an embedding model served by Ollama (/api/embed)."""

    semantic = True

    def __init__(self, model: str, base_url: str, session: Any = None, timeout: float = 120.0) -> None:
        self.model = model
        self.base_url = loopback_ipv4(base_url.rstrip("/"))
        self.name = f"ollama:{model}"
        self._session = session or requests.Session()
        self._timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = [text if text.strip() else " " for text in texts[start : start + EMBED_BATCH]]
            payload: dict[str, Any] = {"model": self.model, "input": batch, "truncate": True, "keep_alive": "30m"}
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    response = self._session.post(f"{self.base_url}/api/embed", json=payload, timeout=(5.0, self._timeout))
                    response.raise_for_status()
                    received = response.json().get("embeddings") or []
                    if len(received) != len(batch):
                        raise EmbeddingError(f"Ollama returned {len(received)} vectors for {len(batch)} texts.")
                    vectors.extend(normalize(vector) for vector in received)
                    last_error = None
                    break
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    if attempt == 0:
                        time.sleep(0.5)
            if last_error is not None:
                raise EmbeddingError(f"Ollama embedding model '{self.model}' failed: {last_error}") from last_error
        return vectors


class SentenceTransformerEmbedder:
    """Vectors from the optional sentence-transformers package. The model loads on first use."""

    semantic = True

    def __init__(self, model: str = DEFAULT_ST_MODEL) -> None:
        self.model = model
        self.name = f"st:{model}"
        self._loaded: Any = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            if self._loaded is None:
                from sentence_transformers import SentenceTransformer

                self._loaded = SentenceTransformer(self.model)
            encoded = self._loaded.encode(list(texts), normalize_embeddings=True)
            return [[float(value) for value in vector] for vector in encoded]
        except Exception as exc:
            raise EmbeddingError(f"sentence-transformers model '{self.model}' failed: {exc}") from exc


def installed_ollama_embedding_models(base_url: str, session: Any = None, timeout: float = 2.0) -> list[str]:
    """Embedding models Ollama has, in order of preference. Empty when Ollama is not reachable."""

    try:
        if session is None:
            # The same short-lived model list as the chat side (modules/providers.ollama_tags).
            from modules.providers import ollama_tags

            listed = ollama_tags(base_url, timeout=timeout)
        else:
            response = session.get(f"{loopback_ipv4(base_url.rstrip('/'))}/api/tags", timeout=timeout)
            response.raise_for_status()
            listed = response.json()
        names = [str(item.get("name") or "") for item in listed.get("models") or []]
    except Exception:
        return []
    found: list[str] = []
    for family in OLLAMA_EMBEDDING_FAMILIES:
        found.extend(name for name in names if name.split(":")[0].split("/")[-1].startswith(family) and name not in found)
    return found


def normalize_backend(value: str | None) -> str:
    cleaned = (value or "auto").strip().lower().replace("-", "_")
    if cleaned in {"hash", "hash_vector", "local_hash"}:
        return "hash"
    if cleaned in {"sentence_transformers", "sentence_transformer", "minilm", "all_minilm_l6_v2", "st"}:
        return "sentence_transformers"
    if cleaned in {"ollama", "auto"}:
        return cleaned
    return "auto"


def choose_embedder(
    backend: str | None = None,
    model: str | None = None,
    *,
    ollama_url: str | None = None,
    session: Any = None,
) -> tuple[Embedder, dict[str, Any]]:
    """Pick the embedding backend and say why. Returns (embedder, status).

    status: configured_backend, runtime_backend, model, semantic, degraded, message.
    """

    configured = normalize_backend(backend if backend is not None else os.environ.get("KNOWLEDGE_EMBEDDING_BACKEND"))
    wanted_model = (model if model is not None else os.environ.get("KNOWLEDGE_EMBEDDING_MODEL") or "").strip()
    url = loopback_ipv4((ollama_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/"))

    def status(embedder: Embedder, runtime: str, model_name: str, message: str, degraded: bool) -> tuple[Embedder, dict[str, Any]]:
        return embedder, {
            "configured_backend": configured,
            "runtime_backend": runtime,
            "model": model_name,
            "name": embedder.name,
            "semantic": embedder.semantic,
            "degraded": degraded,
            "available": not degraded,
            "message": message,
        }

    if configured == "hash":
        return status(HashEmbedder(), "hash", "local_token_hash", "Using word-hash vectors (chosen in settings): search matches shared words, not meaning.", False)

    problems: list[str] = []
    if configured in {"ollama", "auto"}:
        installed = installed_ollama_embedding_models(url, session=session)
        ollama_model = wanted_model if configured == "ollama" and wanted_model and not wanted_model.startswith("sentence-transformers/") else ""
        if ollama_model and not any(name == ollama_model or name.split(":")[0] == ollama_model for name in installed):
            problems.append(f"Ollama embedding model '{ollama_model}' is not installed (ollama pull {ollama_model})")
            ollama_model = ""
        chosen = ollama_model or (installed[0] if installed else "")
        if chosen:
            return status(
                OllamaEmbedder(chosen, url, session=session),
                "ollama",
                chosen,
                f"Using Ollama embedding model {chosen}: search understands meaning as well as words.",
                False,
            )
        if not problems:
            problems.append("no embedding model is installed in Ollama (ollama pull all-minilm, 45 MB)")

    if configured in {"sentence_transformers", "auto"}:
        if importlib.util.find_spec("sentence_transformers") is not None:
            st_model = wanted_model if wanted_model.startswith("sentence-transformers/") or configured == "sentence_transformers" and wanted_model else DEFAULT_ST_MODEL
            if configured == "sentence_transformers":
                return status(
                    SentenceTransformerEmbedder(st_model),
                    "sentence_transformers",
                    st_model,
                    f"Using sentence-transformers model {st_model}; it loads on first use.",
                    False,
                )
        else:
            problems.append("sentence-transformers is not installed")

    reason = "; ".join(problems) or "no embedding backend is available"
    return status(
        HashEmbedder(),
        "hash",
        "local_token_hash",
        f"Degraded: using word-hash vectors because {reason}. Search will fall back to matching shared words, not meaning.",
        True,
    )


def report_degraded(status: dict[str, Any]) -> None:
    """Record once per start that knowledge search is running without a semantic model."""

    if status.get("degraded"):
        record_event("degraded_mode", "Knowledge search has no semantic embedding model", detail=status.get("message", ""))
