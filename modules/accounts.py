"""Linked accounts: credentials for outside services, what each may be used for, and how to take that back.

Until now a service was "linked" by putting a key into an environment variable: all or nothing,
never expiring as far as the app knew, and withdrawn by editing the environment. This module gives
every outside service the same four things.

* A stored credential. On Windows the secret is encrypted with the Data Protection API for the
  signed-in Windows user (CryptProtectData), so the file is useless on another machine or under
  another user. Other systems have no such facility without extra packages: there the secret is
  kept in a file only the user can read, and the account's entry says that it is not encrypted.
* Permissions. Linking an account lets the assistant do nothing by itself. The owner chooses what
  it may be used for (for GitHub: "push", "pull_request"), and code asks for the credential *for a
  permission*: `credential("github", "push")`. Without that permission it gets an error, not a token.
* Renewal. A credential may carry an expiry and a refresh token (OAuth 2.0, RFC 6749 section 6).
  One that has run out is renewed before it is used; one that cannot be renewed is refused with
  the reason, and never sent.
* Withdrawal. One permission, or the whole account. Unlinking deletes the secret here and, when
  the service has a revocation address (RFC 7009), asks the service to cancel the token as well.

A service can still be linked through its environment variable. Such an account has every
permission unless the owner withholds some here, and the app cannot delete the secret (it does not
own the variable): the entry says so.

Signing in on the service's own page instead of pasting a token is the OAuth 2.0 device grant
(RFC 8628). It needs a client id that the owner registers with the service.

Nothing in this module decides what the assistant may *do*: that is agent/approvals.py. An account
with the "push" permission still pushes only when the approval policy lets the push happen.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from modules.data_stores import CONFIG_ROOT
from modules.event_log import record_event
from modules.file_lock import read_json, update_json

ACCOUNTS_FILE = CONFIG_ROOT / "accounts.json"
# Renew this long before the service would start refusing the credential.
RENEW_AHEAD_SECONDS = 120
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
HTTP_TIMEOUT = 20


class AccountError(RuntimeError):
    """A credential could not be provided. The message says why and what the owner can do."""


class NotLinked(AccountError):
    pass


class NotPermitted(AccountError):
    pass


class Expired(AccountError):
    pass


@dataclass(frozen=True)
class Service:
    key: str
    name: str
    used_for: str
    # permission -> what it lets the assistant do, in the owner's terms
    permissions: dict[str, str]
    variables: tuple[str, ...] = ()
    how_to_get: str = ""
    device_url: str = ""
    token_url: str = ""
    revoke_url: str = ""
    # Where the owner cancels a credential when the service offers no address for doing it from here.
    cancel_at: str = ""


SERVICES: dict[str, Service] = {
    service.key: service
    for service in (
        Service(
            key="github",
            name="GitHub",
            used_for="The coding agent publishes its work: its own branch, and a draft pull request.",
            permissions={
                "read": "Read issues, CI results and releases of repositories the token can see.",
                "push": "Push a task's own branch to a repository the token can write to.",
                "pull_request": "Open a draft pull request from that branch.",
            },
            variables=("COGNITIVE_NEXUS_GITHUB_TOKEN", "GITHUB_TOKEN"),
            how_to_get="A fine-grained personal access token for one repository, with 'Contents: read and write' and 'Pull requests: read and write'.",
            device_url="https://github.com/login/device/code",
            token_url="https://github.com/login/oauth/access_token",
            cancel_at="github.com, Settings, Developer settings, Personal access tokens",
        ),
        Service(
            key="openai",
            name="OpenAI",
            used_for="Answers from OpenAI models, when OpenAI is in the provider order or cloud fallback is on.",
            permissions={"chat": "Send your prompts, and the context that goes with them, to OpenAI."},
            variables=("OPENAI_API_KEY",),
            how_to_get="An API key from platform.openai.com.",
            cancel_at="platform.openai.com, API keys",
        ),
        Service(
            key="anthropic",
            name="Anthropic",
            used_for="Answers from Claude models, when Anthropic is in the provider order or cloud fallback is on.",
            permissions={"chat": "Send your prompts, and the context that goes with them, to Anthropic."},
            variables=("ANTHROPIC_API_KEY",),
            how_to_get="An API key from console.anthropic.com.",
            cancel_at="console.anthropic.com, API keys",
        ),
        Service(
            key="brave_search",
            name="Brave Search",
            used_for="Web search results from the Brave Search API.",
            permissions={"search": "Send your search queries to Brave Search."},
            variables=("BRAVE_SEARCH_API_KEY",),
            how_to_get="A subscription token from api.search.brave.com.",
            cancel_at="api.search.brave.com, API keys",
        ),
    )
}


# ---- protecting the secret ---------------------------------------------------------------------------


def _windows() -> bool:
    return sys.platform == "win32"


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Encrypt or decrypt with the Windows Data Protection API, bound to the signed-in Windows user."""

    if sys.platform != "win32":
        raise AccountError("The Windows Data Protection API is only there on Windows.")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    def blob(content: bytes) -> tuple[Blob, Any]:
        buffer = ctypes.create_string_buffer(content, len(content))
        return Blob(len(content), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, _keep_source = blob(data)
    # Mixed into the key so another program's DPAPI call does not decrypt this by accident.
    # It is not a secret and gives no protection against a program that reads this file.
    purpose, _keep_purpose = blob(b"cognitive-nexus linked accounts")
    result = Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    no_prompt = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if not function(ctypes.byref(source), None, ctypes.byref(purpose), None, None, no_prompt, ctypes.byref(result)):
        raise AccountError(
            "Windows could not " + ("encrypt the credential." if protect else "decrypt the stored credential. It was saved by another Windows user or on another machine: link the account again.")
        )
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def protection() -> tuple[str, str]:
    """(how secrets are kept here, a sentence for the owner)."""

    if _windows():
        return "dpapi", "Encrypted for your Windows user on this machine (Windows Data Protection API)."
    return "plain", "Not encrypted: kept in a file that only your user may read. This system offers no built-in way to encrypt it."


def _seal(secret: str) -> dict[str, str]:
    raw = secret.encode("utf-8")
    how = protection()[0]
    return {"how": how, "value": base64.b64encode(_dpapi(raw, protect=True) if how == "dpapi" else raw).decode("ascii")}


def _open(sealed: dict[str, str] | None) -> str:
    if not sealed or not sealed.get("value"):
        return ""
    raw = base64.b64decode(sealed["value"])
    if sealed.get("how") == "dpapi":
        if not _windows():
            raise AccountError("This credential was encrypted on Windows and cannot be read here. Link the account again.")
        raw = _dpapi(raw, protect=False)
    return raw.decode("utf-8")


# ---- the file -----------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _load(path: Path | None = None) -> dict[str, Any]:
    data = read_json(path or ACCOUNTS_FILE, None)
    return data if isinstance(data, dict) else {}


def _change(change: Callable[[dict[str, Any]], Any], path: Path | None = None) -> Any:
    target = Path(path or ACCOUNTS_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = update_json(target, change)
    if not _windows():
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    return result


def service_for(key: str, record: dict[str, Any] | None = None) -> Service:
    """What is known about a service: the built-in description, or the one saved with a custom account."""

    known = SERVICES.get(key)
    if known is not None:
        return known
    record = record or {}
    return Service(
        key=key,
        name=str(record.get("name") or key),
        used_for=str(record.get("used_for") or "A service you added."),
        permissions=dict(record.get("known_permissions") or {name: "" for name in record.get("permissions", [])}),
    )


def _from_environment(service: Service) -> tuple[str, str]:
    for name in service.variables:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def _checked_address(address: str, what: str) -> str:
    """An address a credential may be sent to: https, or plain http to this machine only."""

    address = str(address or "").strip()
    if not address:
        return ""
    parsed = urlparse(address)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError(f"The {what} must be an https address: a credential is sent to it.")
    return address


# ---- linking, permissions, withdrawal ----------------------------------------------------------------------


def link(
    service: str,
    secret: str,
    *,
    permissions: list[str] | tuple[str, ...] | None = None,
    expires_at: str = "",
    expires_in: float | None = None,
    refresh_token: str = "",
    client_id: str = "",
    token_url: str = "",
    revoke_url: str = "",
    name: str = "",
    used_for: str = "",
    known_permissions: dict[str, str] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Store a credential for a service. With no `permissions` the account is linked but may be used for nothing."""

    key = str(service or "").strip().lower()
    secret = str(secret or "").strip()
    if not key or not key.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Give the service a short name of letters, digits, '-' and '_'.")
    if not secret:
        raise ValueError("The credential is empty.")
    described = SERVICES.get(key)
    allowed = set(described.permissions) if described else set(known_permissions or {}) | set(permissions or [])
    wanted = [str(item) for item in (permissions or [])]
    unknown = sorted(set(wanted) - allowed)
    if unknown:
        raise ValueError(f"{described.name if described else key} has no permission named {', '.join(unknown)}. It has: {', '.join(sorted(allowed)) or 'none'}.")
    token_url = _checked_address(token_url or (described.token_url if described else ""), "token address")
    revoke_url = _checked_address(revoke_url or (described.revoke_url if described else ""), "revocation address")
    if expires_in is not None:
        expires_at = _stamp(_now() + timedelta(seconds=float(expires_in)))
    if expires_at:
        datetime.fromisoformat(expires_at)  # refuse a date that cannot be read later
    record: dict[str, Any] = {
        "source": "stored",
        "secret": _seal(secret),
        "refresh": _seal(refresh_token) if refresh_token else None,
        "permissions": sorted(set(wanted)),
        "expires_at": expires_at,
        "client_id": str(client_id or ""),
        "token_url": token_url if (refresh_token or client_id) else "",
        "revoke_url": revoke_url,
        "linked_at": _stamp(),
        "renewed_at": "",
        "last_used": "",
        "problem": "",
    }
    if described is None:
        record.update({"name": name or key, "used_for": used_for, "known_permissions": dict(known_permissions or {item: "" for item in wanted})})

    def change(data: dict[str, Any]) -> None:
        data[key] = record

    _change(change, path)
    record_event("account", f"Linked {key}", service=key, permissions=record["permissions"])
    return describe(key, path=path)


def set_permissions(service: str, permissions: list[str] | tuple[str, ...], *, path: Path | None = None) -> dict[str, Any]:
    """Say exactly what an account may be used for. Works for accounts linked through the environment too."""

    key = str(service).lower()
    wanted = sorted({str(item) for item in permissions})

    def change(data: dict[str, Any]) -> None:
        record = data.get(key)
        described = service_for(key, record)
        unknown = sorted(set(wanted) - set(described.permissions))
        if unknown:
            raise ValueError(f"{described.name} has no permission named {', '.join(unknown)}.")
        if record and record.get("source") == "stored":
            record["permissions"] = wanted
            return
        if not _from_environment(described)[0]:
            raise NotLinked(f"{described.name} is not linked.")
        # Linked through the environment: the app cannot remove the secret, but it can refuse to use it.
        data[key] = {"source": "environment", "withheld": sorted(set(described.permissions) - set(wanted))}

    _change(change, path)
    record_event("account", f"Permissions of {key} set", service=key, permissions=wanted)
    return describe(key, path=path)


def withdraw(service: str, permission: str, *, path: Path | None = None) -> dict[str, Any]:
    current = describe(service, path=path)
    return set_permissions(service, [item for item in current["permissions"] if item != permission], path=path)


def grant(service: str, permission: str, *, path: Path | None = None) -> dict[str, Any]:
    current = describe(service, path=path)
    return set_permissions(service, [*current["permissions"], permission], path=path)


def unlink(service: str, *, tell_the_service: bool = True, path: Path | None = None) -> dict[str, Any]:
    """Delete the stored credential, and ask the service to cancel it where the service can be asked.

    Returns what happened, including what the owner still has to do by hand.
    """

    key = str(service).lower()
    record = _load(path).get(key)
    described = service_for(key, record)
    outcome: dict[str, Any] = {"service": key, "deleted_here": False, "cancelled_at_the_service": None, "still_to_do": ""}
    if record and record.get("source") == "stored":
        if tell_the_service and record.get("revoke_url"):
            cancelled = []
            for sealed, hint in ((record.get("refresh"), "refresh_token"), (record.get("secret"), "access_token")):
                try:
                    token = _open(sealed)
                except AccountError:
                    token = ""
                if not token:
                    continue
                try:
                    answer = requests.post(
                        record["revoke_url"],
                        data={"token": token, "token_type_hint": hint, "client_id": record.get("client_id", "")},
                        headers={"Accept": "application/json"},
                        timeout=HTTP_TIMEOUT,
                    )
                    cancelled.append(answer.status_code == 200)
                except requests.RequestException:
                    cancelled.append(False)
            outcome["cancelled_at_the_service"] = bool(cancelled) and all(cancelled)

        def change(data: dict[str, Any]) -> None:
            data.pop(key, None)

        _change(change, path)
        outcome["deleted_here"] = True
    elif record:

        def forget(data: dict[str, Any]) -> None:
            data.pop(key, None)

        _change(forget, path)
    if outcome["cancelled_at_the_service"] is not True:
        where = described.cancel_at or "the service's own settings"
        outcome["still_to_do"] = f"The credential itself is still valid at {described.name} until you cancel it there ({where})."
    variable = _from_environment(described)[1]
    if variable:
        outcome["still_to_do"] = (outcome["still_to_do"] + " " if outcome["still_to_do"] else "") + (
            f"{described.name} is also linked through the environment variable {variable}, which this app cannot remove: it is still linked until you remove the variable."
        )
    record_event("account", f"Unlinked {key}", service=key, cancelled_at_the_service=outcome["cancelled_at_the_service"])
    return outcome


# ---- renewal --------------------------------------------------------------------------------------------------


def _seconds_left(record: dict[str, Any]) -> float | None:
    if not record.get("expires_at"):
        return None
    try:
        expires = datetime.fromisoformat(record["expires_at"])
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return (expires - _now()).total_seconds()


def _token_reply(answer: requests.Response) -> dict[str, Any]:
    try:
        body = answer.json()
    except ValueError:
        body = {}
    return body if isinstance(body, dict) else {}


def renew(service: str, *, path: Path | None = None) -> dict[str, Any]:
    """Exchange the refresh token for a new credential (RFC 6749, section 6)."""

    key = str(service).lower()
    record = _load(path).get(key)
    if not record or record.get("source") != "stored":
        raise NotLinked(f"{service_for(key).name} has no stored credential to renew.")
    described = service_for(key, record)
    refresh_token = _open(record.get("refresh"))
    if not refresh_token or not record.get("token_url"):
        raise Expired(f"The {described.name} credential cannot be renewed from here: it came without a refresh token. Link the account again.")
    try:
        answer = requests.post(
            record["token_url"],
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": record.get("client_id", "")},
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise Expired(f"The {described.name} credential could not be renewed: the service was not reached ({type(exc).__name__}).") from exc
    body = _token_reply(answer)
    if answer.status_code != 200 or not body.get("access_token"):
        reason = str(body.get("error_description") or body.get("error") or f"HTTP {answer.status_code}")[:200]

        def failed(data: dict[str, Any]) -> None:
            if key in data:
                data[key]["problem"] = f"Renewal was refused: {reason}"

        _change(failed, path)
        record_event("account", f"Renewal of {key} was refused", service=key, reason=reason)
        raise Expired(f"The {described.name} credential has run out and the service refused to renew it ({reason}). Link the account again.")

    def renewed(data: dict[str, Any]) -> None:
        current = data.get(key)
        if not current:
            return
        current["secret"] = _seal(str(body["access_token"]))
        if body.get("refresh_token"):  # some services give a new one every time and cancel the old
            current["refresh"] = _seal(str(body["refresh_token"]))
        current["expires_at"] = _stamp(_now() + timedelta(seconds=float(body["expires_in"]))) if body.get("expires_in") else ""
        current["renewed_at"] = _stamp()
        current["problem"] = ""

    _change(renewed, path)
    record_event("account", f"Renewed {key}", service=key)
    return describe(key, path=path)


# ---- using a credential ----------------------------------------------------------------------------------------


def credential(service: str, permission: str, *, path: Path | None = None) -> str:
    """The credential for one use. Raises AccountError (NotLinked, NotPermitted, Expired) instead of returning nothing."""

    key = str(service).lower()
    record = _load(path).get(key)
    described = service_for(key, record)
    if record and record.get("source") == "stored":
        if permission not in record.get("permissions", []):
            raise NotPermitted(
                f"The {described.name} account is linked, but you have not allowed it to be used for '{permission}'. Settings, Linked accounts changes that."
            )
        left = _seconds_left(record)
        if left is not None and left <= RENEW_AHEAD_SECONDS:
            try:
                renew(key, path=path)
            except Expired:
                if left > 0:  # still valid for a moment: use it, the next call tries again
                    return _open(record["secret"])
                raise
            record = _load(path)[key]
        secret = _open(record["secret"])
        _touch(key, record, path)
        return secret
    value, variable = _from_environment(described)
    if value:
        if record and permission in record.get("withheld", []):
            raise NotPermitted(f"{described.name} is linked through {variable}, but you have withheld '{permission}' in Settings, Linked accounts.")
        if permission not in described.permissions:
            raise NotPermitted(f"{described.name} has no permission named '{permission}'.")
        return value
    how = f" {described.how_to_get}" if described.how_to_get else ""
    variables = f" or set {described.variables[0]}" if described.variables else ""
    raise NotLinked(f"No {described.name} account is linked. Link one in Settings, Linked accounts{variables}.{how}")


def _touch(key: str, record: dict[str, Any], path: Path | None) -> None:
    """Note that the credential was used, at most once a minute (every use would mean a write per request)."""

    last = record.get("last_used") or ""
    try:
        recent = bool(last) and (_now() - datetime.fromisoformat(last)).total_seconds() < 60
    except ValueError:
        recent = False
    if recent:
        return

    def change(data: dict[str, Any]) -> None:
        if key in data:
            data[key]["last_used"] = _stamp()

    try:
        _change(change, path)
    except Exception:  # noting the use must never be the reason a request fails
        pass


def available(service: str, permission: str, *, path: Path | None = None) -> tuple[bool, str]:
    """(usable for this?, why not). Never raises and never contacts the service."""

    key = str(service).lower()
    try:
        record = _load(path).get(key)
    except Exception as exc:
        return False, f"The accounts file cannot be read: {type(exc).__name__}"
    described = service_for(key, record)
    if record and record.get("source") == "stored":
        if permission not in record.get("permissions", []):
            return False, f"{described.name} is linked, but not allowed for '{permission}'."
        left = _seconds_left(record)
        if left is not None and left <= 0 and not record.get("refresh"):
            return False, f"The {described.name} credential ran out on {record['expires_at'][:10]}. Link the account again."
        return True, f"{described.name} is linked."
    value, variable = _from_environment(described)
    if value:
        if record and permission in record.get("withheld", []):
            return False, f"{described.name} is linked through {variable}, but '{permission}' is withheld."
        return True, f"{described.name} is linked through {variable}."
    hint = f"{described.variables[0]} is not set." if described.variables else "No account is linked."
    return False, hint


def describe(service: str, *, path: Path | None = None) -> dict[str, Any]:
    """One account as the owner sees it. Never contains a secret."""

    key = str(service).lower()
    record = _load(path).get(key)
    described = service_for(key, record)
    value, variable = _from_environment(described)
    entry: dict[str, Any] = {
        "service": key,
        "name": described.name,
        "used_for": described.used_for,
        "known_permissions": dict(described.permissions),
        "linked": False,
        "how": "",
        "permissions": [],
        "expires_at": "",
        "renews_itself": False,
        "can_be_deleted_here": False,
        "kept": "",
        "linked_at": "",
        "last_used": "",
        "problem": "",
        "how_to_get": described.how_to_get,
        "cancel_at": described.cancel_at,
    }
    if record and record.get("source") == "stored":
        left = _seconds_left(record)
        run_out = left is not None and left <= 0 and not record.get("refresh")
        entry.update(
            linked=True,
            how="stored by this app",
            permissions=list(record.get("permissions", [])),
            expires_at=record.get("expires_at", ""),
            renews_itself=bool(record.get("refresh") and record.get("token_url")),
            can_be_deleted_here=True,
            kept=protection()[1] if (record.get("secret") or {}).get("how") == protection()[0] else "Saved on another kind of system; link it again.",
            linked_at=record.get("linked_at", ""),
            last_used=record.get("last_used", ""),
            problem=record.get("problem", "") or ("The credential has run out." if run_out else ""),
        )
    elif value:
        withheld = set((record or {}).get("withheld", []))
        entry.update(
            linked=True,
            how=f"environment variable {variable}",
            permissions=sorted(set(described.permissions) - withheld),
            kept="In your environment, outside this app. The app cannot delete it; it can only decline to use it.",
        )
    return entry


def accounts(*, path: Path | None = None) -> list[dict[str, Any]]:
    """Every known service and every account you added, linked or not. Never contains a secret."""

    stored = _load(path)
    keys = list(SERVICES) + sorted(key for key in stored if key not in SERVICES)
    return [describe(key, path=path) for key in keys]


# ---- signing in on the service's own page (RFC 8628) --------------------------------------------------------------


def begin_sign_in(service: str, client_id: str, *, scope: str = "", device_url: str = "") -> dict[str, Any]:
    """Start a device sign-in. Returns the code to type and the page to type it on."""

    described = service_for(str(service).lower())
    address = _checked_address(device_url or described.device_url, "sign-in address")
    if not address:
        raise AccountError(f"{described.name} has no sign-in address on record. Paste a token instead.")
    if not client_id:
        raise AccountError("Signing in this way needs a client id: register an OAuth app with the service and enter its id.")
    answer = requests.post(address, data={"client_id": client_id, "scope": scope}, headers={"Accept": "application/json"}, timeout=HTTP_TIMEOUT)
    body = _token_reply(answer)
    if answer.status_code != 200 or not body.get("device_code"):
        raise AccountError(f"{described.name} did not start the sign-in: {str(body.get('error_description') or body.get('error') or answer.status_code)[:200]}")
    return {
        "service": described.key,
        "client_id": client_id,
        "device_code": str(body["device_code"]),
        "user_code": str(body.get("user_code", "")),
        "verification_uri": str(body.get("verification_uri") or body.get("verification_url") or ""),
        "interval": float(body.get("interval", 5)),
        "expires_at": time.time() + float(body.get("expires_in", 900)),
    }


def finish_sign_in(
    pending: dict[str, Any],
    *,
    permissions: list[str] | tuple[str, ...] = (),
    token_url: str = "",
    wait: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Ask the service whether the owner has approved the sign-in; store the credential when they have.

    With wait=False one question is asked and None is returned while the owner has not decided yet.
    """

    described = service_for(str(pending["service"]))
    address = _checked_address(token_url or described.token_url, "token address")
    interval = float(pending.get("interval", 5))
    while True:
        if time.time() >= float(pending["expires_at"]):
            raise AccountError("The sign-in code ran out before it was approved. Start again.")
        answer = requests.post(
            address,
            data={"client_id": pending["client_id"], "device_code": pending["device_code"], "grant_type": DEVICE_GRANT},
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        body = _token_reply(answer)
        if body.get("access_token"):
            return link(
                described.key,
                str(body["access_token"]),
                permissions=permissions,
                expires_in=float(body["expires_in"]) if body.get("expires_in") else None,
                refresh_token=str(body.get("refresh_token") or ""),
                client_id=str(pending["client_id"]),
                token_url=address,
                path=path,
            )
        error = str(body.get("error") or f"HTTP {answer.status_code}")
        if error == "slow_down":
            interval += 5
        elif error != "authorization_pending":
            raise AccountError(f"{described.name} refused the sign-in: {str(body.get('error_description') or error)[:200]}")
        if not wait:
            return None
        sleep(interval)


# ---- asking the service whether a credential still works ------------------------------------------------------------


def check_github(*, api: str = "https://api.github.com", path: Path | None = None) -> dict[str, Any]:
    """Ask GitHub who the token belongs to and when it expires. Contacts the service."""

    token = ""
    for permission in SERVICES["github"].permissions:
        try:
            token = credential("github", permission, path=path)
            break
        except NotPermitted:
            continue
    if not token:
        raise NotPermitted("The GitHub account is linked but allowed for nothing, so it is not used, not even to check it.")
    answer = requests.get(f"{api.rstrip('/')}/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=HTTP_TIMEOUT)
    result: dict[str, Any] = {"accepted": answer.status_code == 200, "status": answer.status_code, "login": "", "expires_at": ""}
    if answer.status_code == 200:
        result["login"] = str(_token_reply(answer).get("login", ""))
        stated = answer.headers.get("github-authentication-token-expiration", "")
        if stated:
            try:
                result["expires_at"] = datetime.strptime(stated.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
            except ValueError:
                result["expires_at"] = ""
        if result["expires_at"]:

            def note(data: dict[str, Any]) -> None:
                if data.get("github", {}).get("source") == "stored":
                    data["github"]["expires_at"] = result["expires_at"]
                    data["github"]["problem"] = ""

            _change(note, path)
    elif answer.status_code == 401:

        def refused(data: dict[str, Any]) -> None:
            if data.get("github", {}).get("source") == "stored":
                data["github"]["problem"] = "GitHub no longer accepts this token: it has expired or was cancelled."

        _change(refused, path)
    return result


__all__ = [
    "ACCOUNTS_FILE",
    "AccountError",
    "Expired",
    "NotLinked",
    "NotPermitted",
    "SERVICES",
    "Service",
    "accounts",
    "available",
    "begin_sign_in",
    "check_github",
    "credential",
    "describe",
    "finish_sign_in",
    "grant",
    "link",
    "protection",
    "renew",
    "set_permissions",
    "unlink",
    "withdraw",
]
