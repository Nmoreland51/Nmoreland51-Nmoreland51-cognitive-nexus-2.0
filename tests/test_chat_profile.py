import json
import tempfile
import unittest
from pathlib import Path

from modules.chat_profile import (
    ChatProfile,
    build_capability_greeting,
    load_chat_profile,
    save_chat_profile,
)
from modules.internal_prompts import chat_system_prompt


class ChatProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.temp_dir.name) / "chat_profile.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_profile_loads_defaults(self):
        profile = load_chat_profile(self.profile_path)

        self.assertEqual(profile.user_name, "user")
        self.assertEqual(profile.assistant_name, "ENI")
        self.assertTrue(profile.enabled)

    def test_save_and_reload_round_trip(self):
        saved = save_chat_profile(
            ChatProfile(
                user_name="Morgan",
                assistant_name="Iris",
                creative_min_words=650,
                humor_level="balanced",
                humor_style="dry_deadpan",
                humor_notes="Use one quick aside when the moment has room.",
                additional_instructions="Keep the voice sharp.",
            ),
            self.profile_path,
        )
        reloaded = load_chat_profile(self.profile_path)

        self.assertEqual(saved.user_name, "Morgan")
        self.assertEqual(reloaded.assistant_name, "Iris")
        self.assertEqual(reloaded.creative_min_words, 650)
        self.assertEqual(reloaded.humor_level, "balanced")
        self.assertEqual(reloaded.humor_style, "dry_deadpan")
        self.assertIn("quick aside", reloaded.humor_notes)

    def test_system_prompt_carries_the_persona_as_the_owners_instructions(self):
        prompt = chat_system_prompt(ChatProfile())

        self.assertIn("Persona, as the owner set it:", prompt)
        self.assertIn("Your name: ENI", prompt)
        self.assertIn("Humour: light, warm wit", prompt)
        # The persona is an instruction. Nothing in the prompt says it can be overridden.
        self.assertNotIn("cannot override", prompt)
        self.assertNotIn("consensual adult fictional content", prompt)

    def test_system_prompt_follows_the_humour_setting(self):
        prompt = chat_system_prompt(ChatProfile(humor_level="bold", humor_style="playful_spark"))

        self.assertIn("Humour: bold, playful spark", prompt)
        self.assertNotIn("Humour:", chat_system_prompt(ChatProfile(humor_level="off")))

    def test_a_disabled_persona_adds_nothing(self):
        self.assertNotIn("Persona, as the owner set it", chat_system_prompt(ChatProfile(enabled=False)))

    def test_greeting_lists_capabilities_and_the_one_rule(self):
        greeting = build_capability_greeting(ChatProfile())

        self.assertIn("ENI mode is active", greeting)
        self.assertIn("I can help", greeting)
        self.assertIn("one content rule", greeting)
        self.assertIn("no sexual content involving minors", greeting)
        # The greeting used to claim two further limits that the app does not have.
        self.assertNotIn("real private people", greeting)
        self.assertNotIn("real-world harm", greeting)

    def test_saved_profile_is_json_object(self):
        save_chat_profile(ChatProfile(), self.profile_path)
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["assistant_name"], "ENI")


if __name__ == "__main__":
    unittest.main()
