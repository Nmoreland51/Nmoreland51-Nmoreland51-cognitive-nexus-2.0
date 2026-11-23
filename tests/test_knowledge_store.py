"""The knowledge store: hybrid search, filters, change of embedding model, migration from the
old JSON index, and several programs writing at once."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from modules import event_log
from modules.chunking import chunk_code, chunk_text
from modules.embeddings import EmbeddingError, HashEmbedder, OllamaEmbedder, choose_embedder, installed_ollama_embedding_models, normalize
from modules.knowledge_store import SCHEMA_VERSION, KnowledgeStore, document_id

REPO_ROOT = str(Path(__file__).resolve().parents[1])

CONCEPTS = {
    "password": 0, "credentials": 0, "login": 0, "account": 0, "access": 0,
    "reset": 1, "recover": 1, "regain": 1, "forgot": 1, "locked": 1,
    "backup": 2, "snapshot": 2, "archive": 2,
    "cat": 3, "feline": 3, "kitten": 3,
    "invoice": 4, "bill": 4, "payment": 4, "charge": 4,
    "weather": 5, "rain": 5, "forecast": 5,
    "deploy": 6, "release": 6, "ship": 6, "rollout": 6,
    "error": 7, "crash": 7, "failure": 7, "exception": 7,
}  # fmt: skip


class ConceptEmbedder:
    """Stand-in for a semantic model: words that mean the same land on the same dimension."""

    semantic = True

    def __init__(self, name: str = "test:concepts", fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0
        self.texts_embedded = 0

    def embed(self, texts):
        if self.fail:
            raise EmbeddingError("the embedding model is not running")
        self.calls += 1
        self.texts_embedded += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * 8
            for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split():
                if word in CONCEPTS:
                    vector[CONCEPTS[word]] += 1.0
            vectors.append(normalize(vector))
        return vectors


@pytest.fixture
def store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "kb", embedder=ConceptEmbedder())


def fill(store: KnowledgeStore) -> None:
    store.add_document("file:accounts.md", "Account help", "If you are locked out, use the recover link to regain access to your credentials.", kind="file")
    store.add_document("file:pets.md", "Pets", "Our feline sleeps on the sofa most of the day.", kind="knowledge_note")
    store.add_document("https://example.org/billing", "Billing page", "Each invoice lists the charge and the payment date.", kind="url")
    store.add_document("file:ops.md", "Operations", "Run the nightly snapshot before every rollout. Error code 3154 means the archive is damaged.", kind="file")


# --- search -------------------------------------------------------------------------------------------


def test_a_paraphrase_is_found_by_meaning_without_sharing_a_word(store):
    fill(store)

    results = store.search("how do I reset my password", top_k=3)

    assert results and results[0]["title"] == "Account help"
    assert results[0]["matched"] == "meaning"  # no word of the question is in the passage
    assert results[0]["vector_score"] > 0.5 and results[0]["lexical_score"] == 0.0
    assert store.search("how do I reset my password", top_k=3, mode="keyword") == []


def test_an_exact_term_is_found_by_keyword_even_when_the_model_sees_nothing_in_it(store):
    fill(store)

    results = store.search("what is 3154", top_k=3)

    assert results[0]["title"] == "Operations"
    assert results[0]["matched"] == "keyword" and results[0]["lexical_score"] == 1.0


def test_passages_matching_both_ways_rank_first(store):
    fill(store)
    store.add_document("file:other.md", "Other", "The word snapshot appears here among unrelated cooking notes.", kind="file")

    results = store.search("snapshot before rollout", top_k=3)

    assert results[0]["title"] == "Operations" and results[0]["matched"] == "both"
    assert results[0]["similarity"] > results[1]["similarity"]


def test_an_unrelated_question_returns_nothing_instead_of_the_nearest_passage(store):
    fill(store)

    assert store.search("quantum chromodynamics lattice", top_k=3) == []
    assert store.search("", top_k=3) == []


def test_filters_by_kind_source_and_date(store):
    fill(store)

    assert [item["kind"] for item in store.search("invoice payment", kinds=["url"])] == ["url"]
    assert store.search("invoice payment", kinds=["file"]) == []
    assert [item["url"] for item in store.search("feline", source_contains="pets")] == ["file:pets.md"]
    assert store.search("feline", source_contains="billing") == []
    assert store.search("feline", since="2999-01-01") == []
    assert store.search("feline", since="2000-01-01")


def test_your_own_files_outrank_a_saved_web_page_with_the_same_text(store):
    text = "The rollout checklist says to deploy on Tuesday."
    store.add_document("https://example.org/page", "Web copy", text, kind="url")
    store.add_document("file:mine.md", "My copy", text, kind="file")

    results = store.search("rollout checklist deploy", top_k=2)

    assert [item["kind"] for item in results] == ["file", "url"]


def test_one_long_document_does_not_crowd_out_the_others(store):
    long_text = "\n\n".join(f"Paragraph {index}: the invoice for this payment shows the charge. " * 12 for index in range(8))
    store.add_document("file:long.md", "Long billing manual", long_text, kind="file")
    store.add_document("file:short.md", "Short billing note", "An invoice is a bill for a payment.", kind="file")

    results = store.search("invoice payment charge", top_k=3)

    titles = [item["title"] for item in results]
    assert titles.count("Long billing manual") == 2 and "Short billing note" in titles


def test_word_hash_vectors_never_qualify_a_passage_on_their_own(tmp_path):
    hashed = KnowledgeStore(tmp_path / "kb", embedder=HashEmbedder())
    fill(hashed)

    assert hashed.search("how do I reset my password") == []  # no shared word, and no understanding
    assert hashed.search("feline sofa")[0]["title"] == "Pets"


# --- writing ------------------------------------------------------------------------------------------


def test_adding_the_same_document_again_does_no_work(tmp_path):
    embedder = ConceptEmbedder()
    store = KnowledgeStore(tmp_path / "kb", embedder=embedder)
    first = store.add_document("file:a.md", "A", "The feline sleeps. " * 30, kind="file")
    embedded_once = embedder.texts_embedded

    again = store.add_document("file:a.md", "A", "The feline sleeps. " * 30, kind="file")

    assert first["unchanged"] is False and again["unchanged"] is True
    assert embedder.texts_embedded == embedded_once
    assert store.stats()["documents"] == 1


def test_changed_content_replaces_the_old_passages(store):
    store.add_document("file:a.md", "A", "The feline sleeps on the sofa.", kind="file")
    store.add_document("file:a.md", "A", "The invoice was sent on Monday.", kind="file")

    assert store.search("feline sofa") == []
    assert store.search("invoice Monday")[0]["title"] == "A"
    assert store.stats()["chunks"] == 1 and store.stats()["documents"] == 1


def test_re_adding_text_reuses_saved_vectors(tmp_path):
    embedder = ConceptEmbedder()
    store = KnowledgeStore(tmp_path / "kb", embedder=embedder)
    store.add_document("file:a.md", "A", "The feline sleeps on the sofa.", kind="file")
    store.delete_document("file:a.md")
    before = embedder.texts_embedded

    store.add_document("file:a.md", "A", "The feline sleeps on the sofa.", kind="file")

    assert embedder.texts_embedded == before  # taken from the embedding cache
    assert store.search("kitten")


def test_delete_removes_a_document_from_every_index(store):
    fill(store)

    assert store.delete_document("file:pets.md") is True
    assert store.delete_document("file:pets.md") is False

    assert store.search("feline") == [] and store.search("kitten") == []
    assert store.stats()["documents"] == 3
    assert "file:pets.md" not in [item["source"] for item in store.list_documents()]


def test_empty_content_is_refused(store):
    result = store.add_document("file:empty.md", "Empty", "   \n  ", kind="file")

    assert result["status"] == "error" and store.stats()["documents"] == 0


def test_documents_are_listed_with_their_details(store):
    fill(store)

    rows = store.list_documents(kind="file")

    assert {row["title"] for row in rows} == {"Account help", "Operations"}
    assert all(row["chunks"] >= 1 and row["words"] > 0 and row["added_at"] for row in rows)
    stats = store.stats()
    assert stats["by_kind"] == {"file": 2, "knowledge_note": 1, "url": 1}
    assert stats["waiting_for_vectors"] == 0 and stats["schema_version"] == SCHEMA_VERSION


# --- when the embedding model is missing or changes -----------------------------------------------------


def test_a_document_saved_while_the_model_is_down_is_still_found_by_keyword(tmp_path):
    broken = ConceptEmbedder(fail=True)
    store = KnowledgeStore(tmp_path / "kb", embedder=broken)

    result = store.add_document("file:a.md", "A", "The feline sleeps on the sofa.", kind="file")

    assert result["status"] == "success" and result["embedded"] == 0 and "without vectors" in result["warning"]
    assert store.search("feline sofa")[0]["matched"] == "keyword"
    assert store.stats()["waiting_for_vectors"] == 1
    assert event_log.event_counts()["degraded_mode"] >= 1

    broken.fail = False
    outcome = store.reembed()

    assert outcome == {"embedded": 1, "waiting": 0, "error": ""}
    assert store.search("kitten")[0]["matched"] == "meaning"


def test_changing_the_embedding_model_keeps_search_working_and_reembeds(tmp_path):
    folder = tmp_path / "kb"
    first = KnowledgeStore(folder, embedder=HashEmbedder())
    fill(first)
    first.close()

    second = KnowledgeStore(folder, embedder=ConceptEmbedder())

    assert second.stats()["waiting_for_vectors"] == 4
    assert second.search("feline sofa")[0]["title"] == "Pets"  # keyword search needs no vectors
    assert second.search("how do I reset my password") == []  # meaning search does

    seen: list[tuple[int, int]] = []
    outcome = second.reembed(batch=2, progress=lambda done, total: seen.append((done, total)))

    assert outcome["embedded"] == 4 and outcome["waiting"] == 0
    assert seen == [(2, 4), (4, 4)]
    assert second.search("how do I reset my password")[0]["title"] == "Account help"
    # Vectors from the model no longer in use are removed once every passage has a new one.
    connection = sqlite3.connect(second.path)
    assert [row[0] for row in connection.execute("SELECT DISTINCT backend FROM vectors")] == ["test:concepts"]
    connection.close()


def test_reembed_stops_cleanly_when_the_model_fails(tmp_path):
    folder = tmp_path / "kb"
    first = KnowledgeStore(folder, embedder=HashEmbedder())
    fill(first)
    first.close()
    second = KnowledgeStore(folder, embedder=ConceptEmbedder(fail=True))

    outcome = second.reembed()

    assert outcome["embedded"] == 0 and outcome["waiting"] == 4 and "not running" in outcome["error"]


# --- the database itself --------------------------------------------------------------------------------


def test_a_database_from_a_newer_app_is_left_untouched(tmp_path):
    folder = tmp_path / "kb"
    KnowledgeStore(folder, embedder=HashEmbedder()).close()
    connection = sqlite3.connect(folder / "knowledge.sqlite3")
    connection.execute("PRAGMA user_version = 99")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer than this app understands"):
        KnowledgeStore(folder, embedder=HashEmbedder())


def test_old_json_index_is_imported_once_and_kept(tmp_path):
    folder = tmp_path / "kb"
    folder.mkdir()
    words = [f"word{index}" for index in range(1700)]
    words[900] = "feline"
    old_chunks = {
        "abc123": {
            "c1": {"text": " ".join(words[0:750]), "chunk_index": 0, "start_word": 0, "end_word": 750},
            "c2": {"text": " ".join(words[650:1400]), "chunk_index": 1, "start_word": 650, "end_word": 1400},
            "c3": {"text": " ".join(words[1300:1700]), "chunk_index": 2, "start_word": 1300, "end_word": 1700},
        },
        "def456": {"only": {"text": "A short note about the invoice.", "chunk_index": 0, "start_word": 0, "end_word": 6}},
        "empty": {},
    }
    old_meta = {
        "abc123": {"url": "https://example.org/long", "title": "Long page", "timestamp": "2026-05-01T10:00:00", "source_type": "url"},
        "def456": {"url": "knowledge_note:note.md", "title": "note.md", "source_type": "knowledge_note"},
    }
    (folder / "chunks.json").write_text(json.dumps(old_chunks), encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps(old_meta), encoding="utf-8")
    (folder / "embeddings.json").write_text(json.dumps({"abc123": {"c1": [0.0] * 384}}), encoding="utf-8")

    store = KnowledgeStore(folder, embedder=ConceptEmbedder())

    assert store.legacy_import["documents"] == 2
    documents = {row["source"]: row for row in store.list_documents()}
    assert set(documents) == {"https://example.org/long", "knowledge_note:note.md"}
    assert documents["https://example.org/long"]["title"] == "Long page"
    assert documents["https://example.org/long"]["kind"] == "url"
    # The overlapping 750-word pieces were joined back without repeating the overlap.
    assert documents["https://example.org/long"]["words"] == 1700
    assert store.search("kitten")[0]["title"] == "Long page"
    assert store.search("invoice")[0]["kind"] == "knowledge_note"
    # The old files are kept under another name, and the import does not run again.
    assert not (folder / "chunks.json").exists()
    assert len(list(folder.glob("chunks.json.migrated-*"))) == 1
    assert len(list(folder.glob("embeddings.json.migrated-*"))) == 1
    store.close()
    again = KnowledgeStore(folder, embedder=ConceptEmbedder())
    assert again.legacy_import == {} and again.stats()["documents"] == 2


ADD_DOCUMENTS = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from modules.embeddings import HashEmbedder
from modules.knowledge_store import KnowledgeStore
store = KnowledgeStore(Path(sys.argv[2]), embedder=HashEmbedder())
worker, count = int(sys.argv[3]), int(sys.argv[4])
for index in range(count):
    store.add_document(f"file:w{worker}-{index}.md", f"Doc {worker}-{index}", f"worker{worker} item{index} talks about topic{worker * 100 + index}. " * 5, kind="file")
    assert store.search(f"topic{worker * 100 + index}")
"""


def test_separate_programs_can_add_and_search_at_the_same_time(tmp_path):
    """The desktop app and the phone backend share this database."""

    folder = tmp_path / "kb"
    KnowledgeStore(folder, embedder=HashEmbedder()).close()
    workers, per_worker = 3, 8
    processes = [
        subprocess.Popen([sys.executable, "-c", ADD_DOCUMENTS, REPO_ROOT, str(folder), str(worker), str(per_worker)], stderr=subprocess.PIPE)
        for worker in range(workers)
    ]
    for process in processes:
        _out, error = process.communicate(timeout=240)
        assert process.returncode == 0, error.decode(errors="replace")

    store = KnowledgeStore(folder, embedder=HashEmbedder())
    assert store.stats()["documents"] == workers * per_worker
    assert store.stats()["waiting_for_vectors"] == 0
    for worker in range(workers):
        assert store.search(f"topic{worker * 100 + 3}")[0]["title"] == f"Doc {worker}-3"


def test_document_ids_are_stable():
    assert document_id("file:a.md") == document_id("file:a.md") != document_id("file:b.md")
    assert len(document_id("x")) == 16


# --- chunking -------------------------------------------------------------------------------------------


def test_chunks_follow_headings_and_keep_line_breaks():
    text = "# Setup\n\nInstall the tool.\n\nThen run it.\n\n## Troubleshooting\n\n" + "If it fails, check the log. " * 40 + "\n\n```\npip install tool\ntool --check\n```\n"

    chunks = chunk_text(text, target_words=60, overlap_words=10)

    assert chunks[0].heading == "Setup" and "Install the tool." in chunks[0].text
    assert all(chunk.heading == "Troubleshooting" for chunk in chunks[1:])
    assert any("pip install tool\ntool --check" in chunk.text for chunk in chunks)  # the code block is intact
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert max(len(chunk.text.split()) for chunk in chunks) <= 95


def test_chunk_ids_do_not_collide_for_passages_with_the_same_opening():
    opening = "This standard header is repeated at the top of every section of the manual and is quite long indeed. "
    text = "\n\n".join(opening + f"Section {index} then says something different about item {index}. " * 6 for index in range(5))

    ids = [chunk.to_dict()["chunk_id"] for chunk in chunk_text(text, target_words=60)]

    assert len(ids) == len(set(ids)) >= 5


def test_code_is_split_at_definitions_with_line_numbers():
    code = "import os\n\n" + "\n\n".join(
        f"def function_{index}(value):\n" + "".join(f"    step_{line} = value + {line}\n" for line in range(24)) + f"    return step_23  # end {index}"
        for index in range(4)
    )

    chunks = chunk_code(code, language="Python")

    assert len(chunks) == 4
    assert chunks[0].text.startswith("import os") and "def function_0" in chunks[0].text
    assert chunks[1].text.startswith("def function_1") and chunks[1].start_line == 30
    assert chunks[2].heading == "Python source, from line 57"
    assert "\n    step_0 = value + 0" in chunks[1].text  # indentation and line breaks survive
    assert "\n".join(chunk.text for chunk in chunks).count("return step_23") == 4


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == [] and chunk_text("  \n\n ") == [] and chunk_code("") == []


# --- choosing an embedding backend ----------------------------------------------------------------------


class _Tags:
    def __init__(self, names, fail=False):
        self.names, self.fail = names, fail

    def get(self, url, timeout=None):
        if self.fail:
            raise OSError("connection refused")

        class Response:
            def raise_for_status(inner):
                return None

            def json(inner):
                return {"models": [{"name": name} for name in self.names]}

        return Response()


def test_an_installed_ollama_embedding_model_is_used_automatically():
    session = _Tags(["dolphin3:8b", "nomic-embed-text:latest", "all-minilm:latest"])

    assert installed_ollama_embedding_models("http://ollama.test", session=session) == ["all-minilm:latest", "nomic-embed-text:latest"]
    embedder, status = choose_embedder("auto", ollama_url="http://ollama.test", session=session)

    assert embedder.name == "ollama:all-minilm:latest" and embedder.semantic
    assert (status["runtime_backend"], status["degraded"]) == ("ollama", False)


def test_without_any_embedding_model_search_is_marked_degraded():
    for session in (_Tags(["dolphin3:8b"]), _Tags([], fail=True)):
        embedder, status = choose_embedder("auto", ollama_url="http://ollama.test", session=session)

        assert isinstance(embedder, HashEmbedder) and not embedder.semantic
        assert status["degraded"] is True and status["runtime_backend"] == "hash"
        assert "ollama pull all-minilm" in status["message"] and "not meaning" in status["message"]


def test_choosing_word_hash_vectors_on_purpose_is_not_reported_as_degraded():
    embedder, status = choose_embedder("hash")

    assert isinstance(embedder, HashEmbedder) and status["degraded"] is False
    assert len(embedder.embed(["local private knowledge"])[0]) == 384


def test_a_named_ollama_model_that_is_missing_is_reported():
    _embedder, status = choose_embedder("ollama", "bge-m3", ollama_url="http://ollama.test", session=_Tags(["all-minilm:latest"]))

    # The installed one is used, and the status does not pretend the requested one exists.
    assert status["model"] == "all-minilm:latest"


def test_ollama_embedder_batches_normalizes_and_reports_failures():
    class Session:
        def __init__(self):
            self.calls = []
            self.fail = False

        def post(self, url, json=None, timeout=None):
            self.calls.append(json)
            if self.fail:
                raise __import__("requests").ConnectionError("refused")

            class Response:
                def raise_for_status(inner):
                    return None

                def json(inner):
                    return {"embeddings": [[3.0, 4.0] for _ in json["input"]]}

            return Response()

    session = Session()
    embedder = OllamaEmbedder("all-minilm", "http://ollama.test", session=session)

    vectors = embedder.embed([f"text {index}" for index in range(40)])

    assert len(vectors) == 40 and vectors[0] == [0.6, 0.8]
    assert [len(call["input"]) for call in session.calls] == [32, 8]
    assert session.calls[0]["model"] == "all-minilm" and session.calls[0]["truncate"] is True

    session.fail = True
    with pytest.raises(EmbeddingError, match="all-minilm"):
        embedder.embed(["x"])
