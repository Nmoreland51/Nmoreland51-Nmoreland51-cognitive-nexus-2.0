"""Central answer audit pipeline for Cognitive Nexus."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.reality_grounding.claim_validator import Claim, extract_claims
from core.reality_grounding.confidence_estimator import ConfidenceReport, estimate_confidence
from core.reality_grounding.contradiction_checker import ContradictionReport, check_contradictions
from core.reality_grounding.hallucination_detector import HallucinationReport, detect_hallucination_risk
from core.reality_grounding.source_grounder import SourceGroundingReport, assess_source_grounding
from core.reality_grounding.speculation_classifier import SpeculationReport, classify_speculation
from core.reality_grounding.uncertainty_handler import apply_grounding_note


PATTERN_MEMORY_FILE = Path("data/reality_grounding_patterns.json")


@dataclass
class RealityAudit:
    label: str
    confidence: ConfidenceReport
    hallucination: HallucinationReport
    speculation: SpeculationReport
    source_grounding: SourceGroundingReport
    contradictions: ContradictionReport
    claims: list[Claim] = field(default_factory=list)
    cleaned_answer: str = ""
    added_note: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence.to_dict(),
            "hallucination": self.hallucination.to_dict(),
            "speculation": self.speculation.to_dict(),
            "source_grounding": self.source_grounding.to_dict(),
            "contradictions": self.contradictions.to_dict(),
            "claims": [claim.to_dict() for claim in self.claims],
            "claim_count": len(self.claims),
            "added_note": self.added_note,
        }


def _remember_patterns(audit: RealityAudit) -> None:
    try:
        PATTERN_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"patterns": {}, "updated_at": datetime.now().isoformat()}
        if PATTERN_MEMORY_FILE.exists():
            loaded = json.loads(PATTERN_MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload["patterns"] = loaded.get("patterns", {}) if isinstance(loaded.get("patterns"), dict) else {}
        patterns = payload["patterns"]
        for signal in audit.hallucination.signals:
            key = f"{signal.signal_type}:{signal.text}"[:160]
            patterns[key] = int(patterns.get(key, 0)) + 1
        PATTERN_MEMORY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def audit_answer(
    answer: str,
    *,
    label: str = "chat",
    route_category: str = "",
    source_count: int = 0,
    web_used: bool = False,
    rag_used: bool = False,
    tool_confirmed: bool = False,
    apply_note: bool = True,
) -> RealityAudit:
    """Run claim extraction, hallucination analysis, grounding, and confidence scoring."""

    claims = list(extract_claims(answer or ""))
    hallucination = detect_hallucination_risk(answer or "", source_count=source_count, tool_confirmed=tool_confirmed)
    speculation = classify_speculation(answer or "", route_category=route_category)
    source_grounding = assess_source_grounding(
        source_count=source_count,
        web_used=web_used,
        rag_used=rag_used,
        tool_confirmed=tool_confirmed,
    )
    contradictions = check_contradictions(answer or "")
    confidence = estimate_confidence(
        source_status=source_grounding.status,
        source_count=source_count,
        hallucination_probability=hallucination.probability,
        contradiction_risk=contradictions.risk,
        speculation_probability=speculation.probability,
        claim_count=len(claims),
    )
    audit = RealityAudit(
        label=label,
        confidence=confidence,
        hallucination=hallucination,
        speculation=speculation,
        source_grounding=source_grounding,
        contradictions=contradictions,
        claims=claims,
        cleaned_answer=answer or "",
    )
    if apply_note:
        cleaned = apply_grounding_note(answer or "", audit.to_dict())
        audit.cleaned_answer = cleaned
        audit.added_note = cleaned != (answer or "")
    if hallucination.signals:
        _remember_patterns(audit)
    return audit

