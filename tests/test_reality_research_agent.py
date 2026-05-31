import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import reality_research_agent as agent


class RealityResearchAgentTests(unittest.TestCase):
    def _payload(self):
        return {
            "ranked_results": [
                {
                    "title": "Cognitive Nexus Truth Tracking",
                    "url": "https://example.edu/nexus",
                    "source": "example.edu",
                    "source_type": "public_web",
                    "snippet": "Cognitive Nexus is a reality-first research system.",
                    "excerpt": "Cognitive Nexus is a reality-first research system. It extracts claims and verifies sources.",
                    "match_strength": "High",
                    "score": 9.2,
                    "fetched": True,
                    "why_it_matters": "Exact match with source text.",
                },
                {
                    "title": "Duplicate Cognitive Nexus Truth Tracking",
                    "url": "https://example.edu/nexus?utm_source=test",
                    "source": "example.edu",
                    "source_type": "public_web",
                    "snippet": "Duplicate result.",
                    "excerpt": "Duplicate result.",
                    "match_strength": "Low",
                    "score": 2.0,
                    "fetched": False,
                },
            ],
            "summary": "Found sources.",
            "final_answer": "Found sources.",
            "coverage": {"queries_tried": ["Cognitive Nexus"], "duplicates_removed": 0},
            "errors": [],
        }

    def test_detects_research_chat_commands(self):
        self.assertEqual(agent.detect_reality_research_query("research this deeply: AI truth"), "AI truth")
        self.assertEqual(agent.detect_reality_research_query("verify the moon landing"), "the moon landing")
        self.assertEqual(agent.detect_reality_research_query("search for Cognitive Nexus"), "Cognitive Nexus")
        self.assertEqual(agent.detect_reality_research_query("normal chat"), "")

    def test_source_trust_scores_exact_source_rich_results(self):
        source = agent.score_source_trust(self._payload()["ranked_results"][0], "Cognitive Nexus")
        self.assertEqual(source.match_strength, "High")
        self.assertGreaterEqual(source.trust_score, 0.6)
        self.assertIn(source.trust_label, {"Medium", "High"})

    def test_dedupes_urls(self):
        sources = [agent.score_source_trust(item, "Cognitive Nexus") for item in self._payload()["ranked_results"]]
        deduped = agent.dedupe_sources(sources)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].match_strength, "High")

    def test_empty_query_returns_graceful_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(agent, "REPORT_DIR", Path(temp_dir)):
                report = agent.run_reality_research(agent.ResearchRequest(query="", save_to_memory=False))
        self.assertIn("No research query", report.final_answer)
        self.assertTrue(report.errors)

    def test_run_research_saves_json_and_markdown(self):
        def fake_runner(query, **_kwargs):
            return self._payload()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(agent, "REPORT_DIR", Path(temp_dir)):
                report = agent.run_reality_research(
                    agent.ResearchRequest(query="Cognitive Nexus", save_to_memory=False, save_report=True),
                    search_runner=fake_runner,
                )
                self.assertTrue(report.sources)
                self.assertTrue(report.claims)
                self.assertTrue(Path(report.saved_paths["json"]).exists())
                self.assertTrue(Path(report.saved_paths["markdown"]).exists())

    def test_contradiction_detection_separates_possible_conflicts(self):
        claims = [
            agent.ClaimRecord("The system has no evidence for source trust.", "https://a.test", "A", source_trust=0.7),
            agent.ClaimRecord("The system has proven evidence for source trust.", "https://b.test", "B", source_trust=0.7),
        ]
        contradictions = agent.detect_claim_contradictions(claims)
        self.assertTrue(contradictions)
        self.assertEqual(contradictions[0].severity, "Medium")


if __name__ == "__main__":
    unittest.main()
