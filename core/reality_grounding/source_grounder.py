"""Source grounding status estimation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SourceGroundingReport:
    status: str
    source_count: int = 0
    web_used: bool = False
    rag_used: bool = False
    tool_confirmed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_source_grounding(
    *,
    source_count: int = 0,
    web_used: bool = False,
    rag_used: bool = False,
    tool_confirmed: bool = False,
) -> SourceGroundingReport:
    if tool_confirmed and source_count > 0:
        return SourceGroundingReport("verified", source_count, web_used, rag_used, tool_confirmed, "Tool output and sources were available.")
    if web_used and source_count > 0:
        return SourceGroundingReport("source-grounded", source_count, web_used, rag_used, tool_confirmed, "Web/search sources were available.")
    if rag_used:
        return SourceGroundingReport("memory-grounded", source_count, web_used, rag_used, tool_confirmed, "Local memory or knowledge context was used.")
    if tool_confirmed:
        return SourceGroundingReport("tool-confirmed", source_count, web_used, rag_used, tool_confirmed, "Local tool execution confirmed part of the answer.")
    return SourceGroundingReport("ungrounded", source_count, web_used, rag_used, tool_confirmed, "No external grounding was attached to this answer.")

