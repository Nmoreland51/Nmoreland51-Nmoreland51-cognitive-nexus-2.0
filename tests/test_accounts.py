"""Linked accounts: stored credentials, permissions, renewal and withdrawal.

The services are played by a small HTTP server on this machine that follows the same published
rules (OAuth 2.0 refresh, device sign-in and revocation; GitHub's "who am I"). No real service is
contacted, so these tests show that the app speaks the protocol, not that any service accepts it.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from modules import accounts

# Built at run time so that no file in the repository contains something shaped like a credential.
SECRET = "-".join(["first", "credential", "for", "tests"])
RENEWED = "-".join(["second", "credential", "for", "tests"])
REFRESH = "-".join(["refresh", "one"])
REFRESH_2 = "-".join(["refresh", "two"])


class Service(BaseHTTPRequestHandler):
    """A stand-in token server and API. What it received is kept on the server object."""

    def log_message(self, *args):  # keep test output clean
        pass

    def _reply(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        form = {key: values[0] for key, values in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        state = self.server.state
        state["requests"].append((self.path, form))
        if self.path == "/token" and form.get("grant_type") == "refresh_token":
            if form.get("refresh_token") != state["valid_refresh"]:
                return self._reply(400, {"error": "invalid_grant", "error_description": "The refresh token is no longer valid."})
            state["valid_refresh"] = REFRESH_2  # this service gives a new refresh token every time and cancels the old one
            return self._reply(200, {"access_token": RENEWED, "expires_in": 3600, "refresh_token": REFRESH_2, "token_type": "bearer"})
        if self.path == "/token" and form.get("grant_type") == accounts.DEVICE_GRANT:
            state["polls"] += 1
            if state["polls"] <= state["pending_polls"]:
                return self._reply(400, {"error": "authorization_pending"})
            if state["deny"]:
                return self._reply(400, {"error": "access_denied", "error_description": "The owner said no."})
            return self._reply(200, {"access_token": SECRET, "expires_in": 28800, "refresh_token": REFRESH, "token_type": "bearer"})
        if self.path == "/device":
            return self._reply(200, {"device_code": "dev-1", "user_code": "WDJB-MJHT", "verification_uri": "https://service.example/device", "expires_in": 900, "interval": 0})
        if self.path == "/revoke":
            state["revoked"].append((form.get("token"), form.get("token_type_hint")))
            return self._reply(200, {})
        return self._reply(404, {"error": "not_found"})

    def do_GET(self):
        state = self.server.state
        state["requests"].append((self.path, dict(self.headers)))
        if self.path == "/user":
            if self.headers.get("Authorization") != f"Bearer {SECRET}":
                return self._reply(401, {"message": "Bad credentials"})
            return self._reply(200, {"login": "the-owner"}, {"github-authentication-token-expiration": "2027-02-01 09:30:00 UTC"})
        return self._reply(404, {})


@pytest.fixture
def service():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
    server.state = {"requests": [], "valid_refresh": REFRESH, "revoked": [], "polls": 0, "pending_polls": 0, "deny": False}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def book(tmp_path, monkeypatch):
    """An empty accounts file, and no account linked through the environment."""

    for described in accounts.SERVICES.values():
        for name in described.variables:
            monkeypatch.delenv(name, raising=False)
    return tmp_path / "accounts.json"


def soon(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


# ---- storing ---------------------------------------------------------------------------------------


def test_a_stored_credential_comes_back_and_is_not_readable_in_the_file(book):
    entry = accounts.link("github", SECRET, permissions=["push"], path=book)

    assert entry["linked"] and entry["how"] == "stored by this app" and entry["permissions"] == ["push"] and entry["can_be_deleted_here"]
    assert accounts.credential("github", "push", path=book) == SECRET
    on_disk = book.read_text(encoding="utf-8")
    if sys.platform == "win32":
        # Encrypted for this Windows user: neither the text nor its base64 form is in the file.
        import base64

        assert SECRET not in on_disk and base64.b64encode(SECRET.encode()).decode() not in on_disk
        assert json.loads(on_disk)["github"]["secret"]["how"] == "dpapi" and "Encrypted for your Windows user" in entry["kept"]
    else:
        # No encryption without extra packages: the entry says so, and only the user may read the file.
        assert entry["kept"].startswith("Not encrypted") and stat.S_IMODE(os.stat(book).st_mode) == 0o600


def test_what_the_owner_sees_never_contains_a_secret(book):
    accounts.link("github", SECRET, permissions=["push"], refresh_token=REFRESH, token_url="https://service.example/token", path=book)

    shown = json.dumps(accounts.accounts(path=book)) + json.dumps(accounts.describe("github", path=book))

    assert SECRET not in shown and REFRESH not in shown
    assert [entry["service"] for entry in accounts.accounts(path=book)][:4] == ["github", "openai", "anthropic", "brave_search"]
    assert {entry["service"]: entry["linked"] for entry in accounts.accounts(path=book)} == {"github": True, "openai": False, "anthropic": False, "brave_search": False}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Data Protection API")
def test_a_file_copied_from_elsewhere_is_refused_with_a_reason(book):
    accounts.link("github", SECRET, permissions=["push"], path=book)
    data = json.loads(book.read_text(encoding="utf-8"))
    data["github"]["secret"]["value"] = "QUJDREVGR0hJSktMTU5PUA=="  # not something this Windows user encrypted
    book.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(accounts.AccountError, match="link the account again"):
        accounts.credential("github", "push", path=book)


# ---- permissions -----------------------------------------------------------------------------------


def test_linking_allows_nothing_until_a_permission_is_given(book):
    accounts.link("github", SECRET, path=book)

    with pytest.raises(accounts.NotPermitted, match="not allowed it to be used for 'push'"):
        accounts.credential("github", "push", path=book)
    assert accounts.available("github", "push", path=book) == (False, "GitHub is linked, but not allowed for 'push'.")

    accounts.grant("github", "push", path=book)

    assert accounts.credential("github", "push", path=book) == SECRET
    with pytest.raises(accounts.NotPermitted):
        accounts.credential("github", "pull_request", path=book)


def test_one_permission_is_withdrawn_and_the_others_stay(book):
    accounts.link("github", SECRET, permissions=["read", "push", "pull_request"], path=book)

    after = accounts.withdraw("github", "pull_request", path=book)

    assert after["permissions"] == ["push", "read"]
    assert accounts.credential("github", "push", path=book) == SECRET
    with pytest.raises(accounts.NotPermitted):
        accounts.credential("github", "pull_request", path=book)


def test_a_permission_the_service_does_not_have_is_refused(book):
    with pytest.raises(ValueError, match="no permission named delete_repository"):
        accounts.link("github", SECRET, permissions=["delete_repository"], path=book)
    accounts.link("github", SECRET, permissions=["push"], path=book)
    with pytest.raises(ValueError, match="no permission named admin"):
        accounts.set_permissions("github", ["push", "admin"], path=book)
    assert accounts.describe("github", path=book)["permissions"] == ["push"]  # the refused change wrote nothing


def test_a_service_of_your_own_is_linked_with_its_own_permissions(book):
    entry = accounts.link("home-wiki", SECRET, permissions=["read"], known_permissions={"read": "Read pages.", "edit": "Change pages."}, name="Home wiki", used_for="Notes at home.", path=book)

    assert entry["name"] == "Home wiki" and entry["known_permissions"] == {"read": "Read pages.", "edit": "Change pages."}
    assert accounts.credential("home-wiki", "read", path=book) == SECRET
    with pytest.raises(accounts.NotPermitted):
        accounts.credential("home-wiki", "edit", path=book)
    assert accounts.accounts(path=book)[-1]["service"] == "home-wiki"


# ---- accounts linked through the environment ---------------------------------------------------------


def test_an_environment_variable_still_links_an_account_with_every_permission(book, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)

    entry = accounts.describe("github", path=book)

    assert entry["linked"] and entry["how"] == "environment variable GITHUB_TOKEN" and not entry["can_be_deleted_here"]
    assert entry["permissions"] == ["pull_request", "push", "read"] and "cannot delete it" in entry["kept"]
    assert accounts.credential("github", "push", path=book) == SECRET
    assert not book.exists()  # reading an environment account writes nothing


def test_a_permission_can_be_withheld_from_an_environment_account(book, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)

    after = accounts.withdraw("github", "pull_request", path=book)

    assert after["permissions"] == ["push", "read"]
    with pytest.raises(accounts.NotPermitted, match="withheld 'pull_request'"):
        accounts.credential("github", "pull_request", path=book)
    assert accounts.credential("github", "push", path=book) == SECRET
    assert SECRET not in book.read_text(encoding="utf-8")  # the app records the decision, not the secret


def test_a_stored_account_takes_precedence_over_the_environment(book, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")
    accounts.link("github", SECRET, permissions=["push"], path=book)

    assert accounts.credential("github", "push", path=book) == SECRET
    with pytest.raises(accounts.NotPermitted):  # the variable does not quietly supply what the owner did not allow
        accounts.credential("github", "pull_request", path=book)


def test_nothing_linked_says_how_to_link(book):
    with pytest.raises(accounts.NotLinked, match="Link one in Settings, Linked accounts or set COGNITIVE_NEXUS_GITHUB_TOKEN"):
        accounts.credential("github", "push", path=book)
    assert accounts.available("openai", "chat", path=book) == (False, "OPENAI_API_KEY is not set.")
    with pytest.raises(accounts.NotLinked):
        accounts.set_permissions("github", ["push"], path=book)


# ---- renewal -----------------------------------------------------------------------------------------


def test_a_credential_that_has_run_out_is_renewed_before_use(book, service):
    address, state = service
    accounts.link("github", SECRET, permissions=["push"], expires_in=-60, refresh_token=REFRESH, client_id="client-1", token_url=f"{address}/token", path=book)

    assert accounts.credential("github", "push", path=book) == RENEWED

    path, form = state["requests"][0]
    assert path == "/token" and form == {"grant_type": "refresh_token", "refresh_token": REFRESH, "client_id": "client-1"}
    entry = accounts.describe("github", path=book)
    assert entry["renews_itself"] and entry["problem"] == "" and entry["expires_at"] > soon(3000)
    # The service replaced the refresh token; the next renewal must use the new one.
    accounts.renew("github", path=book)
    assert state["requests"][1][1]["refresh_token"] == REFRESH_2


def test_a_credential_about_to_run_out_is_renewed_early_and_a_fresh_one_is_left_alone(book, service):
    address, state = service
    accounts.link("github", SECRET, permissions=["push"], expires_in=30, refresh_token=REFRESH, token_url=f"{address}/token", path=book)
    assert accounts.credential("github", "push", path=book) == RENEWED and len(state["requests"]) == 1

    assert accounts.credential("github", "push", path=book) == RENEWED
    assert len(state["requests"]) == 1  # an hour left: the service is not asked again


def test_a_refused_renewal_is_an_error_with_the_reason_and_nothing_is_sent(book, service):
    address, state = service
    state["valid_refresh"] = "something-else"
    accounts.link("github", SECRET, permissions=["push"], expires_in=-60, refresh_token=REFRESH, token_url=f"{address}/token", path=book)

    with pytest.raises(accounts.Expired, match="refused to renew it .The refresh token is no longer valid"):
        accounts.credential("github", "push", path=book)

    assert "Renewal was refused" in accounts.describe("github", path=book)["problem"]


def test_a_credential_that_ran_out_and_cannot_be_renewed_is_refused(book):
    accounts.link("github", SECRET, permissions=["push"], expires_in=-60, path=book)

    with pytest.raises(accounts.Expired, match="came without a refresh token"):
        accounts.credential("github", "push", path=book)
    usable, why = accounts.available("github", "push", path=book)
    assert not usable and "ran out on" in why
    assert accounts.describe("github", path=book)["problem"] == "The credential has run out."


def test_a_credential_is_only_ever_sent_to_https_or_to_this_machine(book):
    with pytest.raises(ValueError, match="must be an https address"):
        accounts.link("github", SECRET, refresh_token=REFRESH, token_url="http://service.example/token", path=book)
    with pytest.raises(ValueError, match="must be an https address"):
        accounts.link("github", SECRET, revoke_url="ftp://service.example/revoke", path=book)
    assert not book.exists()


# ---- withdrawal ----------------------------------------------------------------------------------------


def test_unlinking_deletes_the_secret_and_asks_the_service_to_cancel_it(book, service):
    address, state = service
    accounts.link("home-wiki", SECRET, permissions=["read"], refresh_token=REFRESH, token_url=f"{address}/token", revoke_url=f"{address}/revoke", path=book)

    outcome = accounts.unlink("home-wiki", path=book)

    assert outcome == {"service": "home-wiki", "deleted_here": True, "cancelled_at_the_service": True, "still_to_do": ""}
    assert state["revoked"] == [(REFRESH, "refresh_token"), (SECRET, "access_token")]
    assert "home-wiki" not in json.loads(book.read_text(encoding="utf-8"))
    with pytest.raises(accounts.NotLinked):
        accounts.credential("home-wiki", "read", path=book)


def test_unlinking_says_what_is_left_to_do_when_the_service_cannot_be_asked(book, monkeypatch):
    accounts.link("github", SECRET, permissions=["push"], path=book)
    monkeypatch.setenv("GITHUB_TOKEN", "from-the-environment")

    outcome = accounts.unlink("github", path=book)

    assert outcome["deleted_here"] and outcome["cancelled_at_the_service"] is None
    assert "still valid at GitHub until you cancel it there" in outcome["still_to_do"]
    assert "also linked through the environment variable GITHUB_TOKEN" in outcome["still_to_do"]


# ---- signing in on the service's page --------------------------------------------------------------------


def test_signing_in_with_a_code_stores_the_credential_once_the_owner_approves(book, service):
    address, state = service
    state["pending_polls"] = 2
    pending = accounts.begin_sign_in("github", "client-1", scope="repo", device_url=f"{address}/device")
    assert pending["user_code"] == "WDJB-MJHT" and pending["verification_uri"] == "https://service.example/device"

    assert accounts.finish_sign_in(pending, permissions=["push"], token_url=f"{address}/token", wait=False, path=book) is None  # not approved yet
    waits = []
    entry = accounts.finish_sign_in(pending, permissions=["push"], token_url=f"{address}/token", sleep=waits.append, path=book)

    assert entry["linked"] and entry["permissions"] == ["push"] and entry["renews_itself"] and len(waits) == 1
    assert accounts.credential("github", "push", path=book) == SECRET
    assert state["requests"][0] == ("/device", {"client_id": "client-1", "scope": "repo"})
    assert state["requests"][1][1] == {"client_id": "client-1", "device_code": "dev-1", "grant_type": accounts.DEVICE_GRANT}


def test_a_sign_in_the_owner_refuses_stores_nothing(book, service):
    address, state = service
    state["deny"] = True
    pending = accounts.begin_sign_in("github", "client-1", device_url=f"{address}/device")

    with pytest.raises(accounts.AccountError, match="refused the sign-in: The owner said no"):
        accounts.finish_sign_in(pending, permissions=["push"], token_url=f"{address}/token", path=book)
    assert not book.exists()


# ---- asking the service ------------------------------------------------------------------------------------


def test_github_is_asked_who_the_token_belongs_to_and_when_it_expires(book, service):
    address, state = service
    accounts.link("github", SECRET, permissions=["read"], path=book)

    result = accounts.check_github(api=address, path=book)

    assert result == {"accepted": True, "status": 200, "login": "the-owner", "expires_at": "2027-02-01T09:30:00+00:00"}
    assert accounts.describe("github", path=book)["expires_at"] == "2027-02-01T09:30:00+00:00"


def test_a_token_github_no_longer_accepts_is_marked(book, service):
    address, _state = service
    accounts.link("github", "a-cancelled-token", permissions=["read"], path=book)

    assert accounts.check_github(api=address, path=book)["accepted"] is False
    assert "no longer accepts this token" in accounts.describe("github", path=book)["problem"]


def test_an_account_allowed_for_nothing_is_not_used_even_to_check_it(book, service):
    address, state = service
    accounts.link("github", SECRET, path=book)

    with pytest.raises(accounts.NotPermitted):
        accounts.check_github(api=address, path=book)
    assert state["requests"] == []
