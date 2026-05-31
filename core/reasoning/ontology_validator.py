"""Semantic consistency checks for theory, fiction, and engineering categories."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OntologyReport:
    violations: list[str] = field(default_factory=list)
    risk: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_ontology(text: str, reality_status: str) -> OntologyReport:
    lowered = (text or "").lower()
    violations: list[str] = []
    if reality_status in {"fictional_construct", "fiction_or_roleplay"} and re.search(r"\b(engineering component|implementation pathway|buildable|deployable)\b", lowered):
        violations.append("Fictional concept is being framed as an engineering component.")
    if reality_status == "theoretical_science" and re.search(r"\b(step-by-step|parts list|prototype|manufacture|blueprint)\b", lowered):
        violations.append("Theoretical concept is being framed as a practical build process.")
    if reality_status == "pseudoscience_or_unsupported" and re.search(r"\bproven|clinically|scientifically established|guaranteed\b", lowered):
        violations.append("Unsupported concept is being framed as proven.")
    return OntologyReport(violations=violations, risk=round(min(1.0, len(violations) * 0.35), 3))

