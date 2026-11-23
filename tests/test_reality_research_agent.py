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


class ClaimCheckTests(unittest.TestCase):
    """The verdict must come from passages that address the claim, not from source counts."""

    def _source(self, url, text, trust="Medium"):
        return agent.SourceRecord(
            title=f"Page at {url}",
            url=url,
            source=agent.get_domain(url),
            snippet=text,
            excerpt=text,
            trust_label=trust,
            trust_score={"High": 0.8, "Medium": 0.55, "Low": 0.3}[trust],
        )

    def _verdict(self, query, sources, **kwargs):
        claims = agent.extract_claim_records(sources)
        return agent.determine_verdict(query, sources, claims, agent.detect_claim_contradictions(claims), **kwargs)

    def test_trusted_sources_that_do_not_address_the_claim_prove_nothing(self):
        # Two high-trust sources, claims extracted, no contradictions: this used to be "TRUE" at 0.8.
        sources = [
            self._source("https://www.nasa.gov/artemis", "NASA launched the Artemis I mission in November 2022.", "High"),
            self._source("https://www.mit.edu/geology", "MIT researchers have studied lunar geology for decades.", "High"),
        ]

        result = self._verdict("verify that the moon landing was faked", sources)

        self.assertEqual(result["verdict"], "UNSUPPORTED")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["evidence"], [])
        self.assertIn("missing evidence, not evidence that the claim is false", result["why"])

    def test_two_independent_supporting_passages_are_likely_true_never_true(self):
        sources = [
            self._source("https://www.nasa.gov/apollo", "The Apollo 11 Moon landing happened on July 20, 1969.", "High"),
            self._source("https://history.example/apollo", "Apollo 11's Moon landing happened in 1969 and was watched worldwide."),
        ]

        result = self._verdict("did the Apollo 11 moon landing happen?", sources)

        self.assertEqual(result["verdict"], "LIKELY TRUE")
        self.assertEqual(result["evidence_strength"], "Moderate")
        self.assertEqual([item.stance for item in result["evidence"]], ["supports", "supports"])
        self.assertIn("July 20, 1969", result["evidence"][0].passage)
        self.assertEqual(len(result["supporting"]), 2)

    def test_debunking_passages_contradict_the_claim(self):
        sources = [
            self._source("https://www.nasa.gov/facts", "Claims that the Moon landing was faked have been thoroughly debunked.", "High"),
            self._source("https://science.example/moon", "The Moon landing was not faked; independent evidence confirms it."),
        ]

        result = self._verdict("verify that the moon landing was faked", sources)

        self.assertEqual(result["verdict"], "LIKELY FALSE")
        self.assertEqual({item.stance for item in result["evidence"]}, {"contradicts"})
        self.assertEqual(result["supporting"], [])

    def test_negated_claim_is_supported_by_refutation_wording(self):
        sources = [
            self._source("https://www.cdc.gov/vaccines", "There is no evidence that vaccines cause autism.", "High"),
            self._source("https://health.example/myths", "The myth that vaccines cause autism has been debunked."),
        ]

        result = self._verdict("is it true that vaccines do not cause autism", sources)

        self.assertEqual(result["claim"], "vaccines do not cause autism")
        self.assertEqual(result["verdict"], "LIKELY TRUE")

    def test_supporting_and_contradicting_passages_are_mixed(self):
        sources = [
            self._source("https://a.example/1", "The Moon landing was faked in a studio."),
            self._source("https://b.example/2", "The Moon landing was not faked."),
        ]

        result = self._verdict("verify that the moon landing was faked", sources)

        self.assertEqual(result["verdict"], "MIXED / CONFLICTING")
        self.assertEqual(result["evidence_strength"], "Conflicting")

    def test_same_site_and_copied_passages_count_once(self):
        sources = [
            self._source("https://a.example/1", "The Moon landing was faked in a studio."),
            self._source("https://a.example/2", "Experts agree the Moon landing was faked."),
            self._source("https://b.example/copy", "The Moon landing was faked in a studio."),
        ]

        result = self._verdict("verify that the moon landing was faked", sources)

        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["verdict"], "WEAKLY SUPPORTED")

    def test_reported_beliefs_and_questions_are_not_support(self):
        sources = [
            self._source("https://a.example/1", "Some people believe the Moon landing was faked."),
            self._source("https://b.example/2", "Was the Moon landing faked?"),
        ]

        result = self._verdict("verify that the moon landing was faked", sources)

        self.assertEqual({item.stance for item in result["evidence"]}, {"mentions"})
        self.assertEqual(result["verdict"], "UNSUPPORTED")
        self.assertIn("none clearly affirms or denies", result["why"])

    def test_only_real_verification_requests_get_a_verdict(self):
        sources = [self._source("https://a.example/1", "The candidate said taxes would fall next year.")]

        for query in ("what did the candidate say about taxes", "research wasps and candidates", "do a deep dive on taxes"):
            self.assertEqual(self._verdict(query, sources)["verdict"], "", query)
        self.assertTrue(agent.is_verification_request("fact-check this claim: taxes fell"))
        self.assertTrue(agent.is_verification_request("Do vaccines cause autism?"))
        # The chat command strips "verify", so the caller says it is a claim check.
        self.assertNotEqual(self._verdict("the candidate said taxes would fall", sources, verify=True)["verdict"], "")

    def test_physics_defying_topic_adds_a_note_instead_of_overriding_the_evidence(self):
        sources = [
            self._source("https://www.nasa.gov/relativity", "Einstein said nothing travels faster than light in a vacuum.", "High"),
            self._source("https://physics.example/sr", "Einstein said that nothing travels faster than light."),
        ]

        result = self._verdict("verify that Einstein said nothing travels faster than light", sources)

        self.assertEqual(result["verdict"], "LIKELY TRUE")
        self.assertTrue(any("physics" in note for note in result["uncertainty"]))

    def _run(self, **kwargs):
        payload = {
            "ranked_results": [
                {
                    "title": "Apollo 11 mission overview",
                    "url": "https://www.nasa.gov/apollo11",
                    "source": "nasa.gov",
                    "snippet": "Claims that the Moon landing was faked have been thoroughly debunked by independent evidence.",
                    "excerpt": "Claims that the Moon landing was faked have been thoroughly debunked by independent evidence.",
                    "match_strength": "High",
                    "score": 9.0,
                    "fetched": True,
                },
                {
                    "title": "Moon landing evidence",
                    "url": "https://science.example/moon",
                    "source": "science.example",
                    "snippet": "The Moon landing was not faked; retroreflectors left on the surface are still used today.",
                    "excerpt": "The Moon landing was not faked; retroreflectors left on the surface are still used today.",
                    "match_strength": "High",
                    "score": 8.0,
                    "fetched": True,
                },
            ],
            "final_answer": "Found sources.",
            "coverage": {},
            "errors": ["Search failed for 'moon landing faked site:reddit.com': rate limited"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(agent, "REPORT_DIR", Path(temp_dir)):
                return agent.run_reality_research(
                    agent.ResearchRequest(query="the moon landing was faked", save_to_memory=False, verify_claim=True),
                    search_runner=lambda query, **_kwargs: payload,
                    **kwargs,
                )

    def test_report_quotes_the_passages_and_admits_incomplete_coverage(self):
        report = self._run()
        markdown = report.to_markdown()

        self.assertEqual(report.verdict, "LIKELY FALSE")
        self.assertTrue(report.final_answer.startswith("Claim check: LIKELY FALSE (evidence: moderate)."))
        self.assertIn("## Claim Check", markdown)
        self.assertIn("thoroughly debunked", markdown)
        self.assertIn(agent.CLAIM_CHECK_CAVEAT, markdown)
        self.assertNotIn("Confidence:", markdown)
        self.assertTrue(any("coverage is incomplete" in note for note in report.uncertainty_notes))
        self.assertEqual(report.to_dict()["claim_evidence"][0]["stance"], "contradicts")

    def test_claim_check_survives_failed_ai_synthesis(self):
        def broken_ai(_prompt):
            raise RuntimeError("model offline")

        report = self._run(ai_callback=broken_ai)

        self.assertTrue(report.final_answer.startswith("Claim check: LIKELY FALSE"))
        self.assertTrue(any("AI synthesis failed" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
