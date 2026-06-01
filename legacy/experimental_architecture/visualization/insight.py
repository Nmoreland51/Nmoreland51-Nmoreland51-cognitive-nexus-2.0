from __future__ import annotations

from typing import Any, Dict


class InsightRenderer:
    """Simple rendering helper for presenting emergent insights."""

    def render_summary(self, summary: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "type": "insight_summary",
            "summary": summary,
            "metadata": metadata or {},
        }

    def render_graph(self, nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, Any]:
        return {
            "type": "graph",
            "nodes": nodes,
            "edges": [
                {"source": source, "target": target} for source, target in edges
            ],
        }
