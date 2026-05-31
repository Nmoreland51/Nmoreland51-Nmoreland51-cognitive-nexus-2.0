#!/usr/bin/env python3
"""Lightweight root-discovery tests for web research URL handling."""

from __future__ import annotations

import unittest
from urllib.parse import urlparse

from modules.research import validate_url as normalize_url


def validate_url(url: str) -> tuple[bool, str]:
    """Validate URLs against the current Streamlit app URL normalizer."""

    try:
        normalized = normalize_url(url)
    except ValueError as exc:
        return False, str(exc)

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return False, "Invalid URL scheme"
    if not parsed.netloc or "." not in parsed.netloc:
        return False, "Invalid domain name"
    return True, normalized


class WebResearchSimpleTests(unittest.TestCase):
    def test_url_validation(self) -> None:
        cases = [
            ("example.com", True, "https://example.com"),
            ("https://example.com", True, "https://example.com"),
            ("http://example.com", True, "http://example.com"),
            ("invalid-url", False, "Invalid domain name"),
            ("https://httpbin.org/html", True, "https://httpbin.org/html"),
            ("not-a-url", False, "Invalid domain name"),
            ("", False, "Enter a URL first"),
            ("ftp://example.com", False, "Invalid domain name"),
            ("https://subdomain.example.com/path", True, "https://subdomain.example.com/path"),
        ]

        for url, expected_valid, expected_result in cases:
            with self.subTest(url=url):
                is_valid, result = validate_url(url)
                self.assertEqual(is_valid, expected_valid)
                if expected_valid:
                    self.assertEqual(result, expected_result)
                else:
                    self.assertIn(expected_result, result)

    def test_dependencies_import(self) -> None:
        import requests  # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401


if __name__ == "__main__":
    unittest.main()
