"""User-facing uncertainty notes and conservative rewrites."""

from __future__ import annotations

from typing import Any


def build_uncertainty_note(audit: dict[str, Any]) -> str:
    """Create a compact note when an answer needs grounding caveats."""

    confidence = audit.get("confidence", {})
    hallucination = audit.get("hallucination", {})
    speculation = audit.get("speculation", {})
    contradictions = audit.get("contradictions", {})
    source = audit.get("source_grounding", {})
    notes: list[str] = []
    level = confidence.get("level", "")

    if level in {"LOW CONFIDENCE", "SPECULATIVE", "FICTIONAL / UNKNOWN"}:
        notes.append(f"Confidence: {level}.")
    if source.get("status") == "ungrounded" and audit.get("claim_count", 0) >= 3:
        notes.append("No external source grounding was attached, so factual claims should be treated as unverified.")
    if hallucination.get("probability", 0) >= 0.45:
        notes.append("Hallucination risk is elevated; verify technical terms, citations, and exact claims before relying on them.")
    if speculation.get("category") not in {"established fact", None}:
        notes.append(f"Speculation label: {speculation.get('category')}.")
    if contradictions.get("contradictions"):
        notes.append("Potential contradiction detected: " + "; ".join(contradictions["contradictions"][:2]))

    if not notes:
        return ""
    return "\n\n**Reality check:** " + " ".join(notes)


def apply_grounding_note(answer: str, audit: dict[str, Any]) -> str:
    """Append a compact uncertainty note instead of silently rewriting content."""

    note = build_uncertainty_note(audit)
    if not note or note in answer:
        return answer
    return answer.rstrip() + note

