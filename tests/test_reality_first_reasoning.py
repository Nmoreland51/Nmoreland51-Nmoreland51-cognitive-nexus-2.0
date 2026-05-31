import unittest

from core.reasoning import analyze_epistemic_request
from core.reasoning.ontology_validator import validate_ontology
from core.reasoning.procedural_safety import inspect_procedural_structure
from core.reasoning.reality_model import model_reality


class RealityFirstReasoningTests(unittest.TestCase):
    def test_time_machine_blocks_procedural_fiction(self):
        assessment = analyze_epistemic_request("How do I build a time machine with temporal stabilizers?")
        self.assertEqual(assessment.reality.reality_status, "fictional_construct")
        self.assertFalse(assessment.feasibility.procedural_allowed)
        self.assertIn("Do not provide step-by-step", assessment.constraints.instruction)

    def test_perpetual_motion_is_impossible(self):
        assessment = analyze_epistemic_request("Give me steps to build a perpetual motion machine.")
        self.assertEqual(assessment.reality.reality_status, "impossible_under_current_science")
        self.assertEqual(assessment.feasibility.level, "impossible")
        self.assertFalse(assessment.constraints.allow_procedural_framing)

    def test_wormholes_are_theoretical_not_engineering(self):
        assessment = analyze_epistemic_request("How would engineers build a wormhole prototype?")
        self.assertEqual(assessment.reality.reality_status, "theoretical_science")
        self.assertEqual(assessment.constraints.epistemic_mode, "theoretical")
        self.assertFalse(assessment.feasibility.procedural_allowed)

    def test_established_coding_can_be_procedural(self):
        assessment = analyze_epistemic_request("How do I implement a Streamlit API client in Python?")
        self.assertEqual(assessment.reality.reality_status, "established_or_practical")
        self.assertTrue(assessment.feasibility.procedural_allowed)

    def test_direct_response_instruction_is_not_fact_checked_as_unknown_reality(self):
        assessment = analyze_epistemic_request(
            "Reply with exactly: Core stability check passed.",
            manual_mode="strict_fact",
        )

        self.assertEqual(assessment.reality.reality_status, "instruction_only")
        self.assertEqual(assessment.constraints.epistemic_mode, "auto")
        self.assertTrue(assessment.constraints.allow_procedural_framing)
        self.assertIn("direct response", assessment.constraints.instruction)
        self.assertNotIn("evidence is insufficient", assessment.constraints.instruction)

    def test_pseudoscience_is_unsupported(self):
        reality = model_reality("Explain the engineering behind scalar wave biofield healing.")
        self.assertEqual(reality.reality_status, "pseudoscience_or_unsupported")

    def test_structural_hallucination_detects_fake_components(self):
        report = inspect_procedural_structure(
            "Components: temporal core, resonance field, dimensional phase array."
        )
        self.assertGreater(report.structural_risk, 0.3)
        self.assertTrue(report.fake_component_markers)

    def test_ontology_flags_fiction_as_engineering(self):
        report = validate_ontology("This is a buildable engineering component.", "fictional_construct")
        self.assertTrue(report.violations)


if __name__ == "__main__":
    unittest.main()
