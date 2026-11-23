import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_repo_hygiene", Path(__file__).resolve().parents[1] / "tools" / "check_repo_hygiene.py"
)
hygiene = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hygiene)


class RepoHygieneTests(unittest.TestCase):
    def test_secret_patterns_catch_real_shapes_and_ignore_placeholders(self):
        samples = {
            "OpenAI API key": "OPENAI_API_KEY=sk-proj-" + "a1B2c3D4" * 6,
            "Anthropic API key": "key = sk-ant-" + "Zx9" * 12,
            "GitHub token": "ghp_" + "A1b2C3d4E5" * 4,
            "AWS access key": "AKIA" + "ABCDEFGHIJKLMNOP",
            "private key block": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "hard-coded credential": 'api_key = "' + "q7W8e9R0" * 4 + '"',
        }
        for label, text in samples.items():
            with self.subTest(label=label):
                self.assertTrue(hygiene.SECRET_PATTERNS[label].search(text))
        for harmless in ("OPENAI_API_KEY=", 'api_key = ""', "BRAVE_SEARCH_API_KEY=your-key-here", "token = os.environ['X']"):
            with self.subTest(harmless=harmless):
                self.assertFalse(any(p.search(harmless) for p in hygiene.SECRET_PATTERNS.values()))

    def test_private_runtime_data_is_rejected_unless_grandfathered(self):
        failures, warnings = hygiene.find_private_data(
            [
                "app.py",
                ".env.example",
                ".env",
                "data/user_profile.json",
                "data/web_research/20261123_report.json",
                "ai_system/knowledge_bank/chat_history.json",
                "data/seed_knowledge/conversational_data.json",
            ]
        )

        self.assertEqual(failures, [".env", "data/user_profile.json", "data/web_research/20261123_report.json"])
        self.assertEqual(warnings, ["ai_system/knowledge_bank/chat_history.json"])

    def test_this_repository_is_clean(self):
        files = hygiene.tracked_files()

        self.assertEqual(hygiene.find_secrets(files), [])
        self.assertEqual(hygiene.find_private_data(files)[0], [])


if __name__ == "__main__":
    unittest.main()
