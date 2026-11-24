"""Secrets kept out of what the app writes down for itself (item 110).

The app's own records are redacted as they are written: its log file (logs/cognitive_nexus.log), its
event log (logs/events.jsonl), the answer checks (logs/uncertainty.jsonl), the metadata saved with
pictures, the text a ComfyUI picture carries inside it (its workflow, which can hold a custom node's
key), and the coding agent's journal of what it did (agent.db). What is taken out:

* text shaped like a key or token: the patterns tools/check_repo_hygiene.py looks for in the
  repository (OpenAI, Anthropic, GitHub, AWS, Google, Slack and Hugging Face keys, private keys);
* a value written after a name that says it is a key, token, secret or password ("api_key=...");
* a password in a web address (https://name:password@host), a key in its query (?api_key=...),
  and the value after "Bearer" or "Basic";
* the values of this machine's own secrets: environment variables whose names say they hold a key,
  token, secret or password, and credentials the app has read from its account store this session.

What is not redacted: the owner's conversation. Chat history, the prompt sent to the model and the
answers stay as written (docs/OWNER_CONTROL.md); a key pasted into chat goes to the model as typed.
Text that only looks like a key may be redacted too; a key in a format not listed here, and not one
of this machine's own, is not.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

REDACTED = "[redacted: {}]"

# Shapes of keys and tokens. Kept the same as the repository check (tools/check_repo_hygiene.py
# imports them from here), so what may not be committed is also what is not written to a log.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),
}
# Values that follow a name saying what they are ("api_key=...", "token: ..."). The name has to end
# with the word, so "max_tokens: 4096" and "token_count=12" are left alone, and the value has to
# contain a letter.
_NAMED_VALUE = re.compile(
    r"""(?ix)
    (?P<name>\b[\w.-]*(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|credential))(?![\w])
    (?P<between>["']?\s*[:=]\s*["']?)
    (?P<value>(?=[^\s"',;&)}\]]*[a-z])[^\s"',;&)}\]]{8,})"""
)
_URL_PASSWORD = re.compile(r"(?P<head>\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)(?P<value>[^/\s@]+)(?P<tail>@)", re.IGNORECASE)
_URL_QUERY_KEY = re.compile(
    r"(?P<head>[?&](?:api[_-]?key|apikey|key|token|access_token|auth|password|secret|signature|sig)=)(?P<value>[^&\s#\"']+)", re.IGNORECASE
)
# An Authorization header's value has a digit or one of + / = in it; "Basic understanding" has not.
_AUTH_HEADER = re.compile(r"(?P<head>\b(?:Bearer|Basic)\s+)(?P<value>(?=[A-Za-z0-9._~+/=-]*[0-9+/=])[A-Za-z0-9._~+/=-]{12,})")
# Environment variables and settings that hold a secret, by a name that ends with what it holds:
# GITHUB_TOKEN and openai_api_key do; MAX_TOKENS, TOKEN_URL and token_count do not.
_SECRET_NAME = re.compile(r"(?i)(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|credential|(?:^|_)pat)$")
MIN_SECRET_LENGTH = 8

_remembered: dict[str, str] = {}
_lock = threading.Lock()


def remember(value: str, label: str) -> None:
    """Keep a secret the app has read (from its account store, say) out of its records from now on."""

    if value and len(value) >= MIN_SECRET_LENGTH:
        with _lock:
            _remembered[value] = label


def known_secrets() -> dict[str, str]:
    """This machine's own secrets, value -> label: secret-named environment variables and remembered credentials."""

    found = {
        value: name
        for name, value in os.environ.items()
        if _SECRET_NAME.search(name) and len(value or "") >= MIN_SECRET_LENGTH
    }
    with _lock:
        found.update(_remembered)
    return found


def redact(text: str) -> str:
    """The text with secrets replaced by "[redacted: what it was]"."""

    if not text:
        return text
    for value, label in sorted(known_secrets().items(), key=lambda item: -len(item[0])):
        if value in text:
            text = text.replace(value, REDACTED.format(label))
    for label, pattern in SECRET_PATTERNS.items():
        text = pattern.sub(REDACTED.format(label), text)
    text = _URL_PASSWORD.sub(lambda match: f"{match['head']}{REDACTED.format('password')}{match['tail']}", text)
    text = _URL_QUERY_KEY.sub(lambda match: f"{match['head']}{REDACTED.format('key')}", text)
    text = _AUTH_HEADER.sub(lambda match: f"{match['head']}{REDACTED.format('credential')}", text)

    def named(match: re.Match[str]) -> str:
        if match["value"].startswith("[redacted"):
            return match[0]
        return f"{match['name']}{match['between']}{REDACTED.format(match['name'])}"

    return _NAMED_VALUE.sub(named, text)


def redact_data(value: Any) -> Any:
    """redact() applied to every string in a structure of dicts, lists and tuples; keys that name a secret lose their value."""

    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            secret_key = isinstance(key, str) and _SECRET_NAME.search(key)
            if secret_key and isinstance(item, str) and len(item) >= MIN_SECRET_LENGTH:
                cleaned[key] = REDACTED.format(key)
            else:
                cleaned[key] = redact_data(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return type(value)(redact_data(item) for item in value)
    return value


class RedactingFormatter(logging.Formatter):
    """Formats a record with another formatter, then redacts the result (message and traceback alike)."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        super().__init__()
        self.inner = inner or logging.Formatter("%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))


def install_log_redaction(logger: logging.Logger | None = None) -> int:
    """Redact everything the logger's handlers write (the root logger by default). Returns how many were changed."""

    changed = 0
    for handler in (logger or logging.getLogger()).handlers:
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter))
            changed += 1
    return changed


def redact_png_text(path: str | Path) -> bool:
    """Redact the text a PNG carries (ComfyUI keeps the whole workflow there). Returns True when it was rewritten.

    The picture is left byte for byte as it was unless a secret is found.
    """

    try:
        from PIL import Image, PngImagePlugin
    except ImportError:
        return False
    target = Path(path)
    if target.suffix.lower() != ".png" or not target.exists():
        return False
    with Image.open(target) as image:
        image.load()
        texts = {key: value for key, value in (getattr(image, "text", None) or {}).items() if isinstance(value, str)}
        cleaned = {key: redact(value) for key, value in texts.items()}
        if cleaned == texts:
            return False
        info = PngImagePlugin.PngInfo()
        for key, value in cleaned.items():
            info.add_text(key, value)
        image.save(target, "PNG", pnginfo=info)
    return True
