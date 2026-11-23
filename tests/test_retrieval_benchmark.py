"""Knowledge search is held to measured scores on a fixed set of documents and questions.

The word-hash run needs no model and runs everywhere. The run against a real embedding model
needs Ollama with an embedding model installed: set CN_LIVE_OLLAMA_URL (for example
http://localhost:11434) to enable it; without that variable it is skipped, never faked.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from retrieval_benchmark import format_results, load_fixture, run_benchmark  # noqa: E402

from modules.embeddings import HashEmbedder, OllamaEmbedder, installed_ollama_embedding_models  # noqa: E402

LIVE_URL = os.environ.get("CN_LIVE_OLLAMA_URL", "").strip()


def test_fixture_is_well_formed():
    fixture = load_fixture()
    ids = [document["id"] for document in fixture["documents"]]

    assert len(ids) == len(set(ids)) >= 30
    kinds = {query["type"] for query in fixture["queries"]}
    assert kinds == {"paraphrase", "exact", "identifier", "unanswerable"}
    for query in fixture["queries"]:
        assert (query["doc"] is None) == (query["type"] == "unanswerable")
        assert query["doc"] is None or query["doc"] in ids


def test_keyword_search_finds_exact_wording_and_identifiers_without_any_model():
    results = run_benchmark(HashEmbedder())["modes"]["hybrid"]

    assert results["exact"]["hit@1"] == 1.0
    assert results["identifier"]["hit@1"] == 1.0
    # Without a model that understands meaning, paraphrased questions mostly cannot be answered.
    # This is the measured gap the embedding model closes; it is recorded, not hidden.
    assert results["paraphrase"]["hit@3"] < 0.5


def test_without_a_model_nothing_unrelated_is_put_into_a_chat_prompt():
    explicit = run_benchmark(HashEmbedder(), min_confidence="low")["modes"]["hybrid"]
    for_chat = run_benchmark(HashEmbedder(), min_confidence="medium")["modes"]["hybrid"]

    assert explicit["unanswerable"]["returned_nothing"] >= 0.6
    assert for_chat["unanswerable"]["returned_nothing"] == 1.0
    assert for_chat["exact"]["hit@1"] == 1.0 and for_chat["identifier"]["hit@1"] == 1.0


def test_results_can_be_printed():
    text = format_results(run_benchmark(HashEmbedder()))

    assert "backend: hash-384" in text and "paraphrase" in text and "returned nothing for" in text


@pytest.mark.skipif(not LIVE_URL, reason="set CN_LIVE_OLLAMA_URL to run against a real embedding model")
def test_with_a_real_embedding_model_paraphrases_are_found_and_unrelated_questions_are_not():
    installed = installed_ollama_embedding_models(LIVE_URL, timeout=10.0)
    if not installed:
        pytest.skip("Ollama is reachable but has no embedding model (ollama pull all-minilm)")
    embedder = OllamaEmbedder(installed[0], LIVE_URL)

    explicit = run_benchmark(embedder, min_confidence="low")["modes"]
    for_chat = run_benchmark(embedder, min_confidence="medium")["modes"]["hybrid"]

    hybrid = explicit["hybrid"]
    assert hybrid["all_answerable"]["hit@3"] >= 0.9
    assert hybrid["paraphrase"]["hit@3"] >= 0.85 and hybrid["paraphrase"]["hit@1"] >= 0.75
    assert hybrid["exact"]["hit@1"] == 1.0 and hybrid["identifier"]["hit@3"] == 1.0
    # Meaning search is what finds paraphrases; keywords alone cannot.
    assert hybrid["paraphrase"]["hit@3"] - explicit["keyword"]["paraphrase"]["hit@3"] >= 0.3
    assert for_chat["unanswerable"]["returned_nothing"] >= 0.9
    assert for_chat["all_answerable"]["hit@3"] >= 0.85


def test_saved_results_exist_and_name_the_model_they_were_measured_with():
    saved = json.loads((REPO_ROOT / "docs" / "benchmarks" / "retrieval_all-minilm.json").read_text(encoding="utf-8"))

    assert saved["runs"][0]["backend"].startswith("ollama:all-minilm")
    assert saved["runs"][0]["modes"]["hybrid"]["all_answerable"]["hit@3"] >= 0.9
    assert saved["measured_at"]
