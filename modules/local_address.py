"""Addresses of servers on this machine (Ollama, ComfyUI, Automatic1111), written so a connection is quick.

On Windows the name "localhost" is tried as the IPv6 address ::1 first. Ollama, ComfyUI and
Automatic1111 listen on 127.0.0.1 by default, so every new connection to "localhost" waited for
the IPv6 attempt to fail before it was made: 2.05 s against 0.04 s on the development machine
(2026-11-24, measured with requests), and a server that is not running took 1.5 s to report
instead of 0.75 s. Saved settings may keep saying "localhost"; loopback_ipv4() is applied where a
request is made, so they do not have to change.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def loopback_ipv4(url: str) -> str:
    """The same address with the host "localhost" written as 127.0.0.1. Any other host is left as it is."""

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return url
    if (parts.hostname or "").lower() != "localhost":
        return url
    netloc = "127.0.0.1" + (f":{port}" if port else "")
    if parts.username:
        netloc = f"{parts.username}{':' + parts.password if parts.password else ''}@{netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
