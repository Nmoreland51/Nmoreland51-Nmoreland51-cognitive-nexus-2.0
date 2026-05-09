import unittest

from modules.provider_router import ProviderRequest, ProviderRouter


class ProviderRouterTests(unittest.TestCase):
    def test_fallback_provider_always_returns_text(self):
        router = ProviderRouter({"provider_order": ["fallback"]})
        result = router.generate(ProviderRequest(prompt="hello", provider_order=["fallback"]))

        self.assertIn("Fallback:", result.text)
        self.assertEqual(result.provider, "fallback")

    def test_detect_all_returns_status_objects(self):
        router = ProviderRouter({"provider_order": ["fallback"]})
        statuses = router.detect_all(["fallback"])

        self.assertEqual(len(statuses), 1)
        self.assertTrue(statuses[0].available)
        self.assertEqual(statuses[0].name, "fallback")


if __name__ == "__main__":
    unittest.main()
