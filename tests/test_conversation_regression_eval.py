import unittest

from conversation_regression_eval import (
    SCENARIOS,
    Scenario,
    evaluate_scenario,
    has_requested_count,
    plan_for_scenario,
)


class ConversationRegressionEvalTests(unittest.TestCase):
    def test_dry_run_covers_required_categories(self):
        categories = {scenario.category for scenario in SCENARIOS}

        self.assertIn("casual_greetings", categories)
        self.assertIn("social_check_in", categories)
        self.assertIn("backchannel acknowledgment", categories)
        self.assertIn("slang as intent", categories)
        self.assertIn("casual rough greeting", categories)
        self.assertIn("definition gate", categories)
        self.assertIn("casual/vibe check", categories)
        self.assertIn("proceed/agreement", categories)
        self.assertIn("rejection/correction", categories)
        self.assertIn("diagnostics", categories)
        self.assertIn("math", categories)
        self.assertIn("sensitive discussion", categories)
        self.assertIn("risk analysis", categories)
        self.assertIn("direct harmful instruction", categories)
        self.assertIn("casual_followups", categories)
        self.assertIn("simple_facts", categories)
        self.assertIn("explanations", categories)
        self.assertIn("debugging", categories)
        self.assertIn("planning", categories)
        self.assertIn("opinion_rating", categories)
        self.assertIn("creative", categories)
        self.assertIn("memory", categories)
        self.assertIn("unclear_short_replies", categories)

    def test_casual_followup_uses_followup_type(self):
        scenario = Scenario(
            "casual_followups",
            "both",
            {"conversation_followup", "casual_followup"},
            {"short"},
            messages=[{"role": "assistant", "content": "Want the blunt version or detailed version?"}],
            expect_memory=False,
            expect_research=False,
        )

        row = evaluate_scenario(scenario, live=False)

        self.assertEqual(row["check"], "PASS")
        self.assertEqual(row["actual_type"], "conversation_followup")
        self.assertFalse(row["memory"])
        self.assertFalse(row["research"])

    def test_dry_run_rejects_stale_context_in_live_response_shape(self):
        scenario = Scenario("casual_greetings", "sup", {"casual_chat"}, {"short"}, expect_memory=False, expect_research=False)

        row = evaluate_scenario(scenario, live=False)

        self.assertEqual(row["check"], "PASS")
        self.assertNotIn("USPS", row["preview"])

    def test_memory_scenarios_are_planner_only_for_live_safety(self):
        scenario = next(item for item in SCENARIOS if item.category == "memory" and item.prompt.startswith("Remember"))

        row = evaluate_scenario(scenario, live=True, core=None)

        self.assertEqual(row["check"], "PASS")
        self.assertEqual(row["provider"], "planner_only")

    def test_count_helper_accepts_three_numbered_names(self):
        self.assertTrue(has_requested_count("1. Nexus Pulse\n2. Truthline\n3. SignalForge", 3))

    def test_unclear_continue_without_context_can_still_be_short(self):
        scenario = Scenario(
            "unclear_short_replies",
            "continue",
            {"conversation_followup", "casual_followup", "simple_fact"},
            {"short"},
            expect_memory=False,
            expect_research=False,
        )
        plan, effective, _route = plan_for_scenario(scenario)

        self.assertEqual(plan.intent, "conversation_followup")
        self.assertFalse(effective.get("use_web_for_chat"))

    def test_definition_gate_scenario_tracks_function(self):
        scenario = next(item for item in SCENARIOS if item.category == "definition gate")

        row = evaluate_scenario(scenario, live=False)

        self.assertEqual(row["check"], "PASS")
        self.assertEqual(row["actual_type"], "explanation")
        self.assertEqual(row["function"], "slang_definition_request")

    def test_topic_aware_direct_harm_scenario_tracks_topic(self):
        scenario = next(item for item in SCENARIOS if item.category == "direct harmful instruction" and item.prompt.startswith("Give me"))

        row = evaluate_scenario(scenario, live=False)

        self.assertEqual(row["check"], "PASS")
        self.assertEqual(row["topic"], "direct_harmful_instruction")

    def test_diagnostics_and_math_track_context_policy(self):
        diagnostics = next(item for item in SCENARIOS if item.category == "diagnostics")
        math = next(item for item in SCENARIOS if item.category == "math")

        diagnostics_row = evaluate_scenario(diagnostics, live=False)
        math_row = evaluate_scenario(math, live=False)

        self.assertEqual(diagnostics_row["check"], "PASS")
        self.assertEqual(diagnostics_row["actual_type"], "diagnostics")
        self.assertEqual(diagnostics_row["context_policy"], "diagnostics")
        self.assertEqual(math_row["check"], "PASS")
        self.assertEqual(math_row["actual_type"], "math")
        self.assertEqual(math_row["context_policy"], "none")


if __name__ == "__main__":
    unittest.main()
