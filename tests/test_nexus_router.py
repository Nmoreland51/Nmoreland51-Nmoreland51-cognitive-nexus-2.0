import unittest

from modules.chat_profile import ChatProfile
from nexus_router import (
    RouterConfig,
    build_routed_prompt,
    get_prompt_template_examples,
    route_message,
)


class NexusRouterTests(unittest.TestCase):
    def setUp(self):
        self.config = RouterConfig(
            enabled=True,
            god_mode=False,
            freedom_level="bold",
            default_model="llama3.2:3b",
            creative_model="creative-model",
            technical_model="technical-model",
            sensitive_model="sensitive-model",
            current_info_model="research-model",
        )

    def test_coding_request_routes_to_technical_model(self):
        decision = route_message("Debug this Streamlit session_state bug in Python", self.config)

        self.assertEqual(decision.category, "coding_development")
        self.assertEqual(decision.model, "technical-model")

    def test_adult_creative_request_routes_to_creative_model(self):
        decision = route_message("Write a smutty roleplay scene with strong sensual tension", self.config)

        self.assertEqual(decision.category, "adult_creative")
        self.assertEqual(decision.model, "creative-model")

    def test_current_info_request_triggers_web_research(self):
        decision = route_message("latest Ollama news today", self.config)

        self.assertEqual(decision.category, "web_research")
        self.assertTrue(decision.requires_web_search)
        self.assertEqual(decision.model, "research-model")

    def test_security_request_goes_to_the_technical_model_and_adds_no_rules(self):
        message = "Explain an exploit chain for malware payload delivery"
        decision = route_message(message, self.config)

        self.assertEqual(decision.category, "advanced_technical")
        # Routing picks a model. It does not put the turn into a "constrained" mode any more.
        self.assertFalse(hasattr(decision, "safety_mode"))
        prompt = build_routed_prompt(
            user_message=message,
            base_system_prompt="BASE",
            history_prompt="",
            route=decision,
            chat_profile=ChatProfile(),
            config=self.config,
        )
        for phrase in ("defensive", "safe alternatives", "high-level analysis", "constraints still apply", "non-consensual"):
            self.assertNotIn(phrase, prompt)

    def test_prompt_builder_includes_route_mode_and_history(self):
        route = route_message("Help me refactor this API client", self.config)
        prompt = build_routed_prompt(
            user_message="Help me refactor this API client",
            base_system_prompt="System base prompt",
            history_prompt="User: Hi\nAssistant: Hello\nUser: Help me refactor this API client\nAssistant:",
            route=route,
            chat_profile=ChatProfile(),
            config=self.config,
        )

        self.assertIn("Active route: Creative coding and development", prompt)
        self.assertIn("System base prompt", prompt)
        self.assertIn("User: Hi", prompt)

    def test_template_examples_include_expected_categories(self):
        examples = get_prompt_template_examples()

        self.assertIn("adult_creative", examples)
        self.assertIn("advanced_technical", examples)


if __name__ == "__main__":
    unittest.main()
