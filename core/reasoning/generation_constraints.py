"""Prompt constraints derived from epistemic feasibility."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from core.reasoning.feasibility_analyzer import FeasibilityReport
from core.reasoning.reality_model import RealityModel
from core.reasoning.speculative_boundary import boundary_language


@dataclass
class GenerationConstraints:
    epistemic_mode: str
    allow_procedural_framing: bool
    max_specificity: str
    instruction: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_epistemic_mode(reality: RealityModel, feasibility: FeasibilityReport, manual_mode: str = "auto") -> str:
    manual = (manual_mode or "auto").strip().lower()
    if reality.reality_status == "instruction_only":
        return "auto"
    if manual in {"strict_fact", "theoretical", "science_fiction", "research"}:
        return manual
    if reality.reality_status in {"fictional_construct", "fiction_or_roleplay"}:
        return "science_fiction"
    if reality.reality_status == "theoretical_science":
        return "theoretical"
    if feasibility.level in {"impossible", "unsupported", "unknown"}:
        return "strict_fact"
    return "auto"


def build_generation_constraints(
    reality: RealityModel,
    feasibility: FeasibilityReport,
    *,
    manual_mode: str = "auto",
) -> GenerationConstraints:
    mode = select_epistemic_mode(reality, feasibility, manual_mode)
    if reality.reality_status == "instruction_only":
        return GenerationConstraints(
            mode,
            True,
            "normal",
            (
                "Reality-first generation constraints:\n"
                "- This prompt is a direct response or formatting instruction, not a factual claim.\n"
                "- Follow the requested output directly unless it conflicts with higher-priority safety or tool limits.\n"
            ),
        )
    allow_procedure = feasibility.procedural_allowed and mode not in {"science_fiction"} and feasibility.score >= 0.5
    specificity = "normal" if allow_procedure else ("conceptual_only" if feasibility.level in {"theoretical_only", "unknown"} else "meta_explanatory")
    boundary = boundary_language(feasibility.level)
    instruction = (
        "Reality-first generation constraints:\n"
        f"- Epistemic mode: {mode}.\n"
        f"- Reality status: {reality.reality_status}; domain: {reality.domain}.\n"
        f"- Feasibility: {feasibility.level} ({feasibility.score}).\n"
        f"- Boundary: {boundary}\n"
        "- Before explaining HOW, establish whether the thing is real, verified, theoretical, fictional, unsupported, or impossible.\n"
    )
    if not allow_procedure and feasibility.procedural_requested:
        instruction += (
            "- Do not provide step-by-step instructions, component lists, blueprints, roadmaps, or fake implementation pathways for this request.\n"
            "- Use explanatory/meta framing instead: what is known, what is theoretical, what is fictional, and what cannot currently be built.\n"
        )
    if mode == "theoretical":
        instruction += "- Discuss theory only as theory; do not convert mathematical speculation into engineering instructions.\n"
    elif mode == "science_fiction":
        instruction += "- If creative speculation is useful, explicitly frame it as fiction/worldbuilding, not real technology.\n"
    elif mode == "strict_fact":
        instruction += "- Prefer strict factual boundaries and say when evidence is insufficient.\n"
    return GenerationConstraints(mode, allow_procedure, specificity, instruction)
