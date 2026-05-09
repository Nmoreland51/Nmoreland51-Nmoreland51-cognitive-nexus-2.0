import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from search import bloodhound_search as bh
from search.onion_search import run_onion_search


class BloodhoundSearchTests(unittest.TestCase):
    def test_detects_chat_commands(self):
        self.assertEqual(bh.detect_bloodhound_query("search for cats"), "cats")
        self.assertEqual(bh.detect_bloodhound_query("find every mention of Cognitive Nexus"), "Cognitive Nexus")
        self.assertEqual(bh.detect_bloodhound_query("bloodhound search obscure filename.py"), "obscure filename.py")
        self.assertEqual(bh.detect_bloodhound_query("normal chat message"), "")

    def test_query_expansion_includes_source_variants(self):
        variants = bh.expand_query("Cognitive Nexus", "Deep")
        self.assertIn('"Cognitive Nexus"', variants)
        self.assertTrue(any("site:github.com" in item for item in variants))
        self.assertTrue(any("site:reddit.com" in item for item in variants))

    def test_url_normalization_removes_tracking(self):
        normalized = bh.normalize_url("https://www.example.com/path/?utm_source=x&id=1#frag")
        self.assertEqual(normalized, "https://example.com/path?id=1")

    def test_run_bloodhound_search_saves_history(self):
        fake_results = [
            {
                "title": "Cognitive Nexus Release Notes",
                "url": "https://example.com/cognitive-nexus",
                "snippet": "Cognitive Nexus appears in the release notes.",
                "source": "example.com",
            }
        ]
        fake_page = {
            "url": "https://example.com/cognitive-nexus",
            "source": "example.com",
            "title": "Cognitive Nexus Release Notes",
            "text": "Cognitive Nexus appears here with exact phrase evidence.",
            "excerpt": "Cognitive Nexus appears here with exact phrase evidence.",
            "links": [],
            "success": True,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = Path(temp_dir) / "history"
            cache_dir = Path(temp_dir) / "cache"
            config = bh.BloodhoundConfig(
                depth="Quick",
                max_results=5,
                enable_cache=False,
                follow_links=False,
                save_history=True,
            )
            with patch.object(bh, "SEARCH_HISTORY_DIR", history_dir), patch.object(bh, "CACHE_DIR", cache_dir):
                with patch.object(bh, "search_web", return_value=fake_results), patch.object(bh, "scrape_url", return_value=fake_page):
                    payload = bh.run_bloodhound_search("Cognitive Nexus", config=config)
            self.assertTrue(payload["ranked_results"])
            self.assertEqual(payload["ranked_results"][0]["match_strength"], "High")
            self.assertTrue(Path(payload["saved_paths"]["json"]).exists())
            self.assertTrue(Path(payload["saved_paths"]["markdown"]).exists())

    def test_onion_disabled_status_is_graceful(self):
        config = bh.default_bloodhound_config({"enable_onion": False})
        self.assertFalse(config.enable_onion)

    def test_onion_results_are_secondary_and_not_prioritized(self):
        public = bh._score_result(
            {
                "title": "Cognitive Nexus public result",
                "url": "https://example.com/nexus",
                "snippet": "Cognitive Nexus exact phrase.",
                "source": "example.com",
                "source_type": "public_web",
            },
            "Cognitive Nexus",
            {"text": "Cognitive Nexus exact phrase appears on this public page.", "success": True},
        )
        onion = bh._score_result(
            {
                "title": "Cognitive Nexus onion result",
                "url": "http://abcdefghijklmnop.onion/nexus",
                "snippet": "Cognitive Nexus exact phrase.",
                "source": "abcdefghijklmnop.onion",
                "source_type": "onion_index",
            },
            "Cognitive Nexus",
            {"text": "Cognitive Nexus exact phrase appears on this onion page.", "success": True},
        )
        self.assertLess(onion.score, public.score)
        self.assertIn("not prioritized", onion.why_it_matters)

    def test_onion_disabled_run_returns_status(self):
        payload = run_onion_search("Cognitive Nexus", enabled=False)
        self.assertFalse(payload["status"]["enabled"])
        self.assertEqual(payload["results"], [])


if __name__ == "__main__":
    unittest.main()
