import unittest

from answer_quality_eval import score_answer_quality


class AnswerQualityEvalTests(unittest.TestCase):
    def test_casual_chat_answer_must_not_leak_stale_context(self):
        score = score_answer_quality(
            "sup",
            "casual_chat",
            "short",
            "Sup. You testing the vibe, or are we building something?",
        )

        self.assertTrue(score.directness)
        self.assertTrue(score.not_overexplaining)
        self.assertTrue(score.usefulness)

    def test_casual_chat_answer_fails_on_stale_package_context(self):
        score = score_answer_quality(
            "sup",
            "casual_chat",
            "short",
            "Your USPS package and Sour Patch Kids order are probably still on Amazon.",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)

    def test_casual_chat_answer_fails_when_too_robotic(self):
        score = score_answer_quality(
            "how are you?",
            "casual_chat",
            "short",
            "I'm good. What are we working on?",
        )

        self.assertFalse(score.usefulness)

    def test_social_check_in_fails_on_system_status_phrase(self):
        score = score_answer_quality(
            "how are you?",
            "casual_chat",
            "short",
            "Life is proceeding as expected.",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)
        self.assertIn("robotic social phrasing", score.notes)

    def test_social_check_in_fails_on_identity_disclaimer(self):
        score = score_answer_quality(
            "how are you?",
            "casual_chat",
            "short",
            "As a language model, I don't have emotions, but I can provide information.",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)

    def test_social_check_in_fails_on_unrequested_diagnostics_language(self):
        score = score_answer_quality(
            "how are you?",
            "casual_chat",
            "short",
            "Provider status is normal and diagnostics show no current model error.",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)

    def test_backchannel_fails_on_text_analysis_language(self):
        score = score_answer_quality(
            "that's good",
            "conversation_followup",
            "short",
            "The phrase means you approve. Do you have a specific question?",
            function="backchannel_acknowledgment",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)
        self.assertIn("unwanted backchannel analysis", score.notes)

    def test_backchannel_accepts_short_natural_continuity(self):
        score = score_answer_quality(
            "that's good",
            "conversation_followup",
            "short",
            "Yeah, that tracks. Want to keep moving?",
            function="backchannel_acknowledgment",
        )

        self.assertTrue(score.directness)
        self.assertTrue(score.not_overexplaining)
        self.assertTrue(score.usefulness)

    def test_casual_chat_answer_fails_on_stale_research_context(self):
        score = score_answer_quality(
            "not much. how are you?",
            "casual_chat",
            "short",
            "Stable complexity and emergence show up across physics, biology, and AI abstraction.",
        )

        self.assertFalse(score.directness)
        self.assertFalse(score.usefulness)

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

    def test_troubleshooting_answer_accepts_due_to_signal(self):
        score = score_answer_quality(
            "Why is my Streamlit app slow?",
            "troubleshooting",
            "surgeon",
            "Your Streamlit app is slow due to potential reruns and uncached expensive calls.",
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
