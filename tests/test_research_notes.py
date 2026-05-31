import tempfile
import unittest
from pathlib import Path

from modules.research import list_knowledge_notes, save_knowledge_note, slugify_note_title
from web_research_module import WebResearchModule


class ResearchNotesTests(unittest.TestCase):
    def test_slugify_note_title(self):
        self.assertEqual(slugify_note_title("Project Memory: Phase 7!"), "project_memory_phase_7")
        self.assertEqual(slugify_note_title(""), "knowledge_note")

    def test_save_knowledge_note_writes_markdown_and_ingests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = WebResearchModule(str(root / "kb"))

            result = save_knowledge_note(
                module,
                title="Useful project fact",
                text="Cognitive Nexus stores local Markdown notes for later retrieval.",
                tags="memory, rag",
                ingest=True,
                notes_dir=root / "notes",
            )

            self.assertEqual(result["status"], "success")
            self.assertTrue(result["ingested"])
            note_path = Path(result["path"])
            self.assertTrue(note_path.exists())
            note_text = note_path.read_text(encoding="utf-8")
            self.assertIn("# Useful project fact", note_text)
            self.assertIn("Tags: memory, rag", note_text)
            matches = module.semantic_search("Markdown notes retrieval", top_k=3)
            self.assertTrue(matches)

    def test_list_knowledge_notes_returns_recent_note_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            path = notes_dir / "20260529_test.md"
            path.write_text(
                "# Test Note\n\nCreated: now\nTags: test\nSource: manual_knowledge_note\n\nRemember this local note.",
                encoding="utf-8",
            )

            notes = list_knowledge_notes(notes_dir=notes_dir, limit=5)

            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["title"], "Test Note")
            self.assertEqual(notes[0]["tags"], "test")
            self.assertIn("Remember this local note", notes[0]["excerpt"])


if __name__ == "__main__":
    unittest.main()
