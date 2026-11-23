"""The knowledge index: documents, passages, a keyword index and vectors in one SQLite database.

It replaces three JSON files (chunks, embeddings, metadata) that were rewritten whole on every
change, without a lock, by whichever program saved last. SQLite gives real transactions, so the
desktop app and the phone backend can read and write at the same time, and a change is either
fully saved or not at all.

Search is hybrid. A keyword index (SQLite FTS5, BM25 ranking) finds passages that share words with
the question; vectors from an embedding model find passages that mean the same in other words.
The two rankings are merged (reciprocal rank fusion), so an exact term match and a paraphrase
both surface. A passage is returned only if it matched a keyword or is close enough in meaning;
"nearest" alone is not a reason, because something is always nearest.

Vectors are tagged with the backend that made them. Changing the embedding model does not break
search: passages without a vector from the current backend are still found by keyword, the
status reports how many are waiting, and reembed() fills them in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from modules.chunking import Chunk, chunk_code, chunk_text
from modules.data_stores import KNOWLEDGE_ROOT
from modules.embeddings import Embedder, EmbeddingError, choose_embedder, report_degraded, terms
from modules.event_log import record_event

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DB_NAME = "knowledge.sqlite3"
LEGACY_FILES = ("chunks.json", "embeddings.json", "metadata.json")
RRF_K = 60
CANDIDATES = 60
EMBEDDING_CACHE_ROWS = 50_000
# Cosine similarity below which a passage found only by meaning is not returned. Chosen from the
# retrieval benchmark (docs/benchmarks): unrelated passages score below it, paraphrases above.
SEMANTIC_FLOOR = {"ollama:all-minilm": 0.30, "default": 0.35}
# How much a kind of source counts. Your own files and notes outrank a saved web page.
KIND_WEIGHT = {
    "file": 1.0,
    "code": 1.0,
    "knowledge_note": 1.0,
    "research_report": 0.95,
    "web_research_summary": 0.95,
    "web_research": 0.9,
    "url": 0.9,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def document_id(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8", errors="replace")).hexdigest()[:16]


def _to_blob(vector: Sequence[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _fts_query(query: str) -> str:
    """An FTS5 query that matches any of the question's words (ranking does the rest)."""

    words = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]{2,}", " ".join(terms(query)))))
    return " OR ".join(f'"{word}"' for word in words[:24])


def quick_stats(folder: Path | str | None = None) -> dict[str, int]:
    """Document and passage counts read straight from the database file, without loading an
    embedding backend. For status pages that only need numbers."""

    path = (Path(folder) if folder else KNOWLEDGE_ROOT / "web_research") / DB_NAME
    counts = {"documents": 0, "chunks": 0}
    if not path.is_file():
        return counts
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
        try:
            counts["documents"] = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            counts["chunks"] = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        pass
    return counts


class KnowledgeStore:
    """One knowledge database. Safe to use from several threads and several processes."""

    def __init__(
        self,
        folder: Path | str | None = None,
        *,
        embedder: Embedder | None = None,
        embedder_status: dict[str, Any] | None = None,
        embedding_backend: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self.folder = Path(folder) if folder else KNOWLEDGE_ROOT / "web_research"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / DB_NAME
        self._local = threading.local()
        self._matrix_lock = threading.Lock()
        self._matrix: tuple[tuple[str, int], np.ndarray, np.ndarray] | None = None
        self._query_vectors: dict[tuple[str, str], np.ndarray] = {}
        if embedder is None:
            embedder, embedder_status = choose_embedder(embedding_backend, embedding_model)
        self.embedder = embedder
        self.embedder_status = embedder_status or {
            "configured_backend": "custom",
            "runtime_backend": embedder.name,
            "model": embedder.name,
            "name": embedder.name,
            "semantic": embedder.semantic,
            "degraded": False,
            "available": True,
            "message": f"Using {embedder.name}.",
        }
        report_degraded(self.embedder_status)
        self._open_schema()
        self.legacy_import = self._import_legacy_json()

    # --- connection and schema -------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def _open_schema(self) -> None:
        connection = self._connect()
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"The knowledge database is version {version}, newer than this app understands ({SCHEMA_VERSION}). "
                "Update the app; the database was left untouched."
            )
        if version == SCHEMA_VERSION:
            return
        # Every statement is "IF NOT EXISTS", so two programs starting at once both end up with
        # the same schema; SQLite makes the second one wait for the first.
        if version < 1:
            connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        content_sha TEXT NOT NULL,
                        added_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        words INTEGER NOT NULL DEFAULT 0,
                        meta TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE TABLE IF NOT EXISTS chunks (
                        id INTEGER PRIMARY KEY,
                        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        heading TEXT NOT NULL DEFAULT '',
                        text TEXT NOT NULL,
                        start_line INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id, position);
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                        text, heading, title, tokenize = 'porter unicode61 remove_diacritics 2'
                    );
                    CREATE TABLE IF NOT EXISTS vectors (
                        chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                        backend TEXT NOT NULL,
                        dim INTEGER NOT NULL,
                        vector BLOB NOT NULL,
                        PRIMARY KEY (chunk_id, backend)
                    );
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        backend TEXT NOT NULL,
                        text_sha TEXT NOT NULL,
                        dim INTEGER NOT NULL,
                        vector BLOB NOT NULL,
                        used_at TEXT NOT NULL,
                        PRIMARY KEY (backend, text_sha)
                    );
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT OR IGNORE INTO meta(key, value) VALUES ('revision', '0');
                    """
            )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _bump(self, connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'revision'")

    def _revision(self) -> int:
        row = self._connect().execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
        return int(row[0]) if row else 0

    # --- embeddings ------------------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> list[bytes]:
        """Vectors for texts as blobs, using the saved cache for texts embedded before."""

        if not texts:
            return []
        backend = self.embedder.name
        connection = self._connect()
        keys = [_sha(text) for text in texts]
        found: dict[str, bytes] = {}
        for start in range(0, len(keys), 400):
            part = keys[start : start + 400]
            marks = ",".join("?" for _ in part)
            for row in connection.execute(
                f"SELECT text_sha, vector FROM embedding_cache WHERE backend = ? AND text_sha IN ({marks})", [backend, *part]
            ):
                found[row["text_sha"]] = row["vector"]
        missing = [index for index, key in enumerate(keys) if key not in found]
        if missing:
            unique: dict[str, str] = {keys[index]: texts[index] for index in missing}
            vectors = self.embedder.embed(list(unique.values()))
            now = _now()
            rows = [(backend, key, len(vector), _to_blob(vector), now) for key, vector in zip(unique, vectors)]
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany("INSERT OR REPLACE INTO embedding_cache(backend, text_sha, dim, vector, used_at) VALUES (?, ?, ?, ?, ?)", rows)
                count = int(connection.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0])
                if count > EMBEDDING_CACHE_ROWS:
                    connection.execute(
                        "DELETE FROM embedding_cache WHERE rowid IN (SELECT rowid FROM embedding_cache ORDER BY used_at LIMIT ?)",
                        (count - EMBEDDING_CACHE_ROWS,),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            for row in rows:
                found[row[1]] = row[3]
        return [found[key] for key in keys]

    @staticmethod
    def _embedding_input(title: str, heading: str, text: str) -> str:
        """What is embedded for a passage: its text with the title and heading it belongs to."""

        lead = " > ".join(part for part in (title.strip(), heading.strip()) if part)
        return f"{lead}\n{text}" if lead else text

    def embed_query(self, query: str) -> np.ndarray | None:
        key = (self.embedder.name, query)
        if key not in self._query_vectors:
            try:
                vector = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
            except EmbeddingError as exc:
                logger.warning("Query embedding failed; keyword search only: %s", exc)
                record_event("degraded_mode", "Knowledge search fell back to keywords for one query", error=str(exc))
                return None
            if len(self._query_vectors) > 256:
                self._query_vectors.clear()
            self._query_vectors[key] = vector
        return self._query_vectors[key]

    # --- writing ---------------------------------------------------------------------------------

    def add_document(
        self,
        source: str,
        title: str,
        text: str | None = None,
        *,
        kind: str = "file",
        chunks: Iterable[Chunk | dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add or replace one document. Unchanged content is recognised and not processed again."""

        source = str(source).strip()
        title = (title or source).strip()
        prepared: list[Chunk] = []
        if chunks is not None:
            for position, item in enumerate(chunks):
                if isinstance(item, Chunk):
                    prepared.append(Chunk(text=item.text, heading=item.heading, position=position, start_line=item.start_line))
                else:
                    prepared.append(
                        Chunk(
                            text=str(item.get("text") or ""),
                            heading=str(item.get("heading") or ""),
                            position=position,
                            start_line=int(item.get("start_line") or 0),
                        )
                    )
        elif text:
            prepared = chunk_code(text) if kind == "code" else chunk_text(text)
        prepared = [chunk for chunk in prepared if chunk.text.strip()]
        if not source or not prepared:
            return {"status": "error", "error": "No text content found.", "title": title, "chunks_count": 0}
        content = text if text is not None else "\n\n".join(chunk.text for chunk in prepared)
        content_sha = _sha(f"{kind}\n{title}\n{content}")
        doc_id = document_id(source)
        connection = self._connect()
        backend = self.embedder.name

        existing = connection.execute("SELECT content_sha FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if existing and existing["content_sha"] == content_sha:
            waiting = connection.execute(
                "SELECT COUNT(*) FROM chunks c WHERE c.document_id = ? AND NOT EXISTS "
                "(SELECT 1 FROM vectors v WHERE v.chunk_id = c.id AND v.backend = ?)",
                (doc_id, backend),
            ).fetchone()[0]
            if not waiting:
                count = connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc_id,)).fetchone()[0]
                return {"status": "success", "unchanged": True, "document_id": doc_id, "title": title, "chunks_count": int(count), "embedded": int(count)}

        # Embedding can take a while and may fail; it happens before the write lock is taken.
        vectors: list[bytes] | None
        embedding_error = ""
        try:
            vectors = self._embed([self._embedding_input(title, chunk.heading, chunk.text) for chunk in prepared])
        except EmbeddingError as exc:
            vectors, embedding_error = None, str(exc)
            record_event("degraded_mode", "A document was saved without vectors; keyword search still finds it", source=source, error=str(exc))

        now = _now()
        # Passages overlap a little, so the document's size is counted from its own text.
        words = len(content.split())
        connection.execute("BEGIN IMMEDIATE")
        try:
            previous = connection.execute("SELECT added_at FROM documents WHERE id = ?", (doc_id,)).fetchone()
            self._delete_chunks(connection, doc_id)
            connection.execute(
                "INSERT INTO documents(id, source, title, kind, content_sha, added_at, updated_at, words, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title = excluded.title, kind = excluded.kind, content_sha = excluded.content_sha, "
                "updated_at = excluded.updated_at, words = excluded.words, meta = excluded.meta",
                (doc_id, source, title, kind, content_sha, previous["added_at"] if previous else now, now, words, json.dumps(meta or {}, ensure_ascii=False)),
            )
            for index, chunk in enumerate(prepared):
                cursor = connection.execute(
                    "INSERT INTO chunks(document_id, position, heading, text, start_line) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, index, chunk.heading, chunk.text, chunk.start_line),
                )
                chunk_id = cursor.lastrowid
                connection.execute("INSERT INTO chunks_fts(rowid, text, heading, title) VALUES (?, ?, ?, ?)", (chunk_id, chunk.text, chunk.heading, title))
                if vectors is not None:
                    connection.execute(
                        "INSERT INTO vectors(chunk_id, backend, dim, vector) VALUES (?, ?, ?, ?)",
                        (chunk_id, backend, len(vectors[index]) // 4, vectors[index]),
                    )
            self._bump(connection)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        result = {
            "status": "success",
            "unchanged": False,
            "document_id": doc_id,
            "title": title,
            "chunks_count": len(prepared),
            "embedded": len(prepared) if vectors is not None else 0,
            "word_count": words,
        }
        if embedding_error:
            result["warning"] = f"Saved, but without vectors ({embedding_error}). It will be found by keywords until vectors are added."
        return result

    @staticmethod
    def _delete_chunks(connection: sqlite3.Connection, doc_id: str) -> int:
        ids = [row[0] for row in connection.execute("SELECT id FROM chunks WHERE document_id = ?", (doc_id,))]
        for start in range(0, len(ids), 400):
            part = ids[start : start + 400]
            marks = ",".join("?" for _ in part)
            connection.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", part)
            connection.execute(f"DELETE FROM vectors WHERE chunk_id IN ({marks})", part)
        connection.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        return len(ids)

    def delete_document(self, source_or_id: str) -> bool:
        connection = self._connect()
        row = connection.execute("SELECT id FROM documents WHERE id = ? OR source = ?", (source_or_id, source_or_id)).fetchone()
        if row is None:
            return False
        connection.execute("BEGIN IMMEDIATE")
        try:
            self._delete_chunks(connection, row["id"])
            connection.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
            self._bump(connection)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        return True

    # --- reading ---------------------------------------------------------------------------------

    def list_documents(self, limit: int = 200, kind: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT d.id, d.source, d.title, d.kind, d.added_at, d.updated_at, d.words, d.meta, "
            "(SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunks FROM documents d"
        )
        arguments: list[Any] = []
        if kind:
            sql += " WHERE d.kind = ?"
            arguments.append(kind)
        sql += " ORDER BY d.updated_at DESC, d.rowid DESC LIMIT ?"
        arguments.append(int(limit))
        rows = []
        for row in self._connect().execute(sql, arguments):
            item = dict(row)
            try:
                item["meta"] = json.loads(item["meta"] or "{}")
            except json.JSONDecodeError:
                item["meta"] = {}
            rows.append(item)
        return rows

    def stats(self) -> dict[str, Any]:
        connection = self._connect()
        backend = self.embedder.name
        chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        embedded = int(connection.execute("SELECT COUNT(*) FROM vectors WHERE backend = ?", (backend,)).fetchone()[0])
        return {
            "documents": int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
            "chunks": chunks,
            "embedded": embedded,
            "waiting_for_vectors": chunks - embedded,
            "by_kind": {row["kind"]: int(row["count"]) for row in connection.execute("SELECT kind, COUNT(*) AS count FROM documents GROUP BY kind")},
            "words": int(connection.execute("SELECT COALESCE(SUM(words), 0) FROM documents").fetchone()[0]),
            "schema_version": SCHEMA_VERSION,
            "embedding_backend": backend,
            "database": str(self.path),
        }

    def vector_dimensions(self) -> int | None:
        """Size of the vectors stored for the backend in use, or None when there are none yet."""

        row = self._connect().execute("SELECT dim FROM vectors WHERE backend = ? LIMIT 1", (self.embedder.name,)).fetchone()
        return int(row[0]) if row else None

    def _vector_matrix(self) -> tuple[np.ndarray, np.ndarray]:
        """(chunk ids, matrix of their vectors) for the backend in use, reloaded when the data changed."""

        key = (self.embedder.name, self._revision())
        with self._matrix_lock:
            if self._matrix is None or self._matrix[0] != key:
                ids: list[int] = []
                blobs: list[bytes] = []
                dim = 0
                for row in self._connect().execute("SELECT chunk_id, dim, vector FROM vectors WHERE backend = ? ORDER BY chunk_id", (key[0],)):
                    if dim and row["dim"] != dim:
                        continue  # a vector of another size cannot be compared; it will be re-embedded
                    dim = dim or int(row["dim"])
                    ids.append(int(row["chunk_id"]))
                    blobs.append(row["vector"])
                matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(ids), dim) if ids else np.zeros((0, 1), dtype=np.float32)
                self._matrix = (key, np.asarray(ids, dtype=np.int64), matrix)
            return self._matrix[1], self._matrix[2]

    def semantic_floor(self) -> float:
        name = self.embedder.name
        return next((floor for prefix, floor in SEMANTIC_FLOOR.items() if name.startswith(prefix)), SEMANTIC_FLOOR["default"])

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        kinds: Sequence[str] | None = None,
        source_contains: str | None = None,
        since: str | None = None,
        per_document: int = 2,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Passages that answer `query`, best first.

        Filters: `kinds` (for example ["file", "knowledge_note"]), `source_contains` (part of a
        file name or address), `since` (ISO date; only documents updated on or after it).
        `mode` is "hybrid" (default), "keyword" or "vector"; the last two exist for measurement.
        """

        query = (query or "").strip()
        if not query or top_k <= 0:
            return []
        connection = self._connect()
        keyword: dict[int, int] = {}
        if mode in {"hybrid", "keyword"}:
            match = _fts_query(query)
            if match:
                try:
                    rows = connection.execute(
                        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 1.0, 0.6, 1.6) LIMIT ?",
                        (match, CANDIDATES),
                    ).fetchall()
                except sqlite3.OperationalError as exc:
                    logger.warning("Keyword search failed for %r: %s", query, exc)
                    rows = []
                keyword = {int(row[0]): rank for rank, row in enumerate(rows, 1)}

        similarity: dict[int, float] = {}
        vector_rank: dict[int, int] = {}
        if mode in {"hybrid", "vector"}:
            ids, matrix = self._vector_matrix()
            query_vector = self.embed_query(query) if len(ids) else None
            if query_vector is not None and matrix.shape[1] == query_vector.shape[0]:
                scores = matrix @ query_vector
                order = np.argsort(-scores)[:CANDIDATES]
                floor = self.semantic_floor()
                for rank, index in enumerate(order, 1):
                    chunk_id, score = int(ids[index]), float(scores[index])
                    similarity[chunk_id] = score
                    if self.embedder.semantic:
                        qualifies = score >= floor
                    else:
                        # Word-hash vectors only measure shared words, so they may strengthen a
                        # keyword match but never bring in a passage on their own.
                        qualifies = chunk_id in keyword and score > 0
                    if qualifies:
                        vector_rank[chunk_id] = rank

        candidates = set(keyword) | set(vector_rank)
        if not candidates:
            return []
        marks = ",".join("?" for _ in candidates)
        sql = (
            "SELECT c.id, c.document_id, c.position, c.heading, c.text, c.start_line, d.source, d.title, d.kind, d.added_at, d.updated_at "
            f"FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN ({marks})"
        )
        arguments: list[Any] = list(candidates)
        if kinds:
            sql += f" AND d.kind IN ({','.join('?' for _ in kinds)})"
            arguments.extend(kinds)
        if source_contains:
            sql += " AND (d.source LIKE ? OR d.title LIKE ?)"
            arguments.extend([f"%{source_contains}%"] * 2)
        if since:
            sql += " AND d.updated_at >= ?"
            arguments.append(since)
        phrase = " ".join(terms(query))
        results = []
        for row in connection.execute(sql, arguments):
            chunk_id = int(row["id"])
            score = 0.0
            if chunk_id in keyword:
                score += 1.0 / (RRF_K + keyword[chunk_id])
            if chunk_id in vector_rank:
                score += 1.0 / (RRF_K + vector_rank[chunk_id])
            score *= KIND_WEIGHT.get(row["kind"], 0.9)
            if len(phrase.split()) >= 2 and phrase in " ".join(terms(row["text"])):
                score *= 1.15  # the question's words appear together, in order
            matched = "both" if chunk_id in keyword and chunk_id in vector_rank else ("keyword" if chunk_id in keyword else "meaning")
            results.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": row["document_id"],
                    "text": row["text"],
                    "title": row["title"],
                    "url": row["source"],
                    "kind": row["kind"],
                    "heading": row["heading"],
                    "chunk_index": int(row["position"]),
                    "start_line": int(row["start_line"]),
                    "added_at": row["added_at"],
                    "updated_at": row["updated_at"],
                    "score": score,
                    "similarity": round(score * (RRF_K + 1) / 2.0, 4),
                    "lexical_score": round(1.0 / keyword[chunk_id], 4) if chunk_id in keyword else 0.0,
                    "vector_score": round(similarity.get(chunk_id, 0.0), 4),
                    "matched": matched,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        # Do not let one long document fill the whole answer when others are relevant too.
        chosen: list[dict[str, Any]] = []
        held_back: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for item in results:
            if seen.get(item["document_id"], 0) < per_document:
                chosen.append(item)
                seen[item["document_id"]] = seen.get(item["document_id"], 0) + 1
            else:
                held_back.append(item)
        return (chosen + held_back)[:top_k]

    # --- migration and maintenance ---------------------------------------------------------------

    def waiting_for_vectors(self) -> int:
        return int(self.stats()["waiting_for_vectors"])

    def reembed(self, *, batch: int = 64, limit: int | None = None, progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        """Make vectors with the current backend for every passage that lacks one.

        Run after the embedding model changed, or after documents were saved while the model was
        unavailable. Safe to stop and run again.
        """

        connection = self._connect()
        backend = self.embedder.name
        total = self.waiting_for_vectors()
        done = 0
        while limit is None or done < limit:
            rows = connection.execute(
                "SELECT c.id, c.heading, c.text, d.title FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE NOT EXISTS (SELECT 1 FROM vectors v WHERE v.chunk_id = c.id AND v.backend = ?) ORDER BY c.id LIMIT ?",
                (backend, batch),
            ).fetchall()
            if not rows:
                break
            try:
                vectors = self._embed([self._embedding_input(row["title"], row["heading"], row["text"]) for row in rows])
            except EmbeddingError as exc:
                return {"embedded": done, "waiting": total - done, "error": str(exc)}
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany(
                    "INSERT OR REPLACE INTO vectors(chunk_id, backend, dim, vector) VALUES (?, ?, ?, ?)",
                    [(row["id"], backend, len(vector) // 4, vector) for row, vector in zip(rows, vectors)],
                )
                self._bump(connection)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            done += len(rows)
            if progress:
                progress(done, total)
        # Vectors from backends no longer in use only take space.
        if not self.waiting_for_vectors():
            connection.execute("DELETE FROM vectors WHERE backend != ?", (backend,))
        return {"embedded": done, "waiting": self.waiting_for_vectors(), "error": ""}

    def _import_legacy_json(self) -> dict[str, Any]:
        """Bring an index saved by the old JSON format into the database, once.

        The JSON files are renamed, not deleted. Their stored word-hash vectors are not used;
        passages are rebuilt (the old format overlapped its 750-word pieces) and re-embedded.
        """

        chunks_file = self.folder / "chunks.json"
        if not chunks_file.is_file():
            return {}
        connection = self._connect()
        if connection.execute("SELECT 1 FROM meta WHERE key = 'legacy_import'").fetchone():
            return {}
        try:
            old_chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
            metadata_file = self.folder / "metadata.json"
            old_meta = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.is_file() else {}
        except (OSError, json.JSONDecodeError) as exc:
            record_event("error", "The old knowledge index could not be read and was left in place", error=str(exc))
            return {"error": str(exc)}
        imported = passages = 0
        for source_hash, pieces in (old_chunks or {}).items():
            if not isinstance(pieces, dict) or not pieces:
                continue
            info = old_meta.get(source_hash, {}) if isinstance(old_meta, dict) else {}
            ordered = sorted(pieces.values(), key=lambda piece: (int(piece.get("start_word", 0) or 0), int(piece.get("chunk_index", 0) or 0)))
            words: list[str] = []
            covered = 0
            for piece in ordered:
                piece_words = str(piece.get("text") or "").split()
                start = int(piece.get("start_word", covered) or 0)
                skip = max(0, covered - start) if start <= covered else 0
                words.extend(piece_words[skip:])
                covered = max(covered, start + len(piece_words))
            text = " ".join(words)
            source = str(info.get("url") or f"legacy:{source_hash}")
            result = self.add_document(
                source,
                str(info.get("title") or source),
                text,
                kind=str(info.get("source_type") or "url"),
                meta={"imported_from": "json index", "original_timestamp": info.get("timestamp", "")},
            )
            if result.get("status") == "success":
                imported += 1
                passages += int(result.get("chunks_count") or 0)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for name in LEGACY_FILES:
            old = self.folder / name
            if old.is_file():
                old.rename(self.folder / f"{name}.migrated-{stamp}")
        summary = {"documents": imported, "passages": passages, "at": _now()}
        connection.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('legacy_import', ?)", (json.dumps(summary),))
        logger.info("Imported the old knowledge index: %s", summary)
        return summary
