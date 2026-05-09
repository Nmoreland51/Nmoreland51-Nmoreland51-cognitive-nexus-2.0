import tempfile
import unittest
from pathlib import Path

from modules.response_planner import (
    ResponsePreferences,
    analyze_intent_cached,
    estimate_tokens,
    plan_response,
    update_response_preferences,
    validate_response_against_plan,
)


class TestResponsePlanner(unittest.TestCase):
    def test_estimate_tokens_is_stable(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertGreaterEqual(estimate_tokens("hello " * 20), 20)

    def test_detects_coding_debug_intent(self):
        result = analyze_intent_cached("Fix this Python traceback in my Streamlit app")
        self.assertIn(result["intent"], {"technical_debugging", "coding_request"})

    def test_short_mode_for_brief_requests(self):
        plan = plan_response(
            user_message="What is Streamlit?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.mode, "short")
        self.assertLessEqual(plan.max_tokens, 850)

    def test_surgeon_mode_for_coding_route(self):
        plan = plan_response(
            user_message="Please fix this NameError without rewriting everything.",
            messages=[],
            route_category="coding_development",
            settings={
                "response_mode": "auto",
                "verbosity_level": 2,
                "reasoning_depth": 2,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.mode, "surgeon")
        self.assertIn("preserve critical details", plan.instructions)

    def test_manual_mode_override(self):
        plan = plan_response(
            user_message="Explain this architecture.",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "research",
                "verbosity_level": 3,
                "reasoning_depth": 4,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.mode, "research")
        self.assertGreaterEqual(plan.max_tokens, 700)

    def test_preference_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "response_preferences.json"
            prefs = update_response_preferences("Keep it short and no fluff.", ResponsePreferences(), path)
            self.assertGreater(prefs.weights["brevity"], 0)
            self.assertGreater(prefs.weights["low_fluff"], 0)
            self.assertTrue(path.exists())

    def test_completion_validation_flags_length(self):
        plan = plan_response(
            user_message="Explain in detail how this works.",
            messages=[],
            route_category="standard_conversation",
            settings={"response_mode": "deep", "verbosity_level": 2, "reasoning_depth": 3},
        )
        completion = validate_response_against_plan("Too short.", plan)
        self.assertEqual(completion["length_status"], "under_target")


if __name__ == "__main__":
    unittest.main()
