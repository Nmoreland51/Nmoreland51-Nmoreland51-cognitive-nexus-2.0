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
