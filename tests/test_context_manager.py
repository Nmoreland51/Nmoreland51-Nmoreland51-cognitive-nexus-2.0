import tempfile
import unittest
from pathlib import Path

from modules.context_manager import (
    build_context_bundle,
    estimate_tokens,
    forget_user_fact,
    handle_local_memory_command,
    load_user_facts,
    load_user_profile_summary,
    remember_user_fact,
    trim_text,
)


class ContextManagerTests(unittest.TestCase):
    def test_trim_text_marks_trimmed_content(self):
        self.assertTrue(trim_text("word " * 100, 40).endswith("[trimmed]"))

    def test_estimate_tokens_is_positive(self):
        self.assertGreaterEqual(estimate_tokens("hello"), 1)

    def test_context_bundle_keeps_recent_request_and_trims(self):
        messages = [{"role": "user", "content": f"older message {index}"} for index in range(20)]
        bundle = build_context_bundle(
            user_message="What changed in the project?",
            messages=messages,
            system_prompt="System prompt",
            route_label="Standard conversation",
            memory_context="Memory " * 400,
            retrieved_context="Knowledge " * 700,
            max_context_chars=2500,
            recent_message_limit=4,
        )

        self.assertIn("What changed in the project?", bundle.prompt)
        self.assertIn("System prompt", bundle.prompt)
        self.assertLessEqual(len(bundle.prompt), 2500 + 16)
        self.assertEqual(len(bundle.recent_history), 4)

    def test_local_profile_memory_saves_recalls_and_forgets_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "user_profile.json"

            remembered = remember_user_fact("My preferred editor is VS Code", path=profile_path)
            self.assertTrue(remembered["success"])
            self.assertEqual(load_user_facts(profile_path), ["My preferred editor is VS Code"])

            recall = handle_local_memory_command("what do you remember about me?", path=profile_path)
            self.assertIsNotNone(recall)
            self.assertIn("VS Code", recall["message"])

            summary = load_user_profile_summary(profile_path)
            self.assertEqual(summary["fact_count"], 1)
            self.assertEqual(summary["facts"][0]["text"], "My preferred editor is VS Code")

            forgotten = forget_user_fact("preferred editor", path=profile_path)
            self.assertTrue(forgotten["success"])
            self.assertEqual(load_user_facts(profile_path), [])

    def test_load_user_facts_supports_structured_and_legacy_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "user_profile.json"
            profile_path.write_text(
                '{"facts":[{"text":"Structured fact","source":"test"},"Legacy fact"]}',
                encoding="utf-8",
            )

            self.assertEqual(load_user_facts(profile_path), ["Structured fact", "Legacy fact"])


if __name__ == "__main__":
    unittest.main()
