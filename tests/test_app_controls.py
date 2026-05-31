import unittest

import app


class AppControlsTests(unittest.TestCase):
    def test_normalize_provider_order_dedupes_and_keeps_fallback_last(self):
        order = app.normalize_provider_order(
            ["fallback", "ollama", "ollama", "missing", "openai"],
            ["ollama", "openai", "fallback"],
        )

        self.assertEqual(order, ["ollama", "openai", "fallback"])

    def test_normalize_provider_order_adds_fallback_when_missing(self):
        order = app.normalize_provider_order(["openai"], ["ollama", "openai", "fallback"])

        self.assertEqual(order, ["openai", "fallback"])

    def test_normalize_provider_order_all_invalid_returns_fallback(self):
        order = app.normalize_provider_order(["missing"], ["ollama", "fallback"])

        self.assertEqual(order, ["fallback"])


if __name__ == "__main__":
    unittest.main()
