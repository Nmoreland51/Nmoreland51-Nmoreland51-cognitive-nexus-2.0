"""Optional secondary onion search for Bloodhound Search Mode."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

from modules.web_research import clean_text


@dataclass
class OnionSearchStatus:
    available: bool
    enabled: bool
    message: str
    proxy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_onion_status(*, enabled: bool, proxy: str = "127.0.0.1:9050") -> OnionSearchStatus:
    """Report optional onion availability without blocking public-web search."""

    if not enabled:
        return OnionSearchStatus(
            available=False,
            enabled=False,
            proxy=proxy,
            message="Onion search is disabled or unavailable. Continuing with public web sources.",
        )
    try:
        session = _tor_session(proxy)
        response = session.get("https://check.torproject.org/api/ip", timeout=8)
        if response.ok:
            return OnionSearchStatus(
                available=True,
                enabled=True,
                proxy=proxy,
                message="Onion search enabled. Tor proxy responded; onion sources will be searched after public web.",
            )
    except Exception as exc:
        return OnionSearchStatus(
            available=False,
            enabled=True,
            proxy=proxy,
            message=f"Onion search enabled, but Tor proxy is unavailable: {exc}. Continuing with public web sources.",
        )
    return OnionSearchStatus(
        available=False,
        enabled=True,
        proxy=proxy,
        message="Onion search enabled, but Tor proxy did not confirm availability. Continuing with public web sources.",
    )


def _tor_session(proxy: str) -> requests.Session:
    proxy = proxy.replace("socks5h://", "").replace("socks5://", "")
    session = requests.Session()
    proxy_url = f"socks5h://{proxy}"
    session.proxies.update({"http": proxy_url, "https": proxy_url})
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 CognitiveNexusBloodhound/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _plain_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 CognitiveNexusBloodhound/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _onion_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _extract_onion_links_from_html(html: str, base_url: str = "") -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("a", href=True):
            href = urljoin(base_url, str(tag.get("href", "")))
            text = clean_text(tag.get_text(" ", strip=True))
            if ".onion" not in href:
                continue
            url = href.split("#", 1)[0]
            if url in seen:
                continue
            seen.add(url)
            links.append({"title": text or url, "url": url, "snippet": text, "source": _onion_domain(url), "source_type": "onion_index"})
    for match in re.finditer(r"https?://[a-z2-7]{16,56}\.onion[^\s\"'<>)]*", html, flags=re.IGNORECASE):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            links.append({"title": url, "url": url, "snippet": "", "source": _onion_domain(url), "source_type": "onion_index"})
    return links


def search_onion_indexes(query: str, *, max_results: int = 10, timeout: int = 12) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover onion URLs from public onion indexes without making them primary results."""

    errors: list[str] = []
    results: list[dict[str, Any]] = []
    search_urls = [
        f"https://ahmia.fi/search/?q={quote_plus(query)}",
        f"https://ahmia.fi/search/?q={quote_plus(query + ' .onion')}",
    ]
    session = _plain_session()
    for search_url in search_urls:
        try:
            response = session.get(search_url, timeout=timeout)
            response.raise_for_status()
            results.extend(_extract_onion_links_from_html(response.text, search_url))
        except Exception as exc:
            errors.append(f"Onion index search failed for {search_url}: {exc}")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        url = str(item.get("url", ""))
        if url and url not in seen:
            seen.add(url)
            deduped.append(item)
        if len(deduped) >= max_results:
            break
    return deduped, errors


def fetch_onion_page(url: str, *, proxy: str = "127.0.0.1:9050", timeout: int = 12) -> dict[str, Any]:
    """Fetch a single onion HTML page through Tor without executing page scripts."""

    output: dict[str, Any] = {
        "url": url,
        "source": _onion_domain(url),
        "title": "",
        "text": "",
        "excerpt": "",
        "links": [],
        "success": False,
        "error": "",
    }
    if ".onion" not in _onion_domain(url):
        output["error"] = "URL is not an onion host."
        return output
    try:
        response = _tor_session(proxy).get(url, timeout=timeout)
        response.raise_for_status()
        html = response.text
        if BeautifulSoup is None:
            text = clean_text(re.sub(r"<[^>]+>", " ", html))
            output.update({"text": text, "excerpt": text[:1500], "success": bool(text)})
            return output
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "form"]):
            tag.decompose()
        title_tag = soup.find("title")
        title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
        parts = [
            clean_text(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "pre", "code"])
            if clean_text(tag.get_text(" ", strip=True))
        ]
        links = []
        for tag in soup.find_all("a", href=True):
            href = urljoin(url, str(tag.get("href", "")))
            if ".onion" in href:
                links.append({"text": clean_text(tag.get_text(" ", strip=True))[:120], "href": href})
            if len(links) >= 25:
                break
        text = clean_text(" ".join(parts) or soup.get_text(" ", strip=True))
        output.update({"title": title, "text": text, "excerpt": text[:1500], "links": links, "success": bool(text)})
    except Exception as exc:
        output["error"] = str(exc)
    return output


def run_onion_search(
    query: str,
    *,
    enabled: bool,
    proxy: str = "127.0.0.1:9050",
    max_results: int = 10,
    timeout: int = 12,
    fetch_pages: bool = True,
) -> dict[str, Any]:
    """Run secondary onion discovery/fetching, returning results even when fetch is unavailable."""

    status = check_onion_status(enabled=enabled, proxy=proxy)
    if not enabled:
        return {"status": status.to_dict(), "results": [], "pages": {}, "errors": []}
    results, errors = search_onion_indexes(query, max_results=max_results, timeout=timeout)
    pages: dict[str, dict[str, Any]] = {}
    if fetch_pages and results and status.available:
        for item in results[:max_results]:
            url = str(item.get("url", ""))
            pages[url] = fetch_onion_page(url, proxy=proxy, timeout=timeout)
            if pages[url].get("error"):
                errors.append(f"Onion fetch failed for {url}: {pages[url]['error']}")
    elif results and not status.available:
        errors.append(status.message)
    return {"status": status.to_dict(), "results": results, "pages": pages, "errors": errors}
