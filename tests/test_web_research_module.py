"""The knowledge module as the rest of the app uses it."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.embeddings import choose_embedder
from tests.test_knowledge_store import ConceptEmbedder
from web_research_module import WebResearchModule


@pytest.fixture
def module(tmp_path) -> WebResearchModule:
    return WebResearchModule(str(tmp_path / "kb"), embedder=ConceptEmbedder())


def test_word_hash_backend_is_reported_for_what_it_is(tmp_path):
    hashed = WebResearchModule(str(tmp_path / "kb"), embedding_backend="hash")

    status = hashed.embedding_status()
    summary = hashed.get_processing_summary()

    assert len(hashed.generate_embedding("local private knowledge")) == 384
    assert (status["runtime_backend"], status["dimensions"], status["degraded"]) == ("hash", 384, False)
    assert "word-hash vectors" in status["message"] and "not meaning" in status["message"]
    assert summary["embedding_backend"] == "hash" and summary["total_chunks"] == 0


def test_without_an_embedding_model_the_module_says_search_is_degraded(tmp_path):
    degraded = WebResearchModule(str(tmp_path / "kb"), embedding_backend="auto")  # no model server in tests

    status = degraded.embedding_status()

    assert degraded.embedding_backend == "hash"
    assert status["degraded"] is True and status["available"] is False
    assert "ollama pull all-minilm" in status["message"]


def test_an_unknown_backend_name_is_treated_as_automatic(tmp_path):
    odd = WebResearchModule(str(tmp_path / "kb"), embedding_backend="unknown")

    assert odd.embedding_status()["configured_backend"] == "auto"
    assert odd.embedding_backend == "hash"


def test_sentence_transformers_that_is_not_installed_falls_back_with_a_reason():
    with patch("modules.embeddings.importlib.util.find_spec", return_value=None):
        _embedder, status = choose_embedder("sentence_transformers", "sentence-transformers/all-MiniLM-L6-v2")

    assert status["configured_backend"] == "sentence_transformers"
    assert (status["runtime_backend"], status["available"], status["degraded"]) == ("hash", False, True)
    assert "sentence-transformers is not installed" in status["message"] and "fall back" in status["message"]


def test_documents_are_added_searched_and_summarised(module):
    module.add_document("file:note.md", "Test Note", "Cognitive Nexus stores local knowledge for retrieval. The feline sleeps.", kind="upload")

    results = module.semantic_search("local knowledge retrieval", top_k=2)

    assert results and results[0]["title"] == "Test Note" and results[0]["kind"] == "file"
    assert {"vector_score", "lexical_score", "similarity", "url", "chunk_index", "matched"} <= set(results[0])
    assert module.semantic_search("kitten")[0]["matched"] == "meaning"
    summary = module.get_processing_summary()
    assert (summary["total_urls"], summary["total_chunks"]) == (1, 1)
    assert summary["urls"][0]["url"] == "file:note.md" and summary["urls"][0]["source_type"] == "file"


def test_passages_split_by_an_older_caller_can_still_be_stored(module):
    chunks = module.chunk_text("Cognitive Nexus stores local knowledge chunks for retrieval.")

    assert module.store_chunks_and_embeddings("note:test", chunks, title="Test Note")
    assert module.semantic_search("knowledge chunks")[0]["title"] == "Test Note"


def test_cleaning_text_keeps_symbols_and_paragraphs(module):
    raw = "Price:   $5.00 (was $7)   \r\n\r\n\r\n\r\nEmail me@example.com   or see https://example.org/a?b=1#c\n  if x < 3 and y >= 4:\n      print('ok')"

    cleaned = module._clean_text(raw)

    assert "$5.00 (was $7)" in cleaned and "me@example.com" in cleaned and "https://example.org/a?b=1#c" in cleaned
    assert "if x < 3 and y >= 4:" in cleaned and "print('ok')" in cleaned
    assert "\n\n\n" not in cleaned and "Price: $5.00" in cleaned


def test_extractive_answer_quotes_the_best_passages(module):
    module.add_document("file:ops.md", "Operations", "The nightly snapshot runs at 02:00. It is copied to the archive server.", kind="file")
    module.add_document("file:pets.md", "Pets", "The feline sleeps on the sofa.", kind="file")

    answer = module.generate_response("when does the snapshot run", module.semantic_search("when does the snapshot run"))

    assert "Operations" in answer and "02:00" in answer and "Pets" not in answer
    assert "don't have enough information" in module.generate_response("anything", [])


def test_page_fetch_keeps_headings_and_reports_failures(module):
    class Response:
        content = b"<html><head><title>Guide</title></head><body><nav>menu</nav><article><h1>Setup</h1><p>Install it.</p><h2>Check</h2><p>Run tool --check.</p></article></body></html>"

        def raise_for_status(self):
            return None

    with patch("web_research_module.safe_get", return_value=Response()):
        page = module.extract_content_from_url("https://example.org/guide")

    assert page["status"] == "success" and page["title"] == "Guide"
    assert "# Setup" in page["content"] and "## Check" in page["content"] and "tool --check" in page["content"]
    assert "menu" not in page["content"]

    with patch("web_research_module.safe_get", side_effect=RuntimeError("blocked: private address")):
        failed = module.extract_content_from_url("http://192.168.0.1/")

    assert failed["status"] == "error" and "private address" in failed["error"]
