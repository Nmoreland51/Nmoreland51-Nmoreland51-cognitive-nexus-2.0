import tempfile
import unittest
from pathlib import Path

from modules.response_planner import (
    ResponsePreferences,
    analyze_intent_cached,
    apply_auto_precision_settings,
    classify_request,
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
        self.assertIn(result["intent"], {"debugging", "coding_help"})

    def test_classify_request_uses_auto_precision_taxonomy(self):
        result = classify_request("Rate this portfolio project and give me the next upgrade path")

        self.assertEqual(result["intent"], "opinion_rating")
        self.assertEqual(result["request_type"], "opinion_rating")

    def test_short_mode_for_brief_requests(self):
        plan = plan_response(
            user_message="What is Streamlit?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.intent, "simple_fact")
        self.assertEqual(plan.mode, "short")
        self.assertLessEqual(plan.max_tokens, 850)

    def test_surgeon_mode_for_coding_route(self):
        plan = plan_response(
            user_message="Please fix this NameError without rewriting everything.",
            messages=[],
            route_category="coding_development",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 2,
                "reasoning_depth": 2,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.mode, "surgeon")
        self.assertIn("preserve critical details", plan.instructions)

    def test_auto_precision_overrides_manual_mode_when_enabled(self):
        plan = plan_response(
            user_message="What is Streamlit?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "deep",
                "auto_precision_mode": True,
                "verbosity_level": 3,
                "reasoning_depth": 4,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.mode, "short")

    def test_manual_mode_override_when_auto_precision_off(self):
        plan = plan_response(
            user_message="Explain this architecture.",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "research",
                "auto_precision_mode": False,
                "verbosity_level": 3,
                "reasoning_depth": 4,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.mode, "research")
        self.assertGreaterEqual(plan.max_tokens, 700)

    def test_research_request_uses_research_profile(self):
        plan = plan_response(
            user_message="Research the latest local AI hallucination controls with sources.",
            messages=[],
            route_category="web_research",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.intent, "research")
        self.assertEqual(plan.mode, "research")
        self.assertTrue(plan.diagnostics["auto_precision_mode"])

    def test_auto_precision_settings_choose_memory_and_research(self):
        simple = apply_auto_precision_settings({"auto_precision_mode": True}, "simple_fact")
        research = apply_auto_precision_settings({"auto_precision_mode": True}, "research")
        reality = apply_auto_precision_settings({"auto_precision_mode": True}, "reality_check")
        debugging = apply_auto_precision_settings({"auto_precision_mode": True}, "debugging")

        self.assertFalse(simple["use_memory"])
        self.assertFalse(simple["use_web_for_chat"])
        self.assertFalse(simple["show_perf_timings"])
        self.assertTrue(research["use_memory"])
        self.assertTrue(research["use_web_for_chat"])
        self.assertTrue(reality["enable_reality_research_agent"])
        self.assertTrue(reality["enable_bloodhound_search"])
        self.assertTrue(reality["show_perf_timings"])
        self.assertTrue(debugging["show_perf_timings"])

    def test_troubleshooting_prompt_uses_technical_triage_mode(self):
        plan = plan_response(
            user_message="Why is my Streamlit app slow?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertIn(plan.intent, {"troubleshooting", "debugging"})
        self.assertEqual(plan.mode, "surgeon")
        self.assertTrue(plan.diagnostics["auto_precision_profile"]["diagnostics"])

    def test_creative_short_copy_is_not_mistaken_for_simple_fact(self):
        plan = plan_response(
            user_message="Write a short website headline",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "creative")
        self.assertEqual(plan.mode, "deep")

    def test_last_test_run_question_uses_debug_memory_profile(self):
        plan = plan_response(
            user_message="What broke in my last test run?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertIn(plan.intent, {"debugging", "troubleshooting"})
        self.assertEqual(plan.mode, "surgeon")
        self.assertTrue(plan.diagnostics["auto_precision_profile"]["use_memory"])

    def test_opinion_rating_prompt_uses_blunt_structured_profile(self):
        plan = plan_response(
            user_message="Rate my AI compared to ChatGPT",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "opinion_rating")
        self.assertEqual(plan.mode, "standard")
        self.assertIn("blunt score", plan.instructions)

    def test_project_planning_prompt_uses_phased_profile(self):
        plan = plan_response(
            user_message="Make me a plan to improve this project",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "project_planning")
        self.assertEqual(plan.mode, "deep")
        self.assertIn("Prioritize the next move", plan.instructions)

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
            settings={"response_mode": "deep", "auto_precision_mode": False, "verbosity_level": 2, "reasoning_depth": 3},
        )
        completion = validate_response_against_plan("Too short.", plan)
        self.assertEqual(completion["length_status"], "under_target")


if __name__ == "__main__":
    unittest.main()
