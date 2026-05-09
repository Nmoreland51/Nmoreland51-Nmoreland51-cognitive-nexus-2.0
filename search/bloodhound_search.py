"""Deep public-web search mode for Cognitive Nexus chat."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from modules.web_research import clean_text, get_domain, scrape_url, search_web, slugify_query
from search.onion_search import run_onion_search


logger = logging.getLogger(__name__)

SEARCH_HISTORY_DIR = Path("data/search_history")
CACHE_DIR = Path("data/search_cache")
SUSPICIOUS_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".ps1",
    ".scr",
    ".msi",
    ".jar",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".iso",
    ".apk",
}


@dataclass
class BloodhoundConfig:
    """Runtime knobs for one Bloodhound search."""

    enabled: bool = True
    depth: str = "Standard"
    max_results: int = 25
    timeout_seconds: int = 20
    enable_cache: bool = True
    cache_ttl_hours: int = 24
    follow_links: bool = True
    link_depth: int = 1
    enable_onion: bool = False
    tor_socks_proxy: str = "127.0.0.1:9050"
    save_history: bool = True


@dataclass
class BloodhoundResult:
    """Ranked search result with optional fetched-page evidence."""

    title: str
    url: str
    source: str
    source_type: str = "public_web"
    snippet: str = ""
    timestamp: str = ""
    match_strength: str = "Low"
    score: float = 0.0
    why_it_matters: str = ""
    matched_terms: list[str] = field(default_factory=list)
    fetched: bool = False
    fetch_error: str = ""
    page_title: str = ""
    excerpt: str = ""
    links_followed_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bool_from_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def int_from_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


def default_bloodhound_config(overrides: dict[str, Any] | None = None) -> BloodhoundConfig:
    """Build config from environment plus UI/runtime overrides."""

    config = BloodhoundConfig(
        enabled=bool_from_env("ENABLE_BLOODHOUND_SEARCH", True),
        enable_onion=bool_from_env("ENABLE_ONION_SEARCH", False),
        tor_socks_proxy=os.environ.get("TOR_SOCKS_PROXY", "127.0.0.1:9050"),
        max_results=int_from_env("MAX_SEARCH_RESULTS", 50),
        timeout_seconds=int_from_env("SEARCH_TIMEOUT_SECONDS", 20),
        enable_cache=bool_from_env("ENABLE_SEARCH_CACHE", True),
        cache_ttl_hours=int_from_env("SEARCH_CACHE_TTL_HOURS", 24),
        follow_links=bool_from_env("ENABLE_LINK_FOLLOWING", True),
    )
    for key, value in (overrides or {}).items():
        if hasattr(config, key):
            setattr(config, key, value)
    config.depth = str(config.depth or "Standard").title()
    config.max_results = max(1, min(int(config.max_results), 150))
    config.timeout_seconds = max(4, min(int(config.timeout_seconds), 60))
    return config


def detect_bloodhound_query(message: str) -> str:
    """Return the search query if a chat turn requests Bloodhound Search Mode."""

    text = re.sub(r"\s+", " ", (message or "").strip())
    lowered = text.lower()
    patterns = [
        r"^bloodhound search\s+(.+)$",
        r"^deep search\s+(.+)$",
        r"^internet scan\s+(.+)$",
        r"^trace mentions of\s+(.+)$",
        r"^find every mention of\s+(.+)$",
        r"^find mentions of\s+(.+)$",
        r"^find sources for\s+(.+)$",
        r"^search for\s+(.+)$",
        r"^find\s+(.+)$",
        r"^look up\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, lowered, flags=re.IGNORECASE)
        if match:
            start, end = match.span(1)
            return text[start:end].strip(" .:")
    return ""


def depth_limits(depth: str, max_results: int) -> dict[str, int]:
    depth = (depth or "Standard").title()
    if depth == "Quick":
        return {"queries": 4, "results": min(max_results, 10), "fetch": min(max_results, 6), "links": 0}
    if depth == "Deep":
        return {"queries": 12, "results": min(max_results, 75), "fetch": min(max_results, 30), "links": 18}
    if depth == "Extreme":
        return {"queries": 18, "results": min(max_results, 150), "fetch": min(max_results, 50), "links": 35}
    return {"queries": 8, "results": min(max_results, 25), "fetch": min(max_results, 14), "links": 10}


def expand_query(query: str, depth: str = "Standard") -> list[str]:
    """Generate exact, variant, and source-specific search queries."""

    cleaned = clean_text(query)
    if not cleaned:
        return []
    variants: list[str] = []
    base_terms = [cleaned, cleaned.lower(), cleaned.upper()]
    quoted = f'"{cleaned}"'
    compact = re.sub(r"[\s_\\-]+", "", cleaned)
    spaced = re.sub(r"[_\\-\\.]+", " ", cleaned)
    username = cleaned.strip().lstrip("@")
    source_queries = [
        f'{quoted}',
        f'{quoted} OR {cleaned}',
        f'{cleaned} site:github.com',
        f'{cleaned} site:reddit.com',
        f'{cleaned} site:stackoverflow.com',
        f'{cleaned} site:news.ycombinator.com',
        f'{cleaned} site:archive.org',
    ]
    for candidate in base_terms + [quoted, compact, spaced, username, f"@{username}"] + source_queries:
        candidate = clean_text(candidate)
        if candidate and candidate not in variants:
            variants.append(candidate)
    limit = depth_limits(depth, 150)["queries"]
    return variants[:limit]


def normalize_url(url: str) -> str:
    """Normalize URLs for deduplication without changing the destination host/path."""

    try:
        parsed = urlparse(url.strip())
        if not parsed.scheme or not parsed.netloc:
            return url.strip()
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith(("utm_", "fbclid", "gclid"))
        ]
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower().replace("www.", ""),
                parsed.path.rstrip("/") or "/",
                "",
                urlencode(query),
                "",
            )
        )
    except Exception:
        return url.strip()


def should_fetch_url(url: str) -> tuple[bool, str]:
    """Allow ordinary public pages; skip risky/download/control URLs gracefully."""

    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return False, "Unsupported URL scheme."
    if parsed.hostname and parsed.hostname.endswith(".onion"):
        return False, "Onion URLs require the optional onion module."
    suffix = Path(parsed.path.lower()).suffix
    if suffix in SUSPICIOUS_EXTENSIONS:
        return False, f"Skipped downloadable or executable file type: {suffix}"
    return True, ""


def _match_terms(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_@.\\-]{3,}", query.lower())
    return list(dict.fromkeys(terms))


def _matching_snippet(text: str, terms: list[str], fallback: str = "", radius: int = 220) -> str:
    haystack = text or ""
    lowered = haystack.lower()
    best_pos = -1
    for term in terms:
        pos = lowered.find(term.lower())
        if pos >= 0:
            best_pos = pos
            break
    if best_pos < 0:
        return clean_text(fallback)[:500]
    start = max(0, best_pos - radius)
    end = min(len(haystack), best_pos + radius)
    return clean_text(haystack[start:end])[:700]


def _score_result(result: dict[str, Any], query: str, page: dict[str, Any] | None = None) -> BloodhoundResult:
    terms = _match_terms(query)
    title = clean_text(result.get("title", ""))
    url = str(result.get("url", ""))
    snippet = clean_text(result.get("snippet", ""))
    source = result.get("source") or get_domain(url)
    page_text = clean_text((page or {}).get("text", ""))
    title_l = title.lower()
    snippet_l = snippet.lower()
    page_l = page_text.lower()
    query_l = clean_text(query).lower()

    score = 0.0
    matched_terms: list[str] = []
    if query_l and query_l in title_l:
        score += 45
    if query_l and query_l in snippet_l:
        score += 35
    if query_l and query_l in page_l:
        score += 50
    for term in terms:
        term_score = 0.0
        if term in title_l:
            term_score += 12
        if term in snippet_l:
            term_score += 8
        if term in page_l:
            term_score += 10
        if term_score:
            matched_terms.append(term)
            score += term_score
    if source in {"github.com", "stackoverflow.com", "reddit.com", "archive.org", "news.ycombinator.com"}:
        score += 4
    if str(result.get("source_type", "")).startswith("onion"):
        score -= 12
    if result.get("timestamp"):
        score += 2

    if score >= 55:
        strength = "High"
    elif score >= 22:
        strength = "Medium"
    else:
        strength = "Low"

    excerpt = _matching_snippet(page_text, terms, snippet)
    why = "Exact or strong term match in title/snippet/page text." if strength == "High" else (
        "Partial term overlap across available source text." if strength == "Medium" else "Weak mention or related result; verify before relying on it."
    )
    source_type = result.get("source_type", "public_web")
    why_prefix = "Secondary onion source; not prioritized over public web. " if str(source_type).startswith("onion") else ""
    return BloodhoundResult(
        title=title or (page or {}).get("title", "") or url,
        url=url,
        source=source,
        source_type=source_type,
        snippet=snippet,
        timestamp=str(result.get("timestamp", "")),
        match_strength=strength,
        score=round(score, 2),
        why_it_matters=why_prefix + why,
        matched_terms=matched_terms,
        fetched=bool(page and page.get("success")),
        fetch_error=str((page or {}).get("error", "")),
        page_title=str((page or {}).get("title", "")),
        excerpt=excerpt,
        links_followed_from=str(result.get("links_followed_from", "")),
    )


def _cache_key(query: str, config: BloodhoundConfig) -> Path:
    slug = slugify_query(f"{query}_{config.depth}_{config.max_results}", 90)
    return CACHE_DIR / f"{slug}.json"


def _read_cache(query: str, config: BloodhoundConfig) -> dict[str, Any] | None:
    if not config.enable_cache:
        return None
    path = _cache_key(query, config)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(payload.get("created_at", ""))
        age_hours = (datetime.now() - created).total_seconds() / 3600
        if age_hours <= config.cache_ttl_hours:
            payload["cache_hit"] = True
            return payload
    except Exception:
        return None
    return None


def _write_cache(query: str, config: BloodhoundConfig, payload: dict[str, Any]) -> None:
    if not config.enable_cache:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_key(query, config)
        cache_payload = dict(payload)
        cache_payload["created_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(cache_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.info("Bloodhound cache write failed: %s", exc)


def _search_variants(queries: list[str], per_query: int, errors: list[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(queries)))) as executor:
        future_to_query = {executor.submit(search_web, query, per_query): query for query in queries}
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                for item in future.result():
                    item["query_variant"] = query
                    found.append(item)
            except Exception as exc:
                errors.append(f"Search failed for {query!r}: {exc}")
    return found


def _dedupe_results(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []
    removed = 0
    for item in results:
        url = str(item.get("url", ""))
        title = clean_text(item.get("title", "")).lower()
        norm = normalize_url(url)
        title_key = re.sub(r"[^a-z0-9]+", "", title)[:90]
        if not url or norm in seen_urls or (title_key and title_key in seen_titles):
            removed += 1
            continue
        seen_urls.add(norm)
        if title_key:
            seen_titles.add(title_key)
        item["normalized_url"] = norm
        deduped.append(item)
    return deduped, removed


def _fetch_pages(results: list[dict[str, Any]], fetch_limit: int, timeout: int, errors: list[str]) -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    candidates = []
    for item in results[:fetch_limit]:
        allowed, reason = should_fetch_url(str(item.get("url", "")))
        if allowed:
            candidates.append(item)
        else:
            errors.append(f"Skipped {item.get('url')}: {reason}")
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as executor:
        future_to_url = {
            executor.submit(scrape_url, str(item["url"]), min(timeout, 12)): str(item["url"])
            for item in candidates
            if item.get("url")
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                pages[url] = future.result()
            except Exception as exc:
                pages[url] = {"url": url, "success": False, "error": str(exc)}
                errors.append(f"Fetch failed for {url}: {exc}")
    return pages


def _score_and_merge_onion(
    *,
    query: str,
    config: BloodhoundConfig,
    ranked: list[BloodhoundResult],
    errors: list[str],
    progress: Callable[[str], None],
) -> tuple[list[BloodhoundResult], dict[str, Any], int]:
    """Search onion sources as a secondary lane and merge without prioritizing them."""

    if not config.enable_onion:
        return ranked, {
            "status": {
                "available": False,
                "enabled": False,
                "proxy": config.tor_socks_proxy,
                "message": "Onion search is disabled or unavailable. Continuing with public web sources.",
            },
            "results": [],
            "pages": {},
            "errors": [],
        }, 0

    progress("Searching secondary onion sources")
    onion_limit = max(3, min(20, config.max_results // 4))
    onion_payload = run_onion_search(
        query,
        enabled=True,
        proxy=config.tor_socks_proxy,
        max_results=onion_limit,
        timeout=min(config.timeout_seconds, 15),
        fetch_pages=True,
    )
    errors.extend(onion_payload.get("errors", []))
    onion_pages = onion_payload.get("pages", {}) or {}
    onion_results = []
    for item in onion_payload.get("results", []):
        item = dict(item)
        item["source_type"] = item.get("source_type") or "onion_index"
        scored = _score_result(item, query, onion_pages.get(str(item.get("url", ""))))
        onion_results.append(scored)
    if not onion_results:
        return ranked, onion_payload, 0

    merged = ranked + onion_results
    merged.sort(key=lambda item: item.score, reverse=True)
    seen: set[str] = set()
    unique: list[BloodhoundResult] = []
    duplicates = 0
    for item in merged:
        norm = normalize_url(item.url)
        if norm in seen:
            duplicates += 1
            continue
        seen.add(norm)
        unique.append(item)
    return unique, onion_payload, duplicates


def _candidate_links(page: dict[str, Any], query: str, limit: int) -> list[str]:
    source_url = str(page.get("url", ""))
    source_domain = get_domain(source_url)
    terms = _match_terms(query)
    links: list[str] = []
    for link in page.get("links", []) or []:
        href = str(link.get("href", ""))
        text = clean_text(link.get("text", ""))
        absolute = urljoin(source_url, href)
        if get_domain(absolute) != source_domain:
            continue
        if not any(term in f"{text} {absolute}".lower() for term in terms):
            continue
        allowed, _reason = should_fetch_url(absolute)
        if allowed and normalize_url(absolute) not in {normalize_url(item) for item in links}:
            links.append(absolute)
        if len(links) >= limit:
            break
    return links


def _follow_links(
    ranked: list[BloodhoundResult],
    pages: dict[str, dict[str, Any]],
    query: str,
    link_limit: int,
    timeout: int,
    errors: list[str],
) -> list[BloodhoundResult]:
    if link_limit <= 0:
        return []
    links_to_fetch: list[dict[str, Any]] = []
    for result in ranked:
        if result.match_strength == "Low":
            continue
        for link in _candidate_links(pages.get(result.url, {}), query, max(1, link_limit // 3)):
            links_to_fetch.append(
                {
                    "title": link,
                    "url": link,
                    "snippet": "",
                    "source": get_domain(link),
                    "source_type": "followed_link",
                    "links_followed_from": result.url,
                }
            )
            if len(links_to_fetch) >= link_limit:
                break
        if len(links_to_fetch) >= link_limit:
            break
    followed_pages = _fetch_pages(links_to_fetch, len(links_to_fetch), timeout, errors)
    return [_score_result(item, query, followed_pages.get(str(item.get("url", "")))) for item in links_to_fetch]


def _summarize_locally(query: str, ranked: list[BloodhoundResult]) -> str:
    best = [item for item in ranked if item.match_strength == "High"][:3]
    medium = [item for item in ranked if item.match_strength == "Medium"][:3]
    if best:
        return f"Found {len(best)} high-confidence match(es) for {query!r}, plus {len(medium)} medium-confidence supporting result(s)."
    if medium:
        return f"Found {len(medium)} medium-confidence match(es) for {query!r}. No high-confidence exact match was confirmed."
    if ranked:
        return f"Found {len(ranked)} weak or related result(s), but no confirmed strong match for {query!r}."
    return f"No public-web matches were found for {query!r}."


def _build_ai_prompt(query: str, ranked: list[BloodhoundResult], coverage: dict[str, Any]) -> str:
    blocks = []
    for index, item in enumerate(ranked[:12], 1):
        blocks.append(
            f"[{index}] {item.title}\n"
            f"URL: {item.url}\n"
            f"Strength: {item.match_strength}\n"
            f"Score: {item.score}\n"
            f"Snippet: {item.excerpt or item.snippet}\n"
        )
    return (
        "You are Cognitive Nexus Bloodhound Search Mode. Summarize only the supplied sources. "
        "Do not invent sources, timestamps, or claims.\n\n"
        f"Query: {query}\n\n"
        f"Coverage: {json.dumps(coverage, ensure_ascii=False)}\n\n"
        "Ranked evidence:\n"
        + "\n".join(blocks)
        + "\n\nWrite: Summary, confirmed matches, weak/possible matches, uncertainty, final answer."
    )


def format_bloodhound_markdown(payload: dict[str, Any]) -> str:
    """Format a complete Bloodhound payload for chat or saved markdown."""

    query = payload.get("query", "")
    ranked = payload.get("ranked_results", [])
    best = [item for item in ranked if item.get("match_strength") in {"High", "Medium"}]
    weak = [item for item in ranked if item.get("match_strength") == "Low"]
    coverage = payload.get("coverage", {})
    lines = [
        f'## Bloodhound Search Results for: "{query}"',
        "",
        "### Summary",
        payload.get("summary", ""),
        "",
        "### Best Matches",
    ]
    if not best:
        lines.append("No high or medium confidence matches were found.")
    for index, item in enumerate(best[:12], 1):
        lines.extend(
            [
                f"{index}. **{item.get('title') or item.get('url')}**",
                f"   URL: {item.get('url')}",
                f"   Source type: {item.get('source_type', 'public_web')}",
                f"   Match strength: {item.get('match_strength')}",
                f"   Why it matters: {item.get('why_it_matters')}",
                f"   Relevant snippet: {item.get('excerpt') or item.get('snippet')}",
                "",
            ]
        )
    lines.append("### Weak / Possible Matches")
    if not weak:
        lines.append("None separated as weak matches.")
    for item in weak[:10]:
        lines.append(f"- [{item.get('title') or item.get('url')}]({item.get('url')}) - {item.get('snippet') or item.get('excerpt')}")
    lines.extend(
        [
            "",
            "### Search Coverage",
            f"- Queries tried: {len(coverage.get('queries_tried', []))}",
            f"- Sources searched: {', '.join(coverage.get('sources_searched', [])) or 'public web'}",
            f"- Pages fetched: {coverage.get('pages_fetched', 0)}",
            f"- Duplicates removed: {coverage.get('duplicates_removed', 0)}",
            f"- Failed sources: {len(coverage.get('failed_sources', []))}",
            f"- Onion search status: {coverage.get('onion_status', 'disabled')}",
            "",
            "### Final Answer",
            payload.get("final_answer", payload.get("summary", "")),
        ]
    )
    if payload.get("saved_paths"):
        lines.extend(["", "### Saved", f"- JSON: `{payload['saved_paths'].get('json')}`", f"- Markdown: `{payload['saved_paths'].get('markdown')}`"])
    return "\n".join(lines).strip()


def save_bloodhound_session(payload: dict[str, Any]) -> dict[str, str]:
    """Save search payload to JSON and Markdown."""

    SEARCH_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify_query(payload.get("query", "search"), 70)
    base = SEARCH_HISTORY_DIR / f"search_{timestamp}_{slug}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    serializable = dict(payload)
    serializable.pop("saved_paths", None)
    json_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(format_bloodhound_markdown(serializable), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def run_bloodhound_search(
    query: str,
    *,
    config: BloodhoundConfig | None = None,
    ai_callback: Callable[[str], str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run query expansion, multi-source search, safe page fetching, ranking, and saving."""

    config = config or default_bloodhound_config()
    query = clean_text(query)
    errors: list[str] = []
    if not query:
        return {
            "query": query,
            "summary": "No search query was provided.",
            "final_answer": "No search query was provided.",
            "ranked_results": [],
            "coverage": {"failed_sources": ["empty query"], "onion_status": "not attempted"},
            "errors": ["Empty query."],
        }

    cached = _read_cache(query, config)
    if cached:
        cached["summary"] = cached.get("summary", "") + "\n\nCache hit: reused a recent Bloodhound search."
        return cached

    limits = depth_limits(config.depth, config.max_results)
    progress = progress_callback or (lambda _message: None)
    progress("Expanding query")
    queries = expand_query(query, config.depth)
    per_query = max(2, min(10, limits["results"] // max(1, len(queries)) + 1))

    progress("Searching sources")
    raw_results = _search_variants(queries, per_query, errors)
    raw_results, duplicates_removed = _dedupe_results(raw_results)
    raw_results = raw_results[: limits["results"]]

    progress("Fetching pages")
    pages = _fetch_pages(raw_results, limits["fetch"], config.timeout_seconds, errors)

    progress("Ranking results")
    ranked = [_score_result(item, query, pages.get(str(item.get("url", "")))) for item in raw_results]
    ranked.sort(key=lambda item: item.score, reverse=True)

    followed: list[BloodhoundResult] = []
    if config.follow_links and limits["links"] > 0:
        progress("Following relevant links")
        followed = _follow_links(ranked[:10], pages, query, limits["links"], config.timeout_seconds, errors)
        ranked.extend(followed)
        ranked.sort(key=lambda item: item.score, reverse=True)
        seen = set()
        unique_ranked = []
        for item in ranked:
            norm = normalize_url(item.url)
            if norm in seen:
                duplicates_removed += 1
                continue
            seen.add(norm)
            unique_ranked.append(item)
        ranked = unique_ranked[: limits["results"]]

    ranked, onion_payload, onion_duplicates = _score_and_merge_onion(
        query=query,
        config=config,
        ranked=ranked,
        errors=errors,
        progress=progress,
    )
    duplicates_removed += onion_duplicates
    ranked = ranked[: limits["results"]]
    onion_status = (onion_payload.get("status") or {}).get(
        "message",
        "Onion search is disabled or unavailable. Continuing with public web sources.",
    )

    coverage = {
        "queries_tried": queries,
        "sources_searched": [
            "DuckDuckGo/DDGS public web",
            "GitHub/Reddit/StackOverflow/site-specific query variants",
        ] + (["Ahmia/onion index secondary lane", "Tor SOCKS onion fetch"] if config.enable_onion else []),
        "urls_found": [item.get("url") for item in raw_results if item.get("url")],
        "onion_urls_found": [item.get("url") for item in onion_payload.get("results", []) if item.get("url")],
        "pages_fetched": sum(1 for page in pages.values() if page.get("success"))
        + sum(1 for page in (onion_payload.get("pages") or {}).values() if page.get("success")),
        "duplicates_removed": duplicates_removed,
        "failed_sources": errors,
        "onion_status": onion_status,
        "onion_enabled": bool(config.enable_onion),
        "onion_available": bool((onion_payload.get("status") or {}).get("available")),
        "depth": config.depth,
        "max_results": config.max_results,
        "link_following": bool(config.follow_links),
    }

    progress("Summarizing findings")
    local_summary = _summarize_locally(query, ranked)
    final_answer = local_summary
    if ai_callback and ranked:
        try:
            ai_summary = clean_text(ai_callback(_build_ai_prompt(query, ranked, coverage)))
            if ai_summary:
                final_answer = ai_summary
        except Exception as exc:
            errors.append(f"AI summary failed: {exc}")
    payload = {
        "query": query,
        "timestamp": datetime.now().isoformat(),
        "expanded_queries": queries,
        "config": asdict(config),
        "ranked_results": [item.to_dict() for item in ranked],
        "summary": local_summary,
        "final_answer": final_answer,
        "coverage": coverage,
        "errors": errors,
        "saved_paths": {},
    }
    if config.save_history:
        payload["saved_paths"] = save_bloodhound_session(payload)
    _write_cache(query, config, payload)
    return payload
