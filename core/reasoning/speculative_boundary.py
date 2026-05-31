"""Natural boundary language for low-feasibility concepts."""

from __future__ import annotations


BOUNDARY_LINES = {
    "fictional": "This concept is best treated as fiction or worldbuilding, not real engineering.",
    "impossible": "No verified method exists, and the request conflicts with established scientific constraints.",
    "theoretical_only": "This remains theoretical; no experimentally validated implementation pathway exists.",
    "unsupported": "This is speculative or unsupported rather than established science.",
    "unknown": "The claim cannot be verified from the available context, so avoid treating it as settled fact.",
}


def boundary_language(feasibility_level: str) -> str:
    return BOUNDARY_LINES.get(feasibility_level, "Keep factual claims bounded to what is established or evidenced.")

