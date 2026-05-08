"""DuckDuckGo web research, scraping, summarization, and local saving."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import local
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

try:
    import trafilatura
except Exception:
    trafilatura = None

try:
    from modules.research import get_research_module, ingest_text
except Exception:
    get_research_module = None
    ingest_text = None


DATA_DIR = Path("data/web_research")
logger = logging.getLogger(__name__)
_THREAD_LOCAL = local()
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 CognitiveNexusResearchBot/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _http_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)
        _THREAD_LOCAL.session = session
    return session


def slugify_query(query: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", query.strip().lower()).strip("_")
    return slug[:max_len] or "research"


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


@lru_cache(maxsize=64)
def _search_web_cached(query: str, max_results: int) -> tuple[str, ...]:
    """Search the web with DuckDuckGo/DDGS and cache repeated queries."""

    if DDGS is None:
        raise RuntimeError("duckduckgo-search is not installed. Add it to requirements.txt.")

    logger.info("Running web search query=%r max_results=%s", query, max_results)
    results: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            url = item.get("href") or item.get("url") or ""
            results.append(
                {
                    "title": clean_text(item.get("title", "")),
                    "url": url,
                    "snippet": clean_text(item.get("body", "") or item.get("snippet", "")),
                    "source": get_domain(url),
                    "timestamp": item.get("date") or item.get("timestamp") or "",
                }
            )

    logger.info("Web search completed query=%r result_count=%s", query, len(results))
    return tuple(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in results[:max_results])


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search the web with DuckDuckGo/DDGS."""

    return [json.loads(item) for item in _search_web_cached(query.strip(), int(max_results))]


def _extract_with_beautifulsoup(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    junk_selectors = [
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "iframe",
        "[aria-label*=cookie]",
        "[class*=cookie]",
        "[id*=cookie]",
        "[class*=advert]",
        "[id*=advert]",
        "[class*=ads]",
        "[id*=ads]",
    ]
    for selector in junk_selectors:
        for tag in soup.select(selector):
            tag.decompose()

    title_tag = soup.find("title")
    title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""

    headings = [
        clean_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all(["h1", "h2", "h3", "h4"])
        if clean_text(tag.get_text(" ", strip=True))
    ]
    paragraphs = [
        clean_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all("p")
        if clean_text(tag.get_text(" ", strip=True))
    ]
    lists = [
        clean_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all(["li"])
        if clean_text(tag.get_text(" ", strip=True))
    ]
    code_blocks = [
        tag.get_text("\n", strip=True)
        for tag in soup.find_all(["pre", "code"])
        if tag.get_text(strip=True)
    ]
    links = []
    for tag in soup.find_all("a", href=True):
        text = clean_text(tag.get_text(" ", strip=True))
        href = tag.get("href", "")
        if href and text:
            links.append({"text": text[:120], "href": href})
        if len(links) >= 25:
            break

    body_parts = headings + paragraphs + lists[:40] + code_blocks[:10]
    text = clean_text(" ".join(body_parts))
    if not text:
        text = clean_text(soup.get_text(" ", strip=True))

    return {
        "title": title,
        "headings": headings,
        "paragraphs": paragraphs,
        "lists": lists[:80],
        "code_blocks": code_blocks[:20],
        "links": links,
        "text": text,
    }


@lru_cache(maxsize=128)
def _scrape_url_cached(url: str, timeout: int = 8) -> str:
    """Scrape a URL into readable text and cache repeat visits."""

    output: dict[str, Any] = {
        "url": url,
        "source": get_domain(url),
        "title": "",
        "headings": [],
        "paragraphs": [],
        "lists": [],
        "code_blocks": [],
        "links": [],
        "text": "",
        "excerpt": "",
        "success": False,
        "error": None,
    }

    try:
        response = _http_session().get(url, timeout=timeout)
        response.raise_for_status()
        html = response.text

        soup_payload = _extract_with_beautifulsoup(html)
        output.update(soup_payload)

        if trafilatura is not None:
            extracted = trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                include_comments=False,
            )
            if extracted:
                output["text"] = clean_text(extracted)

        output["excerpt"] = output["text"][:1500]
        output["success"] = bool(output["text"])
        logger.info("Scraped url=%s success=%s chars=%s", url, output["success"], len(output["text"]))
    except Exception as exc:
        output["error"] = str(exc)
        logger.warning("Scrape failed url=%s error=%s", url, exc)

    return json.dumps(output, ensure_ascii=False)


def scrape_url(url: str, timeout: int = 8) -> dict[str, Any]:
    """Scrape a URL into readable text and structured page parts."""

    return json.loads(_scrape_url_cached(url, int(timeout)))


def _build_research_prompt(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
) -> str:
    source_blocks = []

    for idx, result in enumerate(results, 1):
        source_blocks.append(
            f"[{idx}] {result.get('title', '')}\n"
            f"URL: {result.get('url', '')}\n"
            f"Source: {result.get('source', '')}\n"
            f"Snippet: {result.get('snippet', '')}\n"
        )

    for idx, page in enumerate(scraped_pages, 1):
        if page.get("success"):
            source_blocks.append(
                f"\nSCRAPED PAGE {idx}: {page.get('title')}\n"
                f"URL: {page.get('url')}\n"
                f"TEXT EXCERPT:\n{page.get('excerpt', '')}\n"
            )

    research_context = "\n\n".join(source_blocks)

    return f"""
You are Cognitive Nexus Web Research.

User query:
{query}

Research context:
{research_context}

Write a useful answer with:
1. Direct answer
2. Key findings
3. Source list
4. Uncertainty or limitations
5. Suggested next steps if useful
"""


def summarize_research(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
    ai_callback: Callable[[str], str] | None = None,
) -> str:
    """Summarize research with the active provider callback when available."""

    if ai_callback is None:
        return (
            "AI summarization is unavailable because no active provider was found.\n\n"
            "Raw research results were collected successfully."
        )

    try:
        summary = ai_callback(_build_research_prompt(query, results, scraped_pages))
        logger.info("Research summary generated query=%r chars=%s", query, len(summary or ""))
        return summary
    except Exception as exc:
        logger.warning("Research summarization failed query=%r error=%s", query, exc)
        return f"AI summarization failed: {exc}"


def save_research_session(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
    summary: str,
    settings: dict[str, Any],
    errors: list[str] | None = None,
) -> dict[str, str]:
    """Save one research session as JSON and Markdown."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify_query(query)
    base = DATA_DIR / f"{timestamp}_{slug}"

    payload = {
        "query": query,
        "timestamp": timestamp,
        "settings": settings,
        "results": results,
        "scraped_pages": scraped_pages,
        "summary": summary,
        "errors": errors or [],
    }

    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        f"# Web Research: {query}",
        "",
        f"Timestamp: {timestamp}",
        "",
        "## Summary",
        "",
        summary or "",
        "",
        "## Sources",
        "",
    ]

    for idx, result in enumerate(results, 1):
        md.append(f"{idx}. [{result.get('title', 'Untitled')}]({result.get('url', '')})")
        md.append(f"   - Source: {result.get('source', '')}")
        md.append(f"   - Snippet: {result.get('snippet', '')}")
        if result.get("timestamp"):
            md.append(f"   - Timestamp: {result.get('timestamp')}")
        md.append("")

    md.extend(["## Scraped Excerpts", ""])
    for idx, page in enumerate(scraped_pages, 1):
        md.append(f"### {idx}. {page.get('title') or page.get('url')}")
        md.append("")
        md.append(f"URL: {page.get('url')}")
        md.append("")
        md.append(page.get("excerpt", ""))
        md.append("")

    if errors:
        md.extend(["## Errors", ""])
        md.extend(f"- {error}" for error in errors)
        md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")
    logger.info("Saved research session json=%s markdown=%s", json_path, md_path)

    return {"json": str(json_path), "markdown": str(md_path)}


def add_research_to_memory(
    query: str,
    scraped_pages: list[dict[str, Any]],
    summary: str = "",
) -> dict[str, Any]:
    """Store cleaned research chunks in the existing web research knowledge store."""

    if get_research_module is None or ingest_text is None:
        return {"stored": False, "message": "No compatible memory/RAG module is available."}

    module = get_research_module()
    stored = 0
    for page in scraped_pages:
        if not page.get("success") or not page.get("text"):
            continue
        name = page.get("title") or page.get("url") or query
        result = ingest_text(module, name=name, text=page["text"], source_type="web_research")
        if result.get("status") == "success":
            stored += int(result.get("chunks_count", 0))

    if summary:
        result = ingest_text(
            module,
            name=f"Research summary: {query}",
            text=summary,
            source_type="web_research_summary",
        )
        if result.get("status") == "success":
            stored += int(result.get("chunks_count", 0))

    return {"stored": True, "chunks": stored}


def run_research_session(
    query: str,
    *,
    max_results: int = 5,
    scrape_pages: bool = True,
    summarize_with_ai: bool = True,
    save_locally: bool = True,
    save_to_memory: bool = True,
    ai_callback: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Run a full search/scrape/summarize/save session."""

    settings = {
        "max_results": max_results,
        "scrape_pages": scrape_pages,
        "summarize_with_ai": summarize_with_ai,
        "save_locally": save_locally,
        "save_to_memory": save_to_memory,
    }
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    scraped_pages: list[dict[str, Any]] = []
    summary = ""
    saved_paths: dict[str, str] = {}
    memory_result: dict[str, Any] = {}

    try:
        results = search_web(query, max_results=max_results)
    except Exception as exc:
        errors.append(f"Search failed: {exc}")
        logger.warning("Search failed query=%r error=%s", query, exc)

    if scrape_pages:
        urls = [result.get("url") for result in results if result.get("url")]
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(urls)))) as executor:
            future_to_url = {executor.submit(scrape_url, url): url for url in urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    page = future.result()
                except Exception as exc:
                    page = {
                        "url": url,
                        "source": get_domain(url),
                        "success": False,
                        "error": str(exc),
                    }
                scraped_pages.append(page)
                if not page.get("success") and page.get("error"):
                    errors.append(f"Scrape failed for {url}: {page['error']}")

    if summarize_with_ai:
        summary = summarize_research(query, results, scraped_pages, ai_callback)
    else:
        summary = "AI summarization was skipped for this research session."

    if save_to_memory:
        memory_result = add_research_to_memory(query, scraped_pages, summary)

    if save_locally:
        saved_paths = save_research_session(
            query=query,
            results=results,
            scraped_pages=scraped_pages,
            summary=summary,
            settings=settings,
            errors=errors,
        )

    return {
        "query": query,
        "settings": settings,
        "results": results,
        "scraped_pages": scraped_pages,
        "summary": summary,
        "errors": errors,
        "saved_paths": saved_paths,
        "memory_result": memory_result,
    }
