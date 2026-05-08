import json
import tempfile
import unittest
from pathlib import Path

import cognitive_nexus_ai as app


class FallbackConversationalDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        seed_dir = self.data_dir / "seed_knowledge"
        seed_dir.mkdir(parents=True, exist_ok=True)
        (seed_dir / "conversational_data.json").write_text(
            json.dumps(
                {
                    "greeting": {
                        "warm": {
                            "balanced": [
                                "Welcome back. I'm ready whenever you are."
                            ]
                        }
                    },
                    "check_in": {
                        "warm": {
                            "balanced": [
                                "I'm doing well and ready to help. What would be useful right now?"
                            ]
                        }
                    },
                    "question": {
                        "warm": {
                            "short": [
                                "I can help from local knowledge. Point me to the exact angle you want."
                            ]
                        }
                    },
                    "general": {
                        "warm": {
                            "balanced": [
                                "I'm here with you. Give me a little more detail and we'll work through it together."
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.system = app.FallbackResponseSystem(data_dir=self.data_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seeded_greeting_response_is_used(self):
        response = self.system.get_response(
            "hello",
            policy=app.AdaptivePolicy(tone="warm", detail_level="balanced"),
        )

        self.assertEqual(response, "Welcome back. I'm ready whenever you are.")

    def test_seeded_check_in_response_is_used(self):
        response = self.system.get_response(
            "how are you?",
            policy=app.AdaptivePolicy(tone="warm", detail_level="balanced"),
        )

        self.assertEqual(response, "I'm doing well and ready to help. What would be useful right now?")

    def test_seeded_question_response_uses_detail_level(self):
        response = self.system.get_response(
            "what is recursion?",
            policy=app.AdaptivePolicy(tone="warm", detail_level="short"),
        )

        self.assertEqual(response, "I can help from local knowledge. Point me to the exact angle you want.")


if __name__ == "__main__":
    unittest.main()
