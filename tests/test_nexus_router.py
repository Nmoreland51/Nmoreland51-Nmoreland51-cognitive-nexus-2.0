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

    def test_high_risk_technical_request_marks_constrained_mode(self):
        decision = route_message("Explain an exploit chain for malware payload delivery", self.config)

        self.assertEqual(decision.category, "advanced_technical")
        self.assertEqual(decision.safety_mode, "constrained")

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
