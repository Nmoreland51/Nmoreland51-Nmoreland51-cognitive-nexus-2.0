"""Reality grounding and hallucination-control pipeline."""

from core.reality_grounding.answer_auditor import RealityAudit, audit_answer

__all__ = ["RealityAudit", "audit_answer"]

