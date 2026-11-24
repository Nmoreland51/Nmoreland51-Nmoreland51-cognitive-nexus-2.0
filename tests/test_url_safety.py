import os
import socket
import unittest
from unittest.mock import patch

import requests

from modules import web_research
from modules.url_safety import UnsafeURLError, check_public_url, safe_get

PUBLIC = "https://93.184.216.34"  # literal addresses need no DNS, so these tests run offline


def _addrinfo(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


def _response(status=200, location=None):
    response = requests.Response()
    response.status_code = status
    response._content = b""  # a finished response with no open connection, so close() is a no-op
    response._content_consumed = True
    if location:
        response.headers["Location"] = location
    return response


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append((url, kwargs))
        return self.responses.pop(0)


class UrlSafetyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"ALLOW_PRIVATE_URL_FETCH": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_public_address_is_allowed(self):
        check_public_url(f"{PUBLIC}/page?x=1")

    def test_local_and_private_addresses_are_blocked(self):
        for url in (
            "http://127.0.0.1:11434/api/tags",
            "http://localhost:8501/",
            "http://192.168.1.1/admin",
            "http://10.0.0.5/",
            "http://172.16.4.2/",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.64.0.1/",
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    check_public_url(url)

    def test_other_schemes_and_missing_hosts_are_blocked(self):
        for url in ("file:///C:/Windows/win.ini", "ftp://93.184.216.34/file", "gopher://93.184.216.34/", "http:///nohost", ""):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    check_public_url(url)

    def test_hostname_that_resolves_to_a_private_address_is_blocked(self):
        with patch("modules.url_safety.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34", "10.0.0.7")):
            with self.assertRaisesRegex(UnsafeURLError, "local or private"):
                check_public_url("https://innocent-looking.example/")

    def test_hostname_that_resolves_to_public_addresses_is_allowed(self):
        with patch("modules.url_safety.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            check_public_url("https://example.com/")

    def test_override_allows_private_hosts_on_purpose(self):
        with patch.dict(os.environ, {"ALLOW_PRIVATE_URL_FETCH": "true"}):
            check_public_url("http://127.0.0.1:11434/api/tags")
            with self.assertRaises(UnsafeURLError):
                check_public_url("file:///etc/passwd")  # still http(s) only

    def test_redirect_to_a_private_address_is_not_followed(self):
        session = FakeSession([_response(302, "http://127.0.0.1:11434/api/tags"), _response(200)])

        with self.assertRaises(UnsafeURLError):
            safe_get(f"{PUBLIC}/start", session=session)

        self.assertEqual([url for url, _ in session.requested], [f"{PUBLIC}/start"])

    def test_public_redirects_are_followed_one_checked_hop_at_a_time(self):
        session = FakeSession([_response(301, "/moved"), _response(200)])

        response = safe_get(f"{PUBLIC}/start", session=session, timeout=3)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([url for url, _ in session.requested], [f"{PUBLIC}/start", f"{PUBLIC}/moved"])
        self.assertTrue(all(kwargs["allow_redirects"] is False for _, kwargs in session.requested))

    def test_redirect_loops_stop(self):
        session = FakeSession([_response(302, "/again")] * 10)

        with self.assertRaisesRegex(UnsafeURLError, "Too many redirects"):
            safe_get(f"{PUBLIC}/start", session=session, max_redirects=3)

        self.assertEqual(len(session.requested), 4)

    def test_scrape_url_refuses_a_local_address_without_requesting_it(self):
        session = FakeSession([])
        with patch.object(web_research, "_http_session", return_value=session):
            page = web_research.scrape_url("http://127.0.0.1:11434/api/tags?url-safety-test")

        self.assertFalse(page["success"])
        self.assertIn("local or private", page["error"])
        self.assertEqual(session.requested, [])


if __name__ == "__main__":
    unittest.main()


# ---- the connection goes to the address that was checked (DNS rebinding) -------------------------------

import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import pytest  # noqa: E402

from modules import url_safety  # noqa: E402


class _Site(BaseHTTPRequestHandler):
    """A stand-in for a public web server; it records the Host it was asked for."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.hosts.append(self.headers.get("Host"))
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", f"http://second.test:{self.server.server_address[1]}/final")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"hello"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def rebinding(monkeypatch):
    """A name server that gives a good address the first time a name is asked for and a private one ever after."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    server.hosts = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    asked: list[str] = []
    system = url_safety._system_getaddrinfo

    def lookup(host, port, *args, **kwargs):
        if isinstance(host, str) and host.endswith(".test"):
            asked.append(host)
            return system("127.0.0.1" if asked.count(host) == 1 else "10.9.9.9", port, *args, **kwargs)
        return system(host, port, *args, **kwargs)

    monkeypatch.setattr(url_safety, "_system_getaddrinfo", lookup)
    # The stand-in on this machine plays the public server; the address handed out afterwards is private.
    monkeypatch.setattr(url_safety, "_is_public_address", lambda address: address == "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.delenv("ALLOW_PRIVATE_URL_FETCH", raising=False)
    yield type("Rebinding", (), {"port": server.server_address[1], "hosts": server.hosts, "asked": asked})
    server.shutdown()
    server.server_close()


def test_the_request_connects_to_the_address_that_was_checked(rebinding):
    """Checked once, connected once, to the same address: the second answer of the name server is never used."""

    response = url_safety.safe_get(f"http://rebind.test:{rebinding.port}/page", timeout=5)

    assert response.status_code == 200 and response.text == "hello"
    assert rebinding.hosts == [f"rebind.test:{rebinding.port}"]  # the site still sees the name it was asked for
    assert rebinding.asked == ["rebind.test"]  # the name server was asked once; the connection did not ask it again


def test_without_the_pin_the_same_name_server_would_have_sent_the_connection_elsewhere(rebinding):
    """What the pin prevents, shown by taking it away: the lookup made to connect gets the private address."""

    assert url_safety.public_addresses(f"http://rebind.test:{rebinding.port}/page") == ["127.0.0.1"]
    second = socket.getaddrinfo("rebind.test", rebinding.port, type=socket.SOCK_STREAM)
    assert {entry[4][0] for entry in second} == {"10.9.9.9"}


def test_every_redirect_hop_is_checked_and_pinned_by_itself(rebinding):
    response = url_safety.safe_get(f"http://rebind.test:{rebinding.port}/start", timeout=5)

    assert response.status_code == 200 and response.url == f"http://second.test:{rebinding.port}/final"
    assert rebinding.hosts == [f"rebind.test:{rebinding.port}", f"second.test:{rebinding.port}"]
    assert rebinding.asked == ["rebind.test", "second.test"]


def test_a_pin_holds_for_its_block_and_its_thread_only(monkeypatch):
    system = url_safety._system_getaddrinfo
    monkeypatch.setattr(url_safety, "_system_getaddrinfo", lambda host, port, *a, **k: system(host, port, *a, **k) if host[:1].isdigit() else [("from the name server", host)])
    elsewhere = []

    with url_safety.pinned("Example.ORG.", ["127.0.0.1"]):
        mine = socket.getaddrinfo("example.org", 80, type=socket.SOCK_STREAM)
        other = threading.Thread(target=lambda: elsewhere.append(socket.getaddrinfo("example.org", 80)))
        other.start()
        other.join()
        with url_safety.pinned("example.org", ["127.0.0.2"]):
            assert {entry[4][0] for entry in socket.getaddrinfo("example.org", 80, type=socket.SOCK_STREAM)} == {"127.0.0.2"}
        assert {entry[4][0] for entry in socket.getaddrinfo("example.org", 80, type=socket.SOCK_STREAM)} == {"127.0.0.1"}  # the outer pin is back
        assert socket.getaddrinfo("another.example", 80) == [("from the name server", "another.example")]  # only the pinned name

    assert {entry[4][0] for entry in mine} == {"127.0.0.1"}
    assert elsewhere == [[("from the name server", "example.org")]]  # another thread is not affected
    assert socket.getaddrinfo("example.org", 80) == [("from the name server", "example.org")]  # and afterwards neither is this one
    with url_safety.pinned("example.org", []):  # nothing was checked here (a proxy, or private fetching allowed): nothing is pinned
        assert socket.getaddrinfo("example.org", 80) == [("from the name server", "example.org")]
