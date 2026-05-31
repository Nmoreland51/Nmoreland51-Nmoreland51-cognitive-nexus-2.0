import unittest

from modules.provider_router import ProviderInfo, ProviderRequest, ProviderRouter
from modules.providers import rank_ollama_models


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

    def test_default_provider_order_includes_optional_local_transformers(self):
        router = ProviderRouter({"provider_order": []})
        order = router.provider_order(ProviderRequest(prompt="hello"))

        self.assertEqual(order, ["ollama", "openai", "anthropic", "huggingface_local", "fallback"])

    def test_rank_ollama_models_prefers_fast_local_model(self):
        models = [
            "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
            "llama3.2:3b",
        ]

        self.assertEqual(rank_ollama_models(models)[0], "llama3.2:3b")

    def test_resolve_ollama_model_falls_back_from_stale_selection(self):
        router = ProviderRouter({"provider_order": ["ollama", "fallback"]})
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=["llama3.2:3b"],
            base_url="http://localhost:11434",
        )

        model, note = router._resolve_model(ProviderRequest(prompt="hello", model="missing:model"), info)

        self.assertEqual(model, "llama3.2:3b")
        self.assertIn("not installed", note)

    def test_huggingface_local_is_safe_when_unconfigured(self):
        router = ProviderRouter({"provider_order": ["huggingface_local", "fallback"], "hf_local_model": ""})
        info = router.detect_provider("huggingface_local", ttl=0)

        self.assertFalse(info.available)
        self.assertEqual(info.name, "huggingface_local")
        self.assertIn("HF_LOCAL_MODEL", info.message)

    def test_stream_records_provider_attempts_and_fallback_reason(self):
        router = ProviderRouter({"provider_order": ["missing", "fallback"]})
        text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["missing", "fallback"])))

        self.assertIn("Fallback:", text)
        self.assertEqual(router.last_stream_metadata["provider"], "fallback")
        self.assertEqual(router.last_stream_metadata["fallback_reason"], "Unknown provider.")
        self.assertEqual(router.last_stream_metadata["attempts"][0]["provider"], "missing")
        self.assertFalse(router.last_stream_metadata["attempts"][0]["success"])


if __name__ == "__main__":
    unittest.main()
