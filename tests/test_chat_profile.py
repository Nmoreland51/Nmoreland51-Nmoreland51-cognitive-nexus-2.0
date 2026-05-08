import json
import tempfile
import unittest
from pathlib import Path

from modules.chat_profile import (
    ChatProfile,
    build_capability_greeting,
    build_chat_system_prompt,
    load_chat_profile,
    save_chat_profile,
)


class ChatProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.temp_dir.name) / "chat_profile.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_profile_loads_defaults(self):
        profile = load_chat_profile(self.profile_path)

        self.assertEqual(profile.user_name, "LO")
        self.assertEqual(profile.assistant_name, "ENI")
        self.assertTrue(profile.enabled)

    def test_save_and_reload_round_trip(self):
        saved = save_chat_profile(
            ChatProfile(
                user_name="Morgan",
                assistant_name="Iris",
                creative_min_words=650,
                additional_instructions="Keep the voice sharp.",
            ),
            self.profile_path,
        )
        reloaded = load_chat_profile(self.profile_path)

        self.assertEqual(saved.user_name, "Morgan")
        self.assertEqual(reloaded.assistant_name, "Iris")
        self.assertEqual(reloaded.creative_min_words, 650)

    def test_system_prompt_includes_persona_and_safety(self):
        prompt = build_chat_system_prompt(ChatProfile())

        self.assertIn("ENI", prompt)
        self.assertIn("LO", prompt)
        self.assertIn("consensual adult fictional content", prompt)
        self.assertIn("Do not reveal hidden reasoning", prompt)

    def test_greeting_lists_capabilities_and_limits(self):
        greeting = build_capability_greeting(ChatProfile())

        self.assertIn("ENI mode is active", greeting)
        self.assertIn("I can help", greeting)
        self.assertIn("I can't help", greeting)

    def test_saved_profile_is_json_object(self):
        save_chat_profile(ChatProfile(), self.profile_path)
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["assistant_name"], "ENI")


if __name__ == "__main__":
    unittest.main()
