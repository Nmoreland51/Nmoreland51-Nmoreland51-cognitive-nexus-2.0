"""Claim extraction and coarse claim typing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any


CLAIM_TYPE_KEYWORDS = {
    "medical": ["diagnosis", "symptom", "treatment", "disease", "dose", "medicine", "clinical"],
    "legal": ["law", "legal", "court", "statute", "regulation", "liable", "copyright"],
    "finance": ["stock", "market", "investment", "loan", "interest", "tax", "revenue"],
    "coding": ["import", "function", "class", "api", "package", "module", "command", "npm", "pip"],
    "science": ["physics", "quantum", "chemical", "biology", "experiment", "theory", "energy"],
    "history": ["war", "century", "ancient", "president", "empire", "revolution", "founded"],
    "current_events": ["today", "currently", "latest", "recent", "as of", "this year", "2026"],
}


@dataclass
class Claim:
    text: str
    claim_type: str = "general"
    indicators: list[str] = field(default_factory=list)
    requires_evidence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'])", text.strip())
    return [part.strip() for part in parts if len(part.strip()) >= 18]


def _looks_like_claim(sentence: str) -> bool:
    lowered = sentence.lower()
    if re.search(r"\b(is|are|was|were|has|have|will|must|requires|causes|means|uses|supports|imports|introduced|released)\b", lowered):
        return True
    if re.search(r"\b\d+(\.\d+)?\s?(%|ms|kg|miles|seconds|years|tokens|gb|mb|billion|million)\b", lowered):
        return True
    if re.search(r"https?://|www\.|doi:|arxiv", lowered):
        return True
    return False


def classify_claim(sentence: str) -> tuple[str, list[str]]:
    lowered = sentence.lower()
    hits: list[tuple[str, list[str]]] = []
    for claim_type, keywords in CLAIM_TYPE_KEYWORDS.items():
        found = [keyword for keyword in keywords if keyword in lowered]
        if found:
            hits.append((claim_type, found))
    if not hits:
        return "general", []
    hits.sort(key=lambda item: len(item[1]), reverse=True)
    return hits[0]


@lru_cache(maxsize=512)
def extract_claims(text: str, max_claims: int = 18) -> tuple[Claim, ...]:
    """Extract major factual-looking claims without calling a model."""

    claims: list[Claim] = []
    for sentence in _split_sentences(text):
        if not _looks_like_claim(sentence):
            continue
        claim_type, indicators = classify_claim(sentence)
        requires_evidence = claim_type in {"medical", "legal", "finance", "science", "history", "current_events"} or bool(
            re.search(r"https?://|doi:|arxiv|\b\d{4}\b", sentence.lower())
        )
        claims.append(
            Claim(
                text=sentence[:700],
                claim_type=claim_type,
                indicators=indicators,
                requires_evidence=requires_evidence,
            )
        )
        if len(claims) >= max_claims:
            break
    return tuple(claims)
