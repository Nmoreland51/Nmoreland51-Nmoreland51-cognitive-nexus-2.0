"""Passages that tell the same story in other words, so that a claim retold on many sites counts once (item 030).

The claim check already counts a site once, and the same passage copied onto several sites once
(most of the words shared). A rumour rewritten in other words on each site got past both: ten
retellings counted as ten sources. Here two passages from different sites that say the same thing
about the claim are compared by meaning, with a small embedding model, and the later one is
counted as a retelling of the first when they are close enough.

"Close enough" was measured, not guessed: tests/fixtures/retelling_cases.json holds pairs labelled
before any code existed, and tools/retelling_benchmark.py chose the threshold on the dev pairs and
ran the held-out pairs once (docs/benchmarks/retellings.json). The threshold belongs to the
model it was measured with, so no other embedding model is used for this.

What it cannot do: tell an independent report from a retelling that adds an invented detail of its
own. That needs knowing where each page got its information, which the text does not show.
"""

from __future__ import annotations

import math
import os
from typing import Callable, Sequence

from modules.local_address import loopback_ipv4

Embed = Callable[[list[str]], list[list[float]]]

# The embedding model the threshold was measured with, as Ollama names it.
MEASURED_MODEL = "all-minilm"
MEASURED_TAGS = ("latest", "22m", "l6-v2")
# Two passages whose meaning is at least this close are counted as one story. Chosen on the dev
# pairs by the rule written into the fixture before measuring: there it folded 11 of 16 retold
# pairs and none of 16 independent ones (any value from 0.820 to 0.8312 gives that result).
RETELLING_SIMILARITY = 0.8312
COMPARED_STANCES = ("supports", "contradicts")


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    length = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / length if length else 0.0


def is_measured_model(name: str) -> bool:
    """True for the Ollama model name the threshold was measured with ("all-minilm", "all-minilm:latest")."""

    family, _, tag = (name or "").partition(":")
    return family == MEASURED_MODEL and (not tag or tag in MEASURED_TAGS)


def meaning_embedder(ollama_url: str | None = None) -> tuple[Embed | None, str]:
    """The embedding function to compare passages with, and the model's name; or None and the reason.

    Only the model the threshold was measured with is used. Nothing is downloaded.
    """

    from modules.embeddings import OllamaEmbedder, installed_ollama_embedding_models

    url = loopback_ipv4((ollama_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/"))
    model = next((name for name in installed_ollama_embedding_models(url) if is_measured_model(name)), "")
    if not model:
        return None, (
            f"the {MEASURED_MODEL} embedding model, which the comparison was measured with, is not installed in Ollama "
            f"(ollama pull {MEASURED_MODEL}, 45 MB)"
        )
    embedder = OllamaEmbedder(model, url, timeout=30.0)
    return embedder.embed, model


def fold_retellings(
    passages: Sequence[str],
    stances: Sequence[str],
    sites: Sequence[str],
    embed: Embed,
    threshold: float | None = None,
) -> list[tuple[int, int, float]]:
    """Which passages retell an earlier one: [(index, index of the passage it retells, similarity)].

    The passages are in the order they would be counted, best first. A passage is only compared
    with earlier ones that take the same side on the claim and come from another site, and it is
    folded into the one it is closest to. Raises what embed raises.
    """

    limit = RETELLING_SIMILARITY if threshold is None else threshold
    compared = [index for index, stance in enumerate(stances) if stance in COMPARED_STANCES]
    if len(compared) < 2 or limit <= 0:
        return []
    vectors = dict(zip(compared, embed([passages[index] for index in compared])))
    folded: list[tuple[int, int, float]] = []
    kept: list[int] = []
    for index in compared:
        candidates = [
            (cosine(vectors[index], vectors[other]), other)
            for other in kept
            if stances[other] == stances[index] and sites[other] != sites[index]
        ]
        best = max(candidates, default=None)
        if best is not None and best[0] >= limit:
            folded.append((index, best[1], round(best[0], 3)))
        else:
            kept.append(index)
    return folded
