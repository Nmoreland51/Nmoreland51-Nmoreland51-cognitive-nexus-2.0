import json
import tempfile
import unittest
from pathlib import Path

from cognitive_nexus.adaptation import AdaptiveMemoryManager, AdaptivePolicy


class AdaptiveMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.manager = AdaptiveMemoryManager(self.data_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_remember_and_forget_commands_manage_profile_memory(self):
        remember_response = self.manager.handle_memory_command("remember that I prefer short answers")
        self.assertIn("remember", remember_response.lower())
        self.assertEqual(self.manager.profile.preferences["detail_level"]["value"], "short")

        forget_response = self.manager.handle_memory_command("forget short answers")
        self.assertIn("forgot", forget_response.lower())
        self.assertNotIn("detail_level", self.manager.profile.preferences)

    def test_extract_turn_signals_detects_short_and_search_preferences(self):
        signals = self.manager.extract_turn_signals("keep it short and don't search unless I ask")

        self.assertEqual(signals.detail_level, "short")
        self.assertEqual(signals.search_preference, "only_when_requested")
        self.assertEqual(signals.explicit_preferences["detail_level"], "short")
        self.assertEqual(signals.explicit_preferences["search_preference"], "only_when_requested")

    def test_extract_turn_signals_detects_correction(self):
        signals = self.manager.extract_turn_signals("that's wrong, I meant the short version")

        self.assertTrue(signals.frustration)
        self.assertIn("meant", signals.correction_text.lower())

    def test_repeated_implicit_signals_promote_pattern_after_threshold(self):
        for _ in range(3):
            signals = self.manager.extract_turn_signals("tell me more")
            self.manager.observe_turn("tell me more", signals)

        self.assertIn("detail_level", self.manager.profile.patterns)
        self.assertEqual(self.manager.profile.patterns["detail_level"]["value"], "detailed")

    def test_explicit_feedback_correction_updates_policy_preferences(self):
        event = self.manager.record_feedback("turn_123", "down", "be shorter next time")

        self.assertEqual(event.inferred_preferences["detail_level"], "short")
        self.assertEqual(self.manager.profile.preferences["detail_level"]["value"], "short")

    def test_resolve_policy_prefers_current_turn_signal_over_profile(self):
        self.manager.profile.preferences["tone"] = {
            "value": "formal",
            "source": "explicit_memory",
            "updated_at": "now",
        }
        signals = self.manager.extract_turn_signals("be more casual")

        policy = self.manager.resolve_policy(signals)

        self.assertIsInstance(policy, AdaptivePolicy)
        self.assertEqual(policy.tone, "casual")

    def test_seed_knowledge_is_searchable(self):
        seed_dir = self.data_dir / "seed_knowledge"
        seed_dir.mkdir(parents=True, exist_ok=True)
        (seed_dir / "python.md").write_text("Python decorators wrap functions with reusable behavior.", encoding="utf-8")

        snippets = self.manager.search_seed_knowledge("python decorators")

        self.assertTrue(snippets)
        self.assertIn("decorators", snippets[0].lower())

    def test_context_bundle_includes_profile_and_seed_knowledge(self):
        self.manager.handle_memory_command("remember that I prefer short answers")
        seed_dir = self.data_dir / "seed_knowledge"
        seed_dir.mkdir(parents=True, exist_ok=True)
        (seed_dir / "notes.json").write_text(
            json.dumps({"topic": "decorators", "summary": "Decorators wrap functions."}),
            encoding="utf-8",
        )

        bundle = self.manager.build_context_bundle(
            "python decorators",
            recent_messages=[{"role": "user", "content": "Tell me about decorators"}],
            chat_history=[{"user": "Explain decorators", "assistant": "Decorators wrap functions."}],
            topic_knowledge={},
            learned_facts={},
            policy=self.manager.resolve_policy(),
        )

        self.assertIn("Preference - detail_level: short", bundle.rendered_context)
        self.assertIn("Decorators wrap functions", bundle.rendered_context)


if __name__ == "__main__":
    unittest.main()
