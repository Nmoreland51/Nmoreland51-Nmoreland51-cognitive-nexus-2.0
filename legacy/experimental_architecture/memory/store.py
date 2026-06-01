from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List


@dataclass
class MemoryItem:
    key: str
    value: Any
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryStore:
    """Simple in-memory store for persistent facts and observations."""

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    def set(self, key: str, value: Any, metadata: dict[str, Any] | None = None) -> None:
        self._items[key] = MemoryItem(key=key, value=value, metadata=metadata or {})

    def get(self, key: str, default: Any = None) -> Any:
        item = self._items.get(key)
        return item.value if item else default

    def search(self, query: str) -> list[MemoryItem]:
        normalized = query.lower()
        return [item for item in self._items.values() if normalized in str(item.value).lower() or normalized in item.key.lower()]

    def all(self) -> list[MemoryItem]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()
