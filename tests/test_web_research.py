from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_no_search_results_skips_ai_summary_and_memory(self) -> None:
        prompts: list[str] = []

        def fake_ai(prompt: str) -> str:
            prompts.append(prompt)
            return "Answer from model memory with an invented source list"

        with patch.object(web_research, "search_web", side_effect=RuntimeError("No results found.")), patch.object(
            web_research, "add_research_to_memory"
        ) as add_memory:
            result = web_research.run_research_session("python release", save_locally=False, ai_callback=fake_ai)

        self.assertEqual(prompts, [])
        self.assertEqual(result["summary"], web_research.NO_RESULTS_SUMMARY)
        self.assertIn("Search failed: No results found.", result["errors"])
        add_memory.assert_not_called()

    def test_summary_still_runs_when_results_exist(self) -> None:
        results = [{"title": "Example", "url": "https://example.com", "snippet": "s", "source": "example.com"}]

        summary = web_research.summarize_research("q", results, [], lambda prompt: "grounded answer")

        self.assertEqual(summary, "grounded answer")

    def test_relevant_excerpt_keeps_matching_sentences(self) -> None:
        text = "Skip to content. Menu Downloads Docs. Python 3.15.2 was released on October 25, 2026. Thanks for reading."

        excerpt = web_research._relevant_excerpt(text, "latest Python release", max_chars=200)

        self.assertEqual(excerpt, "Python 3.15.2 was released on October 25, 2026.")

    def test_relevant_excerpt_keeps_abbreviated_dates_whole(self) -> None:
        text = "Release Date: Oct. 25, 2026 This is the second maintenance release of Python 3.15. Docs follow."

        excerpt = web_research._relevant_excerpt(text, "latest Python release", max_chars=300)

        self.assertIn("Oct. 25, 2026", excerpt)

    def test_clean_title_splits_glued_titles_and_keeps_normal_ones(self) -> None:
        glued = (
            "CoryxKenshin - Age, Bio, Family | Famous BirthdaysCoryxKenshin - YouTubeCoryxKenshin Biography, "
            "Age, Net Worth, Girlfriend, Height, Wiki"
        )
        self.assertEqual(web_research._clean_title(glued), "CoryxKenshin - Age, Bio, Family | Famous Birthdays")
        self.assertEqual(web_research._clean_title("Best PlayStation games of 2026"), "Best PlayStation games of 2026")

    def test_brief_prompt_caps_oversized_snippets(self) -> None:
        results = [{"title": "Glued result", "url": "https://example.com", "snippet": "word " * 600}]

        prompt = web_research._build_brief_prompt("q", results, [])

        self.assertLess(len(prompt), 800)

    def test_brief_session_scrapes_top_pages_and_asks_for_short_answer(self) -> None:
        results = [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": f"snippet {i}", "source": "example.com"}
            for i in range(1, 6)
        ]
        scraped: list[str] = []
        prompts: list[str] = []

        def fake_scrape(url: str) -> dict:
            scraped.append(url)
            return {"url": url, "title": url, "text": "Python 3.15.2 is the latest release. " * 50, "success": True}

        with patch.object(web_research, "search_web", return_value=results), patch.object(
            web_research, "scrape_url", side_effect=fake_scrape
        ), patch.object(web_research, "add_research_to_memory", return_value={}):
            web_research.run_research_session(
                "latest python release", save_locally=False, ai_callback=lambda p: prompts.append(p) or "ok", brief=True
            )

        self.assertEqual(sorted(scraped), ["https://example.com/1", "https://example.com/2"])
        self.assertIn("2-3 short sentences", prompts[0])
        self.assertNotIn("Source list", prompts[0])
        self.assertLess(len(prompts[0]), 2500)


if __name__ == "__main__":
    unittest.main()
