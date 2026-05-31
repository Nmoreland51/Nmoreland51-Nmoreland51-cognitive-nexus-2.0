"""
Compression compatibility layer for Cognitive Nexus.

This satisfies core/__init__.py imports:
    from .compression import TheoryCompressor, ExtractedPattern

It provides lightweight pattern extraction and idea compression so startup does not crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ExtractedPattern:
    name: str
    description: str
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TheoryCompressor:
    """
    Lightweight theory/pattern compressor.

    Takes long text, notes, or reasoning output and reduces it into:
    - summary
    - key points
    - extracted patterns
    """

    def __init__(self) -> None:
        self.patterns: List[ExtractedPattern] = []
        self.history: List[Dict[str, Any]] = []

    def compress(
        self,
        text: str,
        max_points: int = 5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        text = str(text or "").strip()

        if not text:
            result = {
                "summary": "",
                "key_points": [],
                "patterns": [],
                "confidence": 0.0,
                "metadata": metadata,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.history.append(result)
            return result

        sentences = [
            part.strip()
            for part in text.replace("\n", " ").split(".")
            if part.strip()
        ]

        key_points = sentences[:max_points]

        summary = " ".join(key_points)
        if len(summary) > 600:
            summary = summary[:600].rstrip() + "..."

        patterns = self.extract_patterns(text, metadata=metadata)

        result = {
            "summary": summary,
            "key_points": key_points,
            "patterns": [pattern.to_dict() for pattern in patterns],
            "confidence": 0.6 if key_points else 0.3,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat(),
        }

        self.history.append(result)
        return result

    def extract_patterns(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ExtractedPattern]:
        metadata = metadata or {}
        text = str(text or "").strip()

        patterns: List[ExtractedPattern] = []

        lowered = text.lower()

        if "because" in lowered or "therefore" in lowered or "so" in lowered:
            patterns.append(
                ExtractedPattern(
                    name="causal_reasoning",
                    description="The text appears to contain cause-and-effect reasoning.",
                    confidence=0.6,
                    evidence=["Detected causal connector words."],
                    metadata=metadata,
                )
            )

        if "error" in lowered or "failed" in lowered or "exception" in lowered:
            patterns.append(
                ExtractedPattern(
                    name="failure_diagnosis",
                    description="The text appears to describe an error or failure state.",
                    confidence=0.75,
                    evidence=["Detected error-related language."],
                    metadata=metadata,
                )
            )

        if "should" in lowered or "need" in lowered or "must" in lowered:
            patterns.append(
                ExtractedPattern(
                    name="action_requirement",
                    description="The text appears to contain a requested or required action.",
                    confidence=0.65,
                    evidence=["Detected action/requirement language."],
                    metadata=metadata,
                )
            )

        if not patterns:
            patterns.append(
                ExtractedPattern(
                    name="general_pattern",
                    description="General information pattern extracted from the text.",
                    confidence=0.4,
                    evidence=[text[:200]],
                    metadata=metadata,
                )
            )

        self.patterns.extend(patterns)
        return patterns

    def summarize(
        self,
        text: str,
        max_points: int = 5,
    ) -> str:
        return self.compress(text, max_points=max_points).get("summary", "")

    def analyze(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.compress(text, metadata=metadata)

    def process(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.compress(text, metadata=metadata)

    def latest_patterns(self, limit: int = 10) -> List[ExtractedPattern]:
        return self.patterns[-limit:]

    def latest_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.history[-limit:]

    def clear(self) -> None:
        self.patterns.clear()
        self.history.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "history": list(self.history),
        }