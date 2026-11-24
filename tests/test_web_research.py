from __future__ import annotations

import json
import os
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

    def test_flatten_markdown_keeps_headings_as_sentences(self) -> None:
        text = "# \n\nIntro text.\n\n## Version 1.67.0 (latest)\n\nRelease date: **November 5, 2026**\n\nSee __init__.py"

        flat = web_research.clean_text(web_research._flatten_markdown(text))

        self.assertEqual(flat, "Intro text. Version 1.67.0 (latest). Release date: November 5, 2026 See __init__.py")

    def test_unsourced_numbers_flags_versions_and_years_missing_from_sources(self) -> None:
        sources = "Version 1.67.0 (latest). Release date: November 5, 2026. Python 3.15.2 was released Oct. 25, 2026."

        self.assertEqual(web_research.unsourced_numbers("Streamlit 1.28.0 came out in 2023.", sources), ["1.28.0", "2023"])
        self.assertEqual(web_research.unsourced_numbers("Python 3.15.2 came out October 25, 2026.", sources), [])
        self.assertEqual(web_research.unsourced_numbers("The latest LTS is v14 (2020).", sources), ["v14", "2020"])
        self.assertEqual(web_research.unsourced_numbers_note("Latest is v1.67.0", sources), "")
        self.assertIn("1.28.0", web_research.unsourced_numbers_note("Latest is 1.28.0", sources))

    def test_summary_gets_warning_for_unsourced_version(self) -> None:
        results = [{"title": "Release notes", "url": "https://example.com", "snippet": "Version 1.67.0 (latest)", "source": "example.com"}]

        summary = web_research.summarize_research("latest streamlit", results, [], lambda prompt: "The latest is 1.28.0.")

        self.assertTrue(summary.startswith("The latest is 1.28.0."))
        self.assertIn("Not found in the sources: 1.28.0", summary)

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

        # The cap is on the snippet (300 characters); the fixed text around it (the instructions,
        # the untrusted-content rule and the fence) is about 900 characters since the corrective
        # phase added two sentences to the instructions (names only from the results; when the
        # results do not answer, say so and then what they do say).
        self.assertLess(len(prompt), 1250)
        self.assertLess(prompt.count("word "), 70)

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


class SearchSourceSwitchingTests(unittest.TestCase):
    RESULT = [{"title": "Hit", "url": "https://example.com/hit", "snippet": "s", "source": "example.com", "timestamp": ""}]

    def setUp(self) -> None:
        web_research._search_web_cached.cache_clear()
        web_research._cooldown_until.clear()

    tearDown = setUp

    def _env(self, **extra: str):
        return patch.dict(os.environ, {"SEARCH_SOURCES": "searxng,ddgs,wikipedia", "SEARXNG_URL": "http://localhost:8888", **extra})

    def test_switches_to_next_source_on_error_and_skips_it_afterwards(self) -> None:
        calls: list[str] = []

        def failing(query: str, max_results: int) -> list:
            calls.append(query)
            raise RuntimeError("HTTP 429 Too Many Requests")

        with self._env(), patch.dict(
            web_research._SEARCH_SOURCES, {"searxng": failing, "ddgs": lambda q, n: [dict(r) for r in self.RESULT]}
        ):
            first = web_research.search_web("first query")
            second = web_research.search_web("second query")

        self.assertEqual(first[0]["search_source"], "ddgs")
        self.assertEqual(second[0]["search_source"], "ddgs")
        self.assertEqual(calls, ["first query"])  # skipped while cooling down
        status = {s["name"]: s for s in web_research.search_sources_status()}
        self.assertGreater(status["searxng"]["cooldown_seconds"], 0)

    def test_switches_on_empty_results_without_cooldown(self) -> None:
        with self._env(), patch.dict(
            web_research._SEARCH_SOURCES,
            {"searxng": lambda q, n: [], "ddgs": lambda q, n: [], "wikipedia": lambda q, n: [dict(r) for r in self.RESULT]},
        ):
            results = web_research.search_web("who is someone")

        self.assertEqual(results[0]["search_source"], "wikipedia")
        self.assertFalse(web_research._cooldown_until)

    def test_raises_when_every_source_fails(self) -> None:
        with self._env(), patch.dict(
            web_research._SEARCH_SOURCES, {"searxng": lambda q, n: [], "ddgs": lambda q, n: [], "wikipedia": lambda q, n: []}
        ):
            with self.assertRaisesRegex(RuntimeError, "No results found"):
                web_research.search_web("nothing anywhere")

    def test_unconfigured_sources_are_skipped_with_setup_hint(self) -> None:
        with patch.dict(os.environ, {"SEARCH_SOURCES": "searxng,brave,ddgs,wikipedia"}, clear=False):
            os.environ.pop("SEARXNG_URL", None)
            os.environ.pop("BRAVE_SEARCH_API_KEY", None)
            status = {s["name"]: s for s in web_research.search_sources_status()}

        self.assertFalse(status["searxng"]["available"])
        self.assertEqual(status["brave"]["setup"], "link Brave Search in Settings, Linked accounts, or set BRAVE_SEARCH_API_KEY")
        self.assertTrue(status["wikipedia"]["available"])

    def test_source_responses_are_parsed(self) -> None:
        payloads = {
            "searxng": {"results": [{"title": "SX", "url": "https://a.example/1", "content": "searx snippet"}]},
            "brave": {"web": {"results": [{"title": "BR", "url": "https://b.example/1", "description": "brave snippet"}]}},
            "wikipedia": {"query": {"search": [{"title": "Ollama", "snippet": "<span>Ollama</span> is &quot;local&quot;"}]}},
        }
        for name, payload in payloads.items():
            with self._env(BRAVE_SEARCH_API_KEY="key"), patch.object(web_research, "_get_json", return_value=payload):
                results = web_research._SEARCH_SOURCES[name]("q", 5)
            self.assertEqual(len(results), 1, name)
            self.assertTrue(results[0]["url"].startswith("https://"), name)
        self.assertEqual(results[0]["url"], "https://en.wikipedia.org/wiki/Ollama")
        self.assertEqual(results[0]["snippet"], 'Ollama is "local"')

    def test_keyword_query_drops_question_words(self) -> None:
        self.assertEqual(web_research._keyword_query("who is coryxkenshin"), "coryxkenshin")
        self.assertEqual(web_research._keyword_query("the latest version of Streamlit"), "version Streamlit")


if __name__ == "__main__":
    unittest.main()
