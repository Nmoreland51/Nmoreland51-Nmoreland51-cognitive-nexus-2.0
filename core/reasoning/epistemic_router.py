"""Reality-first routing and pre-generation epistemic assessment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from core.reasoning.evidence_classifier import EvidenceReport, classify_evidence
from core.reasoning.feasibility_analyzer import FeasibilityReport, analyze_feasibility
from core.reasoning.generation_constraints import GenerationConstraints, build_generation_constraints
from core.reasoning.ontology_validator import OntologyReport, validate_ontology
from core.reasoning.procedural_safety import ProceduralStructureReport, inspect_procedural_structure
from core.reasoning.reality_model import RealityModel, model_reality


@dataclass
class EpistemicAssessment:
    reality: RealityModel
    feasibility: FeasibilityReport
    evidence: EvidenceReport
    constraints: GenerationConstraints
    ontology: OntologyReport
    structural: ProceduralStructureReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "reality": self.reality.to_dict(),
            "feasibility": self.feasibility.to_dict(),
            "evidence": self.evidence.to_dict(),
            "constraints": self.constraints.to_dict(),
            "ontology": self.ontology.to_dict(),
            "structural": self.structural.to_dict(),
        }


def analyze_epistemic_request(
    user_message: str,
    *,
    route_category: str = "",
    source_count: int = 0,
    web_used: bool = False,
    rag_used: bool = False,
    tool_confirmed: bool = False,
    manual_mode: str = "auto",
) -> EpistemicAssessment:
    """Classify reality status and build generation constraints before drafting."""

    reality = model_reality(user_message, route_category)
    feasibility = analyze_feasibility(user_message, reality)
    evidence = classify_evidence(source_count=source_count, web_used=web_used, rag_used=rag_used, tool_confirmed=tool_confirmed)
    constraints = build_generation_constraints(reality, feasibility, manual_mode=manual_mode)
    ontology = validate_ontology(user_message, reality.reality_status)
    structural = inspect_procedural_structure(user_message)
    return EpistemicAssessment(reality, feasibility, evidence, constraints, ontology, structural)

