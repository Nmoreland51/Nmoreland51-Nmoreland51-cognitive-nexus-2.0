"""DuckDuckGo web research, scraping, summarization, and local saving."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock, local
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlsplit, urlunsplit

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

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

from core.reality_grounding.prompt_firewall import UNTRUSTED_RULE, defuse_untrusted_text, fence_untrusted, removed_note
from modules.data_stores import DATA_ROOT
from modules.event_log import record_event
from modules.file_utils import atomic_write_text
from modules.url_safety import safe_get

try:
    from modules.research import get_research_module, ingest_text
except Exception:
    get_research_module = None
    ingest_text = None


DATA_DIR = DATA_ROOT / "web_research"
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


def _flatten_markdown(text: str) -> str:
    """Turn trafilatura's markdown into plain text: "## Version 1.67.0" becomes "Version 1.67.0."
    so headings survive whitespace cleanup as their own sentence, and **bold** markers go away
    (not __, which would mangle Python names like __init__)."""

    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
            if not stripped:
                continue
            if stripped[-1] not in ".!?:":
                stripped += "."
        lines.append(stripped)
    return "\n".join(lines).replace("**", "")


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


MAX_TITLE_CHARS = 100
MAX_SNIPPET_CHARS = 500
# Where a second title was glued on without a space, e.g. "Famous BirthdaysCoryxKenshin".
_GLUED_TITLE = re.compile(r"(?<=[a-z0-9.!?)])(?=[A-Z])")


def _shorten(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-|")
    return f"{cut}…"


def _clean_title(title: str) -> str:
    """Trim titles that some search engines return as several results run together."""

    title = clean_text(title)
    if len(title) > MAX_TITLE_CHARS:
        glued = _GLUED_TITLE.search(title, 20)
        if glued:
            title = title[: glued.start()].rstrip(" .")
    return _shorten(title, MAX_TITLE_CHARS)


# --- Search sources ----------------------------------------------------------------------------
# search_web tries each available source in order and automatically switches to the next one when
# a source errors, is rate-limited, or finds nothing. A source that errors is skipped for
# SEARCH_COOLDOWN_SECONDS so later searches don't wait on it; if every source is cooling down, all
# are tried anyway. Order and sources are set with environment variables (see .env.example):
#   searxng   - your own SearXNG server: SEARXNG_URL (needs the JSON format enabled)
#   brave     - Brave Search API: BRAVE_SEARCH_API_KEY
#   ddgs      - free search-page scraping through the ddgs library (often rate-limited)
#   wikipedia - Wikipedia's search API; last resort, good for who/what questions
DEFAULT_SEARCH_ORDER = "searxng,brave,ddgs,wikipedia"
SEARCH_COOLDOWN_SECONDS = 300
SEARCH_REQUEST_TIMEOUT = 10
API_USER_AGENT = "CognitiveNexus/2.0 (local research assistant)"
_SOURCE_LABELS = {
    "searxng": "SearXNG",
    "brave": "Brave Search API",
    "ddgs": "Search pages (ddgs)",
    "wikipedia": "Wikipedia",
}
_cooldown_until: dict[str, float] = {}


def _search_result(title: str, url: str, snippet: str, timestamp: str = "") -> dict[str, Any]:
    return {
        "title": _clean_title(title),
        "url": url,
        # Some engines return several results' text as one snippet (2,000+ chars).
        "snippet": _shorten(clean_text(snippet), MAX_SNIPPET_CHARS),
        "source": get_domain(url),
        "timestamp": timestamp or "",
        "retrieved_at": _utc_now(),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# How long a search result list and a fetched page are reused. Without an expiry, a "latest
# version" answer stayed whatever it was when the app started.
SEARCH_CACHE_SECONDS = 600
PAGE_CACHE_SECONDS = 1800
_TRACKING_PARAMETERS = re.compile(r"^(?:utm_[a-z]+|fbclid|gclid|msclkid|mc_cid|mc_eid|ref|ref_src|igshid|spm)$", re.IGNORECASE)
_RETRY_STATUS = {429, 500, 502, 503, 504}
_HOST_SPACING_SECONDS = 0.4
_host_lock = Lock()
_host_last_request: dict[str, float] = {}


class _ExpiringCache:
    """Decorator: remember results for a limited time. `keep` decides whether a result is worth keeping."""

    def __init__(self, seconds: float, maxsize: int, keep: Callable[[Any], bool] = lambda _value: True) -> None:
        self.seconds, self.maxsize, self.keep = seconds, maxsize, keep
        self._items: dict[tuple, tuple[float, Any]] = {}
        self._lock = Lock()

    def __call__(self, function: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any) -> Any:
            now = time.monotonic()
            with self._lock:
                hit = self._items.get(args)
                if hit and now - hit[0] < self.seconds:
                    return hit[1]
            value = function(*args)
            if self.keep(value):
                with self._lock:
                    if len(self._items) >= self.maxsize:
                        oldest = min(self._items, key=lambda key: self._items[key][0])
                        del self._items[oldest]
                    self._items[args] = (now, value)
            return value

        wrapper.cache_clear = self.clear  # type: ignore[attr-defined]
        wrapper.__doc__ = function.__doc__
        return wrapper

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def canonical_url(url: str) -> str:
    """The same page under one address: no fragment, no tracking parameters, no trailing slash."""

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMETERS.match(key)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _retry_wait(retry_after: Any) -> float:
    """Seconds to wait before the one retry: what the server asked for, up to five."""

    try:
        return min(max(float(retry_after), 0.0), 5.0)
    except (TypeError, ValueError):
        return 1.0  # no header, or a date instead of a number of seconds


def _wait_for_host(url: str) -> None:
    """Space out requests to the same site so a research run does not hammer it."""

    host = get_domain(url)
    with _host_lock:
        now = time.monotonic()
        wait = _host_last_request.get(host, 0.0) + _HOST_SPACING_SECONDS - now
        _host_last_request[host] = max(now, now + wait)
    if wait > 0:
        time.sleep(wait)


def _get_json(url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": API_USER_AGENT, "Accept": "application/json", **(headers or {})},
        timeout=SEARCH_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _search_searxng(query: str, max_results: int) -> list[dict[str, Any]]:
    base = os.environ.get("SEARXNG_URL", "").rstrip("/")
    data = _get_json(f"{base}/search", params={"q": query, "format": "json"})
    return [
        _search_result(item.get("title", ""), item.get("url", ""), item.get("content", ""), item.get("publishedDate") or "")
        for item in data.get("results", [])
    ][:max_results]


def _search_brave(query: str, max_results: int) -> list[dict[str, Any]]:
    data = _get_json(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(max_results, 20)},
        headers={"X-Subscription-Token": os.environ.get("BRAVE_SEARCH_API_KEY", "")},
    )
    return [
        _search_result(item.get("title", ""), item.get("url", ""), item.get("description", ""), item.get("age") or "")
        for item in (data.get("web") or {}).get("results", [])
    ][:max_results]


def _search_ddgs(query: str, max_results: int) -> list[dict[str, Any]]:
    if DDGS is None:
        raise RuntimeError("ddgs is not installed.")
    try:
        with DDGS() as ddgs:
            items = ddgs.text(query, max_results=max_results)
    except Exception as exc:
        # ddgs reports blocked or empty engines as "No results found"; that's not a source error.
        if "no results" in str(exc).lower():
            return []
        raise
    return [
        _search_result(
            item.get("title", ""),
            item.get("href") or item.get("url") or "",
            item.get("body", "") or item.get("snippet", ""),
            item.get("date") or item.get("timestamp") or "",
        )
        for item in items
    ]


# Wikipedia's search needs every word to match, so question and filler words are dropped first.
_WIKIPEDIA_FILLER = {
    "a", "about", "an", "are", "current", "did", "do", "does", "find", "for", "how", "in", "is",
    "latest", "look", "me", "newest", "of", "on", "please", "recent", "search", "tell", "the",
    "to", "up", "was", "web", "were", "what", "when", "where", "which", "who", "why",
}


def _keyword_query(query: str) -> str:
    words = [word for word in re.findall(r"[\w.+#-]+", query) if word.lower() not in _WIKIPEDIA_FILLER]
    return " ".join(words) or query


def _search_wikipedia(query: str, max_results: int) -> list[dict[str, Any]]:
    lang = os.environ.get("WIKIPEDIA_LANG", "en")
    data = _get_json(
        f"https://{lang}.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": _keyword_query(query),
            "srlimit": max_results,
            "format": "json",
            "utf8": 1,
        },
    )
    return [
        _search_result(
            f"{hit['title']} - Wikipedia",
            f"https://{lang}.wikipedia.org/wiki/{quote(hit['title'].replace(' ', '_'))}",
            html.unescape(re.sub(r"<[^>]+>", "", hit.get("snippet", ""))),
            hit.get("timestamp", ""),
        )
        for hit in data.get("query", {}).get("search", [])
    ]


_SEARCH_SOURCES: dict[str, Callable[[str, int], list[dict[str, Any]]]] = {
    "searxng": _search_searxng,
    "brave": _search_brave,
    "ddgs": _search_ddgs,
    "wikipedia": _search_wikipedia,
}


def _source_setup_hint(name: str) -> str:
    """Empty when the source can be used, otherwise what it needs."""

    if name == "searxng" and not os.environ.get("SEARXNG_URL"):
        return "set SEARXNG_URL"
    if name == "brave" and not os.environ.get("BRAVE_SEARCH_API_KEY"):
        return "set BRAVE_SEARCH_API_KEY"
    if name == "ddgs" and DDGS is None:
        return "pip install ddgs"
    return ""


def search_sources_status() -> list[dict[str, Any]]:
    """Search sources in the order search_web tries them, with setup and cooldown state."""

    now = time.monotonic()
    order = os.environ.get("SEARCH_SOURCES", DEFAULT_SEARCH_ORDER)
    status = []
    for name in dict.fromkeys(part.strip().lower() for part in order.split(",")):
        if name not in _SEARCH_SOURCES:
            continue
        hint = _source_setup_hint(name)
        status.append(
            {
                "name": name,
                "label": _SOURCE_LABELS[name],
                "available": not hint,
                "setup": hint,
                "cooldown_seconds": max(0, int(_cooldown_until.get(name, 0) - now)),
            }
        )
    return status


@_ExpiringCache(SEARCH_CACHE_SECONDS, 64)
def _search_web_cached(query: str, max_results: int) -> tuple[str, ...]:
    """Search with automatic switching between sources and cache successful queries."""

    available = [source for source in search_sources_status() if source["available"]]
    if not available:
        raise RuntimeError("No search source is available. Set SEARXNG_URL or BRAVE_SEARCH_API_KEY, or install ddgs.")
    ready = [source for source in available if not source["cooldown_seconds"]] or available

    logger.info("Running web search query=%r max_results=%s sources=%s", query, max_results, [s["name"] for s in ready])
    problems: list[str] = []
    for source in ready:
        name = source["name"]
        try:
            results = [item for item in _SEARCH_SOURCES[name](query, max_results) if item.get("url")]
        except Exception as exc:
            _cooldown_until[name] = time.monotonic() + SEARCH_COOLDOWN_SECONDS
            problems.append(f"{name}: {exc}")
            record_event("search_source_failure", f"{name} search failed", source=name, error=str(exc))
            logger.warning("Search source %s failed query=%r error=%s; switching to the next source", name, query, exc)
            continue
        if not results:
            problems.append(f"{name}: no results")
            logger.info("Search source %s found nothing query=%r; switching to the next source", name, query)
            continue
        _cooldown_until.pop(name, None)
        for item in results:
            item["search_source"] = name
        logger.info("Web search completed query=%r source=%s result_count=%s", query, name, len(results))
        return tuple(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in results[:max_results])

    raise RuntimeError("No results found (" + "; ".join(problems) + ")")


def search_web(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search the web, switching automatically between the configured sources."""

    return [json.loads(item) for item in _search_web_cached(query.strip(), int(max_results))]


def _extract_with_beautifulsoup(html: str) -> dict[str, Any]:
    if BeautifulSoup is None:
        cleaned = clean_text(re.sub(r"<[^>]+>", " ", html))
        return {
            "title": "",
            "headings": [],
            "paragraphs": [],
            "lists": [],
            "code_blocks": [],
            "links": [],
            "text": cleaned,
        }

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


@_ExpiringCache(PAGE_CACHE_SECONDS, 128, keep=lambda value: '"success": true' in value)
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
        "retrieved_at": _utc_now(),
        "published": "",
        "canonical_url": canonical_url(url),
    }

    try:
        # URLs come from search results and links on other pages: refuse local/private addresses,
        # including ones reached through redirects.
        response = None
        for attempt in range(2):
            _wait_for_host(url)
            try:
                response = safe_get(url, session=_http_session(), timeout=timeout)
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise
                time.sleep(1.0)  # one retry for a dropped or slow connection
                continue
            if response.status_code in _RETRY_STATUS and not attempt:
                time.sleep(_retry_wait(response.headers.get("Retry-After")))
                continue
            break
        assert response is not None
        response.raise_for_status()
        html = response.text
        output["published"] = _published_date(html)

        soup_payload = _extract_with_beautifulsoup(html)
        output.update(soup_payload)

        if trafilatura is not None:
            extracted = trafilatura.extract(
                html,
                include_links=True,
                include_tables=True,
                include_comments=False,
                # Without formatting, trafilatura drops headings, e.g. "Version 1.67.0 (latest)"
                # on Streamlit's release notes, so the answer never reached the model.
                include_formatting=True,
            )
            if extracted:
                output["text"] = clean_text(_flatten_markdown(extracted))

        output["excerpt"] = output["text"][:1500]
        output["success"] = bool(output["text"])
        logger.info("Scraped url=%s success=%s chars=%s", url, output["success"], len(output["text"]))
    except Exception as exc:
        output["error"] = str(exc)
        logger.warning("Scrape failed url=%s error=%s", url, exc)

    return json.dumps(output, ensure_ascii=False)


def _published_date(html: str) -> str:
    """When the page says it was published or last changed (YYYY-MM-DD), or "" when it does not say."""

    if trafilatura is not None:
        try:
            metadata = trafilatura.extract_metadata(html)
            date = getattr(metadata, "date", None) if metadata is not None else None
            if date:
                return str(date)[:10]
        except Exception:
            pass
    match = re.search(
        r'<meta[^>]+(?:property|name|itemprop)=["\'](?:article:(?:published|modified)_time|date|datePublished|dateModified|last-modified)["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
        html or "",
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


_FRESHNESS_WORDS = re.compile(r"\b(?:latest|newest|current(?:ly)?|today|now|recent(?:ly)?|this (?:week|month|year)|up[- ]to[- ]date)\b", re.IGNORECASE)


def staleness_note(query: str, scraped_pages: list[dict[str, Any]], today: datetime | None = None) -> str:
    """A caution when the question is about what is current and the sources are old or undated."""

    if not _FRESHNESS_WORDS.search(query or ""):
        return ""
    dates = sorted(str(page.get("published") or "")[:10] for page in scraped_pages if page.get("success") and page.get("published"))
    if not dates:
        if not any(page.get("success") for page in scraped_pages):
            return ""
        return "\n\nNote: none of the pages state when they were published, so this may not be the current situation."
    newest = dates[-1]
    try:
        age_days = ((today or datetime.now()) - datetime.fromisoformat(newest)).days
    except ValueError:
        return ""
    if age_days > 365:
        return f"\n\nNote: the newest dated page is from {newest}, over a year old; the current situation may differ."
    return ""


def scrape_url(url: str, timeout: int = 8) -> dict[str, Any]:
    """Scrape a URL into readable text and structured page parts."""

    return json.loads(_scrape_url_cached(url, int(timeout)))


def _fenced_context(pieces: list[str], label: str) -> tuple[str, str]:
    """The web text for a prompt: lines aimed at the model removed, the rest fenced. Returns (block, note)."""

    cleaned = []
    removed = 0
    for piece in pieces:
        text, count = defuse_untrusted_text(piece)
        removed += count
        if text.strip():
            cleaned.append(text)
    return fence_untrusted("\n\n".join(cleaned), label), removed_note(removed)


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
            published = f"Published: {page.get('published')}\n" if page.get("published") else ""
            source_blocks.append(
                f"SCRAPED PAGE {idx}: {page.get('title')}\n"
                f"URL: {page.get('url')}\n"
                f"{published}"
                f"TEXT EXCERPT: {page.get('excerpt', '')}\n"
            )

    research_context, note = _fenced_context(source_blocks, "web research")

    return f"""
You are Cognitive Nexus Web Research.

{UNTRUSTED_RULE}

User query:
{query}

Research context:
{research_context}
{note}

Write a useful answer with:
1. Direct answer
2. Key findings
3. Source list
4. Uncertainty or limitations
5. Suggested next steps if useful

Base the answer on the research context above, which is newer than your training data.
Only list sources whose URLs appear in the research context. If the context does not
answer the question, say so instead of answering from memory.
"""


NO_RESULTS_SUMMARY = (
    "Web search returned no results, so no summary was written. Search engines sometimes "
    "block or rate-limit automated searches for a few minutes; try again shortly."
)


def _has_research_sources(results: list[dict[str, Any]], scraped_pages: list[dict[str, Any]]) -> bool:
    return bool(results) or any(page.get("success") for page in scraped_pages)


# Brief mode is for chat: a local CPU model reads ~30 tokens/s and writes ~3 tokens/s, so the
# prompt and answer must stay small for a reply in about a minute.
BRIEF_MAX_PAGES = 2
BRIEF_PAGE_CHARS = 600
BRIEF_SNIPPET_CHARS = 300


def _relevant_excerpt(text: str, query: str, max_chars: int = BRIEF_PAGE_CHARS) -> str:
    """Return the sentences of a page that mention the query terms, in page order."""

    terms = {word for word in re.findall(r"[a-z0-9][a-z0-9.]*", query.lower()) if len(word) > 2}
    # Split only where the next word is capitalized, so "Oct. 25, 2026" or "v3.15. 2" stay together.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", text or "") if s.strip()]
    scored = [(sum(term in s.lower() for term in terms), i) for i, s in enumerate(sentences)]
    chosen: list[int] = []
    size = 0
    for score, i in sorted(scored, key=lambda item: (-item[0], item[1])):
        if score == 0 or size >= max_chars:
            break
        chosen.append(i)
        size += len(sentences[i]) + 1
    if not chosen:
        return (text or "")[:max_chars]
    return " ".join(sentences[i] for i in sorted(chosen))[:max_chars]


def _build_brief_prompt(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
) -> str:
    blocks = [
        f"[{idx}] {r.get('title', '')}: {_shorten(str(r.get('snippet', '')), BRIEF_SNIPPET_CHARS)}"
        for idx, r in enumerate(results, 1)
    ]
    for page in scraped_pages:
        if page.get("success"):
            blocks.append(f"PAGE {page.get('title') or page.get('url')}: {_relevant_excerpt(page.get('text', ''), query)}")
    context, note = _fenced_context(blocks, "web results")
    return f"""Question: {query}

{UNTRUSTED_RULE}

Fresh web results (newer than your training data):
{context}
{note}

Answer the question in 2-3 short sentences using only these web results. Include dates or
version numbers when relevant. Do not list sources or URLs; the app shows them. If the results
do not contain the answer, begin with "The web results do not say" and name what is missing;
do not offer other facts in its place.
"""


# Version-like numbers ("1.28.0", "v3.15", "v14") and years. A small local model sometimes fills
# these in from its training data when the sources don't contain them.
_FACT_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)+|\b[vV]\d+\b(?!\.\d)|\b(?:19|20)\d{2}\b")


def unsourced_numbers(answer: str, source_text: str) -> list[str]:
    """Version numbers and years in the answer that don't appear anywhere in the source text."""

    return [token for token in dict.fromkeys(_FACT_NUMBER.findall(answer or "")) if token not in (source_text or "")]


def unsourced_numbers_note(answer: str, source_text: str) -> str:
    """Warning to append when the answer states numbers its sources don't contain, else ""."""

    missing = unsourced_numbers(answer, source_text)
    if not missing:
        return ""
    return (
        f"\n\n⚠️ Not found in the sources: {', '.join(missing)}. This may come from the model's older "
        "training data, so double-check it."
    )


_LINK_IN_TEXT = re.compile(r"https?://[^\s<>()\[\]\"'`]+")


def unlisted_links(answer: str, source_text: str) -> list[str]:
    """Links in the answer that appear nowhere in what the model was given.

    A model asked for a source list sometimes writes a plausible address instead of copying one.
    Addresses are compared without tracking parameters, fragments or a trailing slash. The front
    page or a parent folder of a retrieved page is accepted; another page on the same site is not.
    """

    known = {canonical_url(link.rstrip(".,;:!?*_")) for link in _LINK_IN_TEXT.findall(source_text or "")}
    found: list[str] = []
    for raw in _LINK_IN_TEXT.findall(answer or ""):
        link = raw.rstrip(".,;:!?*_")
        address = canonical_url(link)
        # The front page or a parent folder of a retrieved page is that site, not an invention.
        parent_of_known = any(source.startswith(address.rstrip("/") + "/") for source in known) and "?" not in address
        if address not in known and not parent_of_known and link not in found:
            found.append(link)
    return found


def unlisted_links_note(answer: str, source_text: str) -> str:
    """Warning to append when the answer cites links that were not retrieved, else ""."""

    missing = unlisted_links(answer, source_text)
    if not missing:
        return ""
    return (
        f"\n\n⚠️ Not among the pages that were retrieved: {', '.join(missing[:5])}. "
        "The model may have made these links up, so do not rely on them."
    )


def summarize_research_result(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
    ai_callback: Callable[[str], str] | None = None,
    brief: bool = False,
) -> tuple[str, bool]:
    """Summarize research with the active provider callback.

    Returns (text, generated). `generated` is True only when a model wrote the text. The other
    outcomes (no sources, no provider, the model failed) return a plain statement of what
    happened, which must not be stored or presented as a research summary.

    Version numbers, years or links the model wrote that aren't in its sources get a warning appended.
    """

    if not _has_research_sources(results, scraped_pages):
        # Without sources the model would only answer from (possibly stale) memory and
        # invent a source list, which then gets saved as if it were research.
        return NO_RESULTS_SUMMARY, False

    if ai_callback is None:
        return (
            "AI summarization is unavailable because no active provider was found.\n\n"
            "Raw research results were collected successfully."
        ), False

    try:
        prompt = build_summary_prompt(query, results, scraped_pages, brief=brief)
        summary = str(ai_callback(prompt) or "").strip()
    except Exception as exc:
        logger.warning("Research summarization failed query=%r error=%s", query, exc)
        return f"AI summarization failed: {exc}\n\nThe pages that were found are listed below.", False
    if not summary:
        return "AI summarization returned no text. The pages that were found are listed below.", False
    logger.info("Research summary generated query=%r chars=%s", query, len(summary))
    notes = unsourced_numbers_note(summary, prompt) + unlisted_links_note(summary, prompt) + staleness_note(query, scraped_pages)
    return summary + notes, True


def summarize_research(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
    ai_callback: Callable[[str], str] | None = None,
    brief: bool = False,
) -> str:
    """The text of summarize_research_result, for callers that only show it."""

    return summarize_research_result(query, results, scraped_pages, ai_callback, brief=brief)[0]


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
    atomic_write_text(json_path, json.dumps(payload, indent=2, ensure_ascii=False))

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

    atomic_write_text(md_path, "\n".join(md))
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


def build_summary_prompt(
    query: str,
    results: list[dict[str, Any]],
    scraped_pages: list[dict[str, Any]],
    brief: bool = False,
) -> str:
    """Prompt for summarizing research: brief chat answer or full report."""

    return (_build_brief_prompt if brief else _build_research_prompt)(query, results, scraped_pages)


def gather_research(
    query: str,
    *,
    max_results: int = 5,
    scrape_pages: bool = True,
    brief: bool = False,
) -> dict[str, Any]:
    """Search and scrape. Returns results, scraped pages, errors and stage timings.

    brief=True (chat mode) scrapes only the top pages.
    """

    started = time.perf_counter()
    timings: dict[str, float] = {}
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    scraped_pages: list[dict[str, Any]] = []

    try:
        results = search_web(query, max_results=max_results)
    except Exception as exc:
        errors.append(f"Search failed: {exc}")
        logger.warning("Search failed query=%r error=%s", query, exc)
    timings["search"] = time.perf_counter() - started

    if scrape_pages:
        # The same page often appears twice in results under addresses that differ only in
        # tracking parameters; fetch it once.
        urls = list({canonical_url(str(result.get("url"))): str(result.get("url")) for result in results if result.get("url")}.values())
        if brief:
            urls = urls[:BRIEF_MAX_PAGES]
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
    timings["scrape"] = time.perf_counter() - started - timings["search"]
    # Keep the pages in the order of the search results, and mark copies of the same text on
    # several sites: a syndicated article is one source, not several.
    order = {canonical_url(str(result.get("url"))): index for index, result in enumerate(results)}
    scraped_pages.sort(key=lambda page: order.get(canonical_url(str(page.get("url"))), len(order)))
    seen_text: dict[str, str] = {}
    for page in scraped_pages:
        if not page.get("success"):
            continue
        fingerprint = hashlib.sha1(re.sub(r"\W+", " ", str(page.get("text", "")).lower())[:4000].encode("utf-8")).hexdigest()
        if fingerprint in seen_text:
            page["duplicate_of"] = seen_text[fingerprint]
        else:
            seen_text[fingerprint] = str(page.get("url"))

    return {
        "query": query,
        "brief": brief,
        "results": results,
        "scraped_pages": scraped_pages,
        "errors": errors,
        "timings": timings,
        "started": started,
        "has_sources": _has_research_sources(results, scraped_pages),
    }


def finish_research_session(
    gathered: dict[str, Any],
    summary: str,
    *,
    settings: dict[str, Any],
    save_locally: bool = True,
    save_to_memory: bool = True,
    summary_generated: bool = True,
) -> dict[str, Any]:
    """Store the summary in memory, log stage timings and save the session to disk.

    summary_generated=False means `summary` is a notice (the model failed, was skipped or was
    not available), not a model's summary. The pages are still stored; the notice is not.
    """

    query = gathered["query"]
    results = gathered["results"]
    scraped_pages = gathered["scraped_pages"]
    errors = gathered["errors"]
    timings = dict(gathered["timings"])
    started = gathered["started"]
    saved_paths: dict[str, str] = {}
    memory_result: dict[str, Any] = {}
    timings.setdefault("summary", time.perf_counter() - started - sum(timings.values()))

    settings = {**settings, "summary_generated": bool(summary_generated)}
    if save_to_memory and gathered["has_sources"]:
        memory_result = add_research_to_memory(query, scraped_pages, summary if summary_generated else "")
    timings["memory"] = time.perf_counter() - started - sum(timings.values())
    logger.info(
        "Research timings query=%r brief=%s %s total=%.1fs",
        query,
        gathered["brief"],
        " ".join(f"{name}={seconds:.1f}s" for name, seconds in timings.items()),
        time.perf_counter() - started,
    )

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
        "summary_generated": bool(summary_generated),
        "errors": errors,
        "saved_paths": saved_paths,
        "memory_result": memory_result,
    }


def run_research_session(
    query: str,
    *,
    max_results: int = 5,
    scrape_pages: bool = True,
    summarize_with_ai: bool = True,
    save_locally: bool = True,
    save_to_memory: bool = True,
    ai_callback: Callable[[str], str] | None = None,
    brief: bool = False,
) -> dict[str, Any]:
    """Run a full search/scrape/summarize/save session.

    brief=True is the chat mode: scrape only the top pages and ask for a 2-3 sentence answer.
    """

    settings = {
        "max_results": max_results,
        "scrape_pages": scrape_pages,
        "summarize_with_ai": summarize_with_ai,
        "save_locally": save_locally,
        "save_to_memory": save_to_memory,
        "brief": brief,
    }
    gathered = gather_research(query, max_results=max_results, scrape_pages=scrape_pages, brief=brief)
    summary_started = time.perf_counter()
    if summarize_with_ai:
        summary, generated = summarize_research_result(
            query, gathered["results"], gathered["scraped_pages"], ai_callback, brief=brief
        )
    else:
        summary, generated = "AI summarization was skipped for this research session.", False
    gathered["timings"]["summary"] = time.perf_counter() - summary_started

    return finish_research_session(
        gathered,
        summary,
        settings=settings,
        save_locally=save_locally,
        save_to_memory=save_to_memory,
        summary_generated=generated,
    )
