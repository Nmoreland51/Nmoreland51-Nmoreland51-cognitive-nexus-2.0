import unittest

from modules.context_manager import build_context_bundle, estimate_tokens, trim_text


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


if __name__ == "__main__":
    unittest.main()
