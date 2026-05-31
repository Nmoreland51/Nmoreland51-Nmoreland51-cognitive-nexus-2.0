"""Web research and knowledge-base integration."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from modules.providers import generate_with_ollama
from web_research_module import WebResearchModule


KNOWLEDGE_NOTES_DIR = Path("data/knowledge_notes")


def get_research_module() -> WebResearchModule:
    """Create the existing project web research module."""

    return WebResearchModule()


def validate_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Enter a URL first.")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def process_url(module: WebResearchModule, url: str) -> Dict[str, Any]:
    """Extract a URL, chunk it, store embeddings, and save metadata."""

    normalized_url = validate_url(url)
    extracted = module.extract_content_from_url(normalized_url)
    if extracted.get("status") != "success":
        return extracted

    chunks = module.chunk_text(extracted.get("content", ""))
    stored = module.store_chunks_and_embeddings(normalized_url, chunks)
    url_hash = hashlib.md5(normalized_url.encode("utf-8")).hexdigest()[:12]
    module.metadata[url_hash] = {
        "url": normalized_url,
        "title": extracted.get("title", "Untitled"),
        "timestamp": extracted.get("timestamp", datetime.now().isoformat()),
        "word_count": extracted.get("word_count", 0),
        "chunks_count": len(chunks),
        "source_type": "url",
    }
    module._save_json_file(module.metadata_file, module.metadata)
    extracted["chunks_count"] = len(chunks)
    extracted["stored"] = stored
    return extracted


def ingest_text(module: WebResearchModule, *, name: str, text: str, source_type: str = "file") -> Dict[str, Any]:
    """Ingest uploaded text into the existing web research knowledge store."""

    cleaned_text = module._clean_text(text)
    if not cleaned_text:
        return {"status": "error", "error": "No text content found.", "title": name}

    source_id = f"{source_type}:{name}"
    chunks = module.chunk_text(cleaned_text)
    stored = module.store_chunks_and_embeddings(source_id, chunks)
    source_hash = hashlib.md5(source_id.encode("utf-8")).hexdigest()[:12]
    module.metadata[source_hash] = {
        "url": source_id,
        "title": name,
        "timestamp": datetime.now().isoformat(),
        "word_count": len(cleaned_text.split()),
        "chunks_count": len(chunks),
        "source_type": source_type,
    }
    module._save_json_file(module.metadata_file, module.metadata)
    return {
        "status": "success",
        "title": name,
        "word_count": len(cleaned_text.split()),
        "chunks_count": len(chunks),
        "stored": stored,
    }


def slugify_note_title(title: str) -> str:
    """Create a compact filesystem-safe name for a local Markdown note."""

    slug = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
    return slug[:80] or "knowledge_note"


def save_knowledge_note(
    module: WebResearchModule,
    *,
    title: str,
    text: str,
    tags: str = "",
    ingest: bool = True,
    notes_dir: Path = KNOWLEDGE_NOTES_DIR,
) -> Dict[str, Any]:
    """Save a Markdown knowledge note and optionally ingest it into retrieval."""

    cleaned_title = title.strip() or "Untitled knowledge note"
    cleaned_text = text.strip()
    if not cleaned_text:
        return {"status": "error", "error": "No note text was provided.", "title": cleaned_title}

    notes_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now()
    tag_values = [tag.strip() for tag in re.split(r"[,#]", tags or "") if tag.strip()]
    tag_line = ", ".join(tag_values) if tag_values else "none"
    file_name = f"{timestamp:%Y%m%d_%H%M%S}_{slugify_note_title(cleaned_title)}.md"
    path = notes_dir / file_name
    markdown = (
        f"# {cleaned_title}\n\n"
        f"Created: {timestamp.isoformat()}\n"
        f"Tags: {tag_line}\n"
        "Source: manual_knowledge_note\n\n"
        f"{cleaned_text}\n"
    )
    path.write_text(markdown, encoding="utf-8")

    result: Dict[str, Any] = {
        "status": "success",
        "title": cleaned_title,
        "path": str(path),
        "file_name": file_name,
        "tags": tag_values,
        "ingested": False,
        "chunks_count": 0,
    }
    if ingest:
        ingest_result = ingest_text(module, name=file_name, text=markdown, source_type="knowledge_note")
        result["ingested"] = ingest_result.get("status") == "success"
        result["chunks_count"] = int(ingest_result.get("chunks_count") or 0)
        result["ingest_result"] = ingest_result
    return result


def list_knowledge_notes(notes_dir: Path = KNOWLEDGE_NOTES_DIR, limit: int = 20) -> List[Dict[str, Any]]:
    """List saved Markdown notes for the Memory and Knowledge tabs."""

    if not notes_dir.exists():
        return []
    notes: List[Dict[str, Any]] = []
    for path in sorted(notes_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        title = next((line[2:].strip() for line in lines if line.startswith("# ")), path.stem)
        tag_line = next((line.removeprefix("Tags:").strip() for line in lines if line.startswith("Tags:")), "")
        body_lines = [line for line in lines if line and not line.startswith(("# ", "Created:", "Tags:", "Source:"))]
        excerpt = " ".join(body_lines)[:240]
        stat = path.stat()
        notes.append(
            {
                "title": title,
                "tags": tag_line,
                "path": str(path),
                "file_name": path.name,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "excerpt": excerpt,
            }
        )
    return notes


def query_knowledge(
    module: WebResearchModule,
    query: str,
    *,
    model: Optional[str],
    base_url: str,
    provider_ready: bool,
    top_k: int = 5,
    ai_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """Retrieve chunks and answer with Ollama when available."""

    results = module.semantic_search(query, top_k=top_k)
    if not results:
        return {"answer": "No matching knowledge was found. Add URLs or files first.", "results": []}

    if ai_callback is not None:
        context = "\n\n".join(
            f"Source: {item.get('title') or item.get('url')}\n{item.get('text', '')[:900]}"
            for item in results
        )
        prompt = (
            "Answer the question using only the provided local knowledge. "
            "If the answer is not in the context, say that the knowledge base does not contain it.\n\n"
            f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer:"
        )
        answer = ai_callback(prompt)
    elif provider_ready and model:
        context = "\n\n".join(
            f"Source: {item.get('title') or item.get('url')}\n{item.get('text', '')[:900]}"
            for item in results
        )
        prompt = (
            "Answer the question using only the provided local knowledge. "
            "If the answer is not in the context, say that the knowledge base does not contain it.\n\n"
            f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer:"
        )
        answer = generate_with_ollama(
            prompt=prompt,
            model=model,
            base_url=base_url,
            options={"num_predict": 320, "num_ctx": 2048, "temperature": 0.35},
        )
    else:
        answer = module.generate_response(query, results)

    return {"answer": answer, "results": results}


def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Run the lightweight web search logic used by the legacy Cognitive Nexus app."""

    headers = {"User-Agent": "Mozilla/5.0"}
    results: List[Dict[str, str]] = []

    try:
        url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("AbstractText"):
            results.append(
                {
                    "title": data.get("Heading") or query,
                    "snippet": data.get("AbstractText", ""),
                    "url": data.get("AbstractURL", ""),
                    "source": "DuckDuckGo",
                }
            )

        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": topic.get("Text", "").split(" - ")[0][:90],
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                        "source": "DuckDuckGo",
                    }
                )
    except Exception:
        pass

    if len(results) < max_results:
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit={max_results}&format=json"
            response = requests.get(wiki_url, headers=headers, timeout=10)
            response.raise_for_status()
            wiki_data = response.json()
            titles = wiki_data[1] if len(wiki_data) > 1 else []
            snippets = wiki_data[2] if len(wiki_data) > 2 else []
            urls = wiki_data[3] if len(wiki_data) > 3 else []

            for title, snippet, url in zip(titles, snippets, urls):
                if len(results) >= max_results:
                    break
                results.append(
                    {
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                        "source": "Wikipedia",
                    }
                )
        except Exception:
            pass

    return results[:max_results]
