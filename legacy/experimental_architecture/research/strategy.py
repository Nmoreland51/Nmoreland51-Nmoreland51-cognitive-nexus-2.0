from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class EvidenceBundle:
    topic: str
    sources: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class ResearchStrategy:
    """A guided research strategy for Cognitive Nexus."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.evidence = EvidenceBundle(topic=topic)

    def add_source(self, source: str) -> None:
        self.evidence.sources.append(source)

    def add_note(self, note: str) -> None:
        self.evidence.notes.append(note)

    def summarize(self) -> str:
        return f"Research strategy for {self.topic}: {len(self.evidence.sources)} sources, {len(self.evidence.notes)} notes."
