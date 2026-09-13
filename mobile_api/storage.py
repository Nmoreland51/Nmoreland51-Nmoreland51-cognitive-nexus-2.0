from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ConversationStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_conversation(self, *, conversation_id: str | None, user_id: str, device_id: str, title: str) -> str:
        with self._lock:
            if conversation_id:
                with self._conn() as conn:
                    row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                    if row:
                        conn.execute(
                            "UPDATE conversations SET updated_at = ? WHERE id = ?",
                            (self._now(), conversation_id),
                        )
                        conn.commit()
                        return conversation_id
            cid = conversation_id or f"conv_{uuid.uuid4().hex[:16]}"
            now = self._now()
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO conversations(id, user_id, device_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (cid, user_id, device_id, title[:120], now, now),
                )
                conn.commit()
            return cid

    def add_message(self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> str:
        mid = f"msg_{uuid.uuid4().hex[:16]}"
        now = self._now()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO messages(id, conversation_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (mid, conversation_id, role, content, payload, now),
                )
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
                conn.commit()
        return mid

    def list_conversations(self, user_id: str | None = None, device_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT c.id, c.user_id, c.device_id, c.title, c.updated_at, "
            "(SELECT COUNT(1) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM conversations c"
        )
        filters: list[str] = []
        params: list[Any] = []
        if user_id:
            filters.append("c.user_id = ?")
            params.append(user_id)
        if device_id:
            filters.append("c.device_id = ?")
            params.append(device_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            header = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if not header:
                return None
            messages = conn.execute(
                "SELECT id, role, content, metadata_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        payload = dict(header)
        payload["messages"] = [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in messages
        ]
        return payload

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
                if not row:
                    return False
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
                conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                conn.commit()
        return True
