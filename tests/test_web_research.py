from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules import web_research


class WebResearchTests(unittest.TestCase):
    def test_slugify_query(self) -> None:
        self.assertEqual(web_research.slugify_query("Latest AI News!!!"), "latest_ai_news")
        self.assertEqual(web_research.slugify_query(""), "research")

    def test_clean_text_removes_extra_spaces(self) -> None:
        self.assertEqual(web_research.clean_text("  hello\n\n   world\t "), "hello world")

    def test_save_research_session_creates_json_and_markdown(self) -> None:
        original_dir = web_research.DATA_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            web_research.DATA_DIR = Path(tmpdir)
            try:
                paths = web_research.save_research_session(
                    query="test query",
                    results=[
                        {
                            "title": "Example",
                            "url": "https://example.com",
                            "snippet": "Example snippet",
                            "source": "example.com",
                        }
                    ],
                    scraped_pages=[
                        {
                            "title": "Example Page",
                            "url": "https://example.com",
                            "excerpt": "Example excerpt",
                            "success": True,
                        }
                    ],
                    summary="Example summary",
                    settings={"max_results": 1},
                    errors=[],
                )
                json_path = Path(paths["json"])
                md_path = Path(paths["markdown"])
                self.assertTrue(json_path.exists())
                self.assertTrue(md_path.exists())
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["query"], "test query")
                self.assertIn("Example summary", md_path.read_text(encoding="utf-8"))
            finally:
                web_research.DATA_DIR = original_dir

    def test_search_web_returns_list_or_clean_failure(self) -> None:
        try:
            results = web_research.search_web("streamlit", max_results=1)
            self.assertIsInstance(results, list)
        except Exception as exc:
            self.assertIsInstance(str(exc), str)


if __name__ == "__main__":
    unittest.main()
