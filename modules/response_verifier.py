"""Lightweight response verification and uncertainty logging."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.nexus_config import LOG_DIR, ensure_runtime_dirs


UNCERTAINTY_PATTERNS = [
    r"\bprobably\b",
    r"\bmight\b",
    r"\bmaybe\b",
    r"\bI assume\b",
    r"\bI guess\b",
    r"\blikely\b",
]

SUCCESS_CLAIM_PATTERNS = [
    r"\bI (fixed|created|updated|deleted|pushed|installed|ran)\b",
    r"\b(successfully|completed|verified)\b",
]


@dataclass
class VerificationResult:
    """Verification metadata for one generated response."""

    risk_level: str = "low"
    issues: list[str] = field(default_factory=list)
    suggested_note: str = ""
    source_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_response(
    answer: str,
    *,
    source_count: int = 0,
    tool_confirmed: bool = False,
    web_used: bool = False,
) -> VerificationResult:
    """Flag unsupported confidence without calling another model."""

    issues: list[str] = []
    lowered = answer.lower()
    if web_used and source_count == 0:
        issues.append("Web/current-info answer did not include sources.")
    if re.search("|".join(UNCERTAINTY_PATTERNS), answer, flags=re.IGNORECASE):
        issues.append("Answer contains uncertainty language.")
    if not tool_confirmed and re.search("|".join(SUCCESS_CLAIM_PATTERNS), answer, flags=re.IGNORECASE):
        issues.append("Answer may imply completed tool work without confirmation.")
    if "as of" in lowered and source_count == 0:
        issues.append("Time-sensitive phrasing appears without a cited source.")

    risk_level = "low"
    if len(issues) >= 2:
        risk_level = "medium"
    if web_used and source_count == 0:
        risk_level = "high"

    suggested_note = ""
    if issues:
        suggested_note = "Some claims may need verification; check sources or local logs before treating them as final."

    return VerificationResult(
        risk_level=risk_level,
        issues=issues,
        suggested_note=suggested_note,
        source_count=source_count,
    )


def log_verification(result: VerificationResult, label: str = "chat") -> None:
    """Append verification metadata to logs/uncertainty.jsonl."""

    ensure_runtime_dirs()
    path = LOG_DIR / "uncertainty.jsonl"
    payload = {
        "timestamp": datetime.now().isoformat(),
        "label": label,
        **result.to_dict(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
