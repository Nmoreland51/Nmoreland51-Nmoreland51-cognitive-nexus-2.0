"""Evidence-quality classification for pre-generation constraints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class EvidenceReport:
    quality: str
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_evidence(*, source_count: int = 0, web_used: bool = False, rag_used: bool = False, tool_confirmed: bool = False) -> EvidenceReport:
    if tool_confirmed and source_count >= 2:
        return EvidenceReport("verified_sources", 0.9, "Tool-confirmed answer with multiple sources.")
    if web_used and source_count >= 2:
        return EvidenceReport("source_grounded", 0.76, "Web/search evidence is available.")
    if rag_used:
        return EvidenceReport("local_memory", 0.58, "Local memory or RAG evidence is available.")
    if source_count:
        return EvidenceReport("limited_sources", 0.5, "Some sources are available but grounding is limited.")
    return EvidenceReport("ungrounded", 0.18, "No source evidence is attached before generation.")

