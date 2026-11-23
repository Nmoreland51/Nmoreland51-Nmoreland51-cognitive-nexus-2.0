"""Knowledge module: fetch a page, split text into passages, store and search them.

Storage and search live in modules/knowledge_store.py (one SQLite database with a keyword index
and vectors). This class keeps the interface the rest of the app has always used on top of it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from modules.chunking import DEFAULT_OVERLAP_WORDS, DEFAULT_TARGET_WORDS, chunk_code, chunk_text
from modules.data_stores import KNOWLEDGE_ROOT
from modules.embeddings import HASH_DIMENSIONS, Embedder, EmbeddingError
from modules.knowledge_store import KnowledgeStore
from modules.url_safety import safe_get

logger = logging.getLogger(__name__)

# What older callers passed as "source_type", and the kind of document it is.
SOURCE_KINDS = {
    "upload": "file",
    "file": "file",
    "url": "url",
    "code": "code",
    "knowledge_note": "knowledge_note",
    "web_research": "web_research",
    "web_research_summary": "web_research_summary",
    "reality_research_report": "research_report",
    "research_report": "research_report",
}


class WebResearchModule:
    """URL processing and the knowledge base."""

    def __init__(
        self,
        knowledge_base_path: Optional[str] = None,
        embedding_backend: Optional[str] = None,
        embedding_model_name: Optional[str] = None,
        embedder: Optional[Embedder] = None,
    ):
        self.knowledge_base_path = Path(knowledge_base_path) if knowledge_base_path else KNOWLEDGE_ROOT / "web_research"
        self.store = KnowledgeStore(
            self.knowledge_base_path,
            embedder=embedder,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model_name,
        )
        status = self.store.embedder_status
        self.embedding_backend = str(status.get("runtime_backend"))
        self.embedding_model_name = str(status.get("model"))

    # --- fetching ---------------------------------------------------------------------------------

    def extract_content_from_url(self, url: str) -> Dict[str, Any]:
        """Fetch a page and return its title and readable text."""

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            # safe_get refuses local/private addresses, including ones reached through redirects.
            response = safe_get(url, headers=headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            title = soup.find("title")
            title_text = title.get_text().strip() if title else "Untitled"
            main_content = None
            for selector in ("article", "main", ".content", ".post", ".article", 'div[role="main"]', ".entry-content", ".post-content"):
                main_content = soup.select_one(selector)
                if main_content:
                    break
            if not main_content:
                main_content = soup.find("body") or soup
            headings = [
                {"level": int(heading.name[1]), "text": heading.get_text().strip(), "id": heading.get("id", "")}
                for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            ]
            for heading in main_content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                # Keep headings as headings, so passages know what section they belong to.
                heading.string = f"\n\n{'#' * int(heading.name[1])} {heading.get_text(' ', strip=True)}\n\n"
            for block in main_content.find_all(["p", "li", "tr", "pre", "blockquote", "div"]):
                block.append(soup.new_string("\n"))
            cleaned_text = self._clean_text(main_content.get_text(separator="\n", strip=False))
            return {
                "url": url,
                "title": title_text,
                "content": cleaned_text,
                "headings": headings,
                "word_count": len(cleaned_text.split()),
                "timestamp": datetime.now().isoformat(),
                "status": "success",
            }
        except Exception as exc:
            logger.error("Error extracting content from %s: %s", url, exc)
            return {
                "url": url,
                "title": "Error",
                "content": "",
                "headings": [],
                "word_count": 0,
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(exc),
            }

    def _clean_text(self, text: str) -> str:
        """Tidy whitespace. Symbols, line breaks and paragraph breaks are kept.

        (This used to delete every character outside letters, digits and a few punctuation
        marks, which destroyed code, addresses, quotations and tables.)
        """

        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    # --- passages ---------------------------------------------------------------------------------

    def chunk_text(self, text: str, target_size: int = DEFAULT_TARGET_WORDS, overlap: int = DEFAULT_OVERLAP_WORDS) -> List[Dict[str, Any]]:
        """Split text into passages that follow its headings and paragraphs."""

        return [chunk.to_dict() for chunk in chunk_text(text, target_words=int(target_size), overlap_words=int(overlap))]

    def generate_embedding(self, text: str) -> List[float]:
        """Vector for one text from the backend in use."""

        try:
            return list(self.store.embedder.embed([text or ""])[0])
        except EmbeddingError as exc:
            logger.warning("Embedding failed: %s", exc)
            return []

    def add_document(self, source: str, title: str, text: str, *, kind: str = "file", meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add or replace a document. `kind` may be a document kind or an older source_type name."""

        resolved = SOURCE_KINDS.get(kind, kind)
        passages = chunk_code(text, language=str((meta or {}).get("language") or "")) if resolved == "code" else None
        return self.store.add_document(source, title, text, kind=resolved, chunks=passages, meta=meta)

    def store_chunks_and_embeddings(self, url: str, chunks: List[Dict[str, Any]], title: Optional[str] = None, kind: str = "url") -> bool:
        """Store passages that were already split (kept for older callers)."""

        try:
            result = self.store.add_document(url, title or url, None, kind=SOURCE_KINDS.get(kind, kind), chunks=chunks)
            return result.get("status") == "success"
        except Exception as exc:
            logger.error("Error storing passages: %s", exc)
            return False

    # --- search -----------------------------------------------------------------------------------

    def semantic_search(self, query: str, top_k: int = 5, **filters: Any) -> List[Dict[str, Any]]:
        """Passages that answer the query: keyword and meaning search combined."""

        try:
            return self.store.search(query, top_k=top_k, **filters)
        except Exception as exc:
            logger.error("Error in knowledge search: %s", exc)
            return []

    def _best_snippet(self, query: str, text: str, max_chars: int = 700) -> str:
        """The sentences of a passage that share the most words with the query."""

        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return ""
        query_terms = [term for term in re.findall(r"[a-zA-Z0-9_@.-]{3,}", query.lower())]
        ranked = []
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            hits = sum(1 for term in query_terms if term in sentence.lower())
            if hits:
                ranked.append((hits, -len(sentence), sentence))
        if ranked:
            ranked.sort(reverse=True)
            return " ".join(item[2] for item in ranked[:3])[:max_chars].strip()
        return cleaned[:max_chars].strip()

    def generate_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """An answer made of the best matching passages themselves (no model involved)."""

        if not context_chunks:
            return "I don't have enough information to answer that question. Add pages or files first."
        ranked = sorted(context_chunks, key=lambda chunk: float(chunk.get("similarity") or 0), reverse=True)
        best = float(ranked[0].get("similarity") or 0)
        chosen = [chunk for chunk in ranked if float(chunk.get("similarity") or 0) >= best * 0.5][:4]
        excerpts = []
        sources = []
        for index, chunk in enumerate(chosen, 1):
            snippet = self._best_snippet(query, chunk.get("text", ""))
            title = chunk.get("title") or chunk.get("url") or f"Source {index}"
            if snippet:
                excerpts.append(f"{index}. **{title}**\n\n{snippet}")
            sources.append(title)
        if not excerpts:
            return "I found potentially related local knowledge, but the stored text does not contain a clear answer to that question."
        return (
            f"Based on the local knowledge store, the strongest matching source(s) are: {', '.join(list(dict.fromkeys(sources))[:5])}.\n\n"
            f"**Question:** {query}\n\n"
            "**Relevant local excerpts:**\n\n"
            + "\n\n".join(excerpts)
            + "\n\nIf you want a synthesized answer instead of excerpts, enable **AI synthesis for knowledge queries** in the sidebar."
        )

    # --- status -----------------------------------------------------------------------------------

    def embedding_status(self) -> Dict[str, Any]:
        """How search is working right now, for Diagnostics."""

        status = dict(self.store.embedder_status)
        stats = self.store.stats()
        status["dimensions"] = self.store.vector_dimensions() or (HASH_DIMENSIONS if status.get("runtime_backend") == "hash" else None)
        status["waiting_for_vectors"] = stats["waiting_for_vectors"]
        if stats["waiting_for_vectors"]:
            status["message"] = (
                f"{status.get('message', '')} {stats['waiting_for_vectors']} passage(s) have no vector from this backend yet "
                "and are found by keyword only until they are re-embedded."
            ).strip()
        return status

    def get_processing_summary(self) -> Dict[str, Any]:
        """Counts and sources for the Files / Knowledge tab."""

        stats = self.store.stats()
        embedding_status = self.embedding_status()
        return {
            "total_urls": stats["documents"],
            "total_chunks": stats["chunks"],
            "total_words": stats["words"],
            "by_kind": stats["by_kind"],
            "waiting_for_vectors": stats["waiting_for_vectors"],
            "embedding_backend": embedding_status["runtime_backend"],
            "embedding_configured_backend": embedding_status["configured_backend"],
            "embedding_model": embedding_status["model"],
            "embedding_status": embedding_status,
            "urls": [
                {
                    "url": row["source"],
                    "title": row["title"],
                    "timestamp": row["updated_at"],
                    "word_count": row["words"],
                    "chunks_count": row["chunks"],
                    "source_type": row["kind"],
                }
                for row in self.store.list_documents(limit=200)
            ],
        }

    def close(self) -> None:
        """Close this thread's database connection (the file can then be moved or deleted)."""

        self.store.close()

    def reembed(self, **options: Any) -> Dict[str, Any]:
        """Make vectors for passages that have none from the current backend."""

        return self.store.reembed(**options)
