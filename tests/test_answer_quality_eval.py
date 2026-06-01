import unittest

from answer_quality_eval import score_answer_quality


class AnswerQualityEvalTests(unittest.TestCase):
    def test_simple_fact_answer_must_stay_direct_and_short(self):
        score = score_answer_quality(
            "What is Cognitive Nexus?",
            "simple_fact",
            "short",
            "Cognitive Nexus is a local-first AI command center for chat, memory, research, and diagnostics.",
        )

        self.assertTrue(score.directness)
        self.assertTrue(score.not_overexplaining)
        self.assertTrue(score.usefulness)

    def test_internal_planner_language_fails_directness(self):
        score = score_answer_quality(
            "What is Cognitive Nexus?",
            "simple_fact",
            "short",
            "Adaptive response plan: Intent: simple_fact. Cognitive Nexus is a local AI tool.",
        )

        self.assertFalse(score.directness)

    def test_debugging_answer_needs_next_step_signal(self):
        score = score_answer_quality(
            "Fix this import error: ModuleNotFoundError: core.model",
            "debugging",
            "surgeon",
            "Likely cause: the old core.model import points at a removed module. Next step: search imports and replace it with the current core.reality_grounding path.",
        )

        self.assertTrue(score.usefulness)

    def test_planning_answer_needs_steps_or_phases(self):
        score = score_answer_quality(
            "Make me a plan to improve this project.",
            "project_planning",
            "deep",
            "1. Stabilize startup.\n2. Improve answer quality.\n3. Package the demo.",
        )

        self.assertTrue(score.usefulness)

    def test_rating_answer_needs_score_or_verdict(self):
        score = score_answer_quality(
            "Rate my AI compared to ChatGPT.",
            "opinion_rating",
            "standard",
            "Verdict: 6.5/10 right now. Strong concept, weaker polish and reliability.",
        )

        self.assertTrue(score.usefulness)

    def test_dry_run_catches_overbroad_headline_plan(self):
        score = score_answer_quality(
            "Write a short website headline for Cognitive Nexus.",
            "creative",
            "deep",
            "[dry run]",
            dry_run=True,
            profile={"style": "Be vivid and useful."},
        )

        self.assertFalse(score.not_overexplaining)


if __name__ == "__main__":
    unittest.main()
