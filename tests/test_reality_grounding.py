import unittest

from core.reality_grounding import audit_answer
from core.reality_grounding.claim_validator import extract_claims
from core.reality_grounding.contradiction_checker import check_contradictions
from core.reality_grounding.hallucination_detector import detect_hallucination_risk
from core.reality_grounding.speculation_classifier import classify_speculation


class RealityGroundingTests(unittest.TestCase):
    def test_extracts_factual_claims(self):
        claims = extract_claims("Python 3.12 was released in 2023. This package imports streamlit and requests.")
        self.assertGreaterEqual(len(claims), 2)
        self.assertTrue(any(claim.requires_evidence for claim in claims))

    def test_flags_fake_science_jargon(self):
        report = detect_hallucination_risk(
            "The temporal resonance stabilizer uses a neural entropy manifold and quantum foam synchronization array."
        )
        self.assertGreater(report.probability, 0.4)
        self.assertTrue(report.signals)

    def test_classifies_science_fiction(self):
        report = classify_speculation("A wormhole stabilizer is a science fiction device, not current engineering.")
        self.assertEqual(report.category, "science fiction")

    def test_detects_contradiction(self):
        report = check_contradictions(
            "Faster-than-light travel is impossible under relativity. Standard engines can exceed light speed."
        )
        self.assertTrue(report.contradictions)

    def test_audit_adds_grounding_note_for_ungrounded_claims(self):
        answer = (
            "The Quantum Foam Synchronization API was released in 2026 and is guaranteed to work. "
            "It requires a temporal resonance stabilizer."
        )
        audit = audit_answer(answer, source_count=0, web_used=False, tool_confirmed=False)
        self.assertIn("Reality check", audit.cleaned_answer)
        self.assertGreater(audit.hallucination.probability, 0.3)
        self.assertIn(audit.confidence.level, {"LOW CONFIDENCE", "SPECULATIVE", "FICTIONAL / UNKNOWN", "MODERATE CONFIDENCE"})

    def test_source_grounding_raises_confidence(self):
        audit = audit_answer(
            "The page says Cognitive Nexus has Bloodhound Search Mode.",
            source_count=3,
            web_used=True,
            tool_confirmed=True,
        )
        self.assertIn(audit.source_grounding.status, {"verified", "source-grounded"})


if __name__ == "__main__":
    unittest.main()
