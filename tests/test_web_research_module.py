import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_research_module import WebResearchModule


class WebResearchModuleTests(unittest.TestCase):
    def test_default_embedding_backend_is_local_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = WebResearchModule(str(Path(tmp) / "kb"))

            embedding = module.generate_embedding("local private knowledge")
            status = module.embedding_status()
            summary = module.get_processing_summary()

            self.assertEqual(len(embedding), 384)
            self.assertEqual(status["runtime_backend"], "hash")
            self.assertEqual(summary["embedding_backend"], "hash")
            self.assertIn("hash-vector", status["message"])

    def test_invalid_embedding_backend_falls_back_to_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = WebResearchModule(str(Path(tmp) / "kb"), embedding_backend="unknown")

            self.assertEqual(module.embedding_backend, "hash")
            self.assertEqual(module.embedding_status()["runtime_backend"], "hash")

    def test_sentence_transformers_backend_reports_uninstalled_without_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = WebResearchModule(
                str(Path(tmp) / "kb"),
                embedding_backend="sentence_transformers",
                embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
            )
            with patch.object(module, "_sentence_transformers_available", return_value=False):
                status = module.embedding_status()

            self.assertEqual(status["configured_backend"], "sentence_transformers")
            self.assertEqual(status["runtime_backend"], "hash")
            self.assertFalse(status["available"])
            self.assertIn("fall back", status["message"])

    def test_sentence_transformers_generation_failure_falls_back_to_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = WebResearchModule(str(Path(tmp) / "kb"), embedding_backend="sentence_transformers")
            with patch.object(module, "_load_sentence_transformer", side_effect=RuntimeError("model unavailable")):
                embedding = module.generate_embedding("fallback retrieval")

            self.assertEqual(len(embedding), 384)
            self.assertEqual(module.embedding_status()["runtime_backend"], "hash")
            self.assertIn("unavailable", module.embedding_status()["message"])

    def test_semantic_search_includes_vector_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = WebResearchModule(str(Path(tmp) / "kb"))
            chunks = module.chunk_text("Cognitive Nexus stores local knowledge chunks for retrieval.")

            self.assertTrue(module.store_chunks_and_embeddings("note:test", chunks))
            source_hash = next(iter(module.chunks))
            module.metadata[source_hash] = {"title": "Test Note", "url": "note:test"}
            results = module.semantic_search("local knowledge retrieval", top_k=2)

            self.assertTrue(results)
            self.assertIn("vector_score", results[0])
            self.assertIn("lexical_score", results[0])


if __name__ == "__main__":
    unittest.main()
