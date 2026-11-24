"""Guard for fetching URLs that come from search results, web pages or pasted links.

Research follows links found on the open web. Without a check, a page (or a redirect) could point
the app at addresses only this machine can reach - localhost services such as Ollama, the home
router, cloud metadata endpoints - and their contents would end up in reports and model prompts.

`safe_get` refuses anything that is not plain http(s) to a public address and re-checks every
redirect hop. Set ALLOW_PRIVATE_URL_FETCH=true to fetch local or private hosts on purpose.

The connection is made to the address that was checked. A name is looked up once per hop, and for
the duration of that request the same thread is given exactly those addresses when the HTTP
library looks the name up again to connect. Without this a hostile name server could answer the
check with a public address and the connection, a moment later, with a private one ("DNS
rebinding"). The URL, the Host header and the name a certificate must be for are untouched.

Not covered: a request that goes through a configured proxy. The proxy looks the name up itself,
so this machine can neither check nor pin the address it uses.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import requests

MAX_REDIRECTS = 5

# The system's own lookup, kept so that the one below can pass everything else on to it.
_system_getaddrinfo = socket.getaddrinfo
_pins = threading.local()


def _getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    """socket.getaddrinfo, except that a name pinned by this thread resolves to its checked addresses only."""

    pinned = getattr(_pins, "hosts", {}).get(_name(host)) if isinstance(host, str) else None
    if not pinned:
        return _system_getaddrinfo(host, port, *args, **kwargs)
    found: list[Any] = []
    for address in pinned:
        found.extend(_system_getaddrinfo(address, port, *args, **kwargs))  # an address written out: no lookup happens
    return found


# Installed once for the process. Outside `pinned()` it is the system's lookup and nothing else.
socket.getaddrinfo = _getaddrinfo


def _name(host: str) -> str:
    return host.strip().lower().rstrip(".")


@contextmanager
def pinned(host: str, addresses: list[str]) -> Iterator[None]:
    """While this block runs, this thread's lookups of `host` give `addresses` and nothing else."""

    if not addresses:
        yield
        return
    hosts = getattr(_pins, "hosts", None)
    if hosts is None:
        hosts = _pins.hosts = {}
    key = _name(host)
    before = hosts.get(key)
    hosts[key] = list(addresses)
    try:
        yield
    finally:
        if before is None:
            hosts.pop(key, None)
        else:
            hosts[key] = before


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


def public_addresses(url: str) -> list[str]:
    """Check a URL and return the public addresses its host resolved to.

    Raises UnsafeURLError unless the URL is http(s) and every address is public. The list is
    empty when the name was not checked here: fetching private hosts is allowed on purpose, or a
    proxy resolves the name.
    """

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
        return []
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        if requests.utils.get_environ_proxies(url):
            return []  # a configured proxy resolves the name; this machine can't check it
        raise UnsafeURLError(f"Could not resolve host {host!r}.") from exc
    addresses = list(dict.fromkeys(str(entry[4][0]) for entry in resolved))
    for address in addresses:
        if not _is_public_address(address):
            raise UnsafeURLError(
                f"Blocked {host!r}: it points to a local or private address. "
                "Set ALLOW_PRIVATE_URL_FETCH=true to allow this."
            )
    return addresses


def check_public_url(url: str) -> None:
    """Raise UnsafeURLError unless the URL is http(s) and every address it resolves to is public."""

    public_addresses(url)


def safe_get(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs: Any,
) -> requests.Response:
    """GET a public URL: the address is checked before the request and before each redirect, and the connection goes to a checked address."""

    getter = (session or requests).get
    current = str(url or "").strip()
    for _hop in range(max_redirects + 1):
        addresses = public_addresses(current)
        with pinned(urlparse(current).hostname or "", addresses):
            response = getter(current, timeout=timeout, allow_redirects=False, **kwargs)
        location = response.headers.get("Location") if response.is_redirect is True else None
        if not location:
            return response
        response.close()
        current = urljoin(current, location)
    raise UnsafeURLError(f"Too many redirects (more than {max_redirects}).")
