"""Guard for fetching URLs that come from search results, web pages or pasted links.

Research follows links found on the open web. Without a check, a page (or a redirect) could point
the app at addresses only this machine can reach - localhost services such as Ollama, the home
router, cloud metadata endpoints - and their contents would end up in reports and model prompts.

`safe_get` refuses anything that is not plain http(s) to a public address and re-checks every
redirect hop. Set ALLOW_PRIVATE_URL_FETCH=true to fetch local or private hosts on purpose.

Not covered: DNS rebinding between the check and the connection (the address is not pinned).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """The URL is not a public http(s) address the app is willing to fetch."""


def private_fetch_allowed() -> bool:
    return os.environ.get("ALLOW_PRIVATE_URL_FETCH", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def check_public_url(url: str) -> None:
    """Raise UnsafeURLError unless the URL is http(s) and every address it resolves to is public."""

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only http and https URLs can be fetched.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("The URL has no host.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("The URL has an invalid port.") from exc
    if private_fetch_allowed():
        return
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        if requests.utils.get_environ_proxies(url):
            return  # a configured proxy resolves the name; this machine can't check it
        raise UnsafeURLError(f"Could not resolve host {host!r}.") from exc
    for entry in resolved:
        if not _is_public_address(entry[4][0]):
            raise UnsafeURLError(
                f"Blocked {host!r}: it points to a local or private address. "
                "Set ALLOW_PRIVATE_URL_FETCH=true to allow this."
            )


def safe_get(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs: Any,
) -> requests.Response:
    """GET a public URL, checking the address before the request and again before each redirect."""

    getter = (session or requests).get
    current = str(url or "").strip()
    for _hop in range(max_redirects + 1):
        check_public_url(current)
        response = getter(current, timeout=timeout, allow_redirects=False, **kwargs)
        location = response.headers.get("Location") if response.is_redirect is True else None
        if not location:
            return response
        response.close()
        current = urljoin(current, location)
    raise UnsafeURLError(f"Too many redirects (more than {max_redirects}).")
