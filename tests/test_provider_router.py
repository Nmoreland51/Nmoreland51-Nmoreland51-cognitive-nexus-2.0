import unittest
from unittest.mock import patch

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

    def test_rank_ollama_models_prefers_blackhills_when_installed(self):
        models = [
            "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
            "llama3.2:3b",
        ]

        self.assertEqual(rank_ollama_models(models)[0], "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest")

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

    def test_stream_ollama_uses_installed_model_when_requested_model_missing(self):
        router = ProviderRouter({"provider_order": ["ollama"]})
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=["llama3.2:3b"],
            base_url="http://localhost:11434",
        )

        def fake_detect(_provider):
            return info

        def fake_stream(_request, _info, model):
            yield f"model={model}"

        router.detect_provider = fake_detect  # type: ignore[method-assign]
        router._stream_ollama = fake_stream  # type: ignore[method-assign]

        text = "".join(router.stream(ProviderRequest(prompt="hello", model="missing:model", provider_order=["ollama"])))

        self.assertEqual(text, "model=llama3.2:3b")
        self.assertEqual(router.last_stream_metadata["model"], "llama3.2:3b")
        self.assertIn("not installed", router.last_stream_metadata["model_note"])
        self.assertIn("not installed", router.last_stream_metadata["attempts"][0]["note"])

    def test_provider_exception_records_attempt_log_and_fallback_reason(self):
        router = ProviderRouter({"provider_order": ["ollama", "fallback"]})
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=["llama3.2:3b"],
            base_url="http://localhost:11434",
        )

        def fake_detect(provider):
            if provider == "ollama":
                return info
            return ProviderInfo(name="fallback", available=True, message="fallback")

        def broken_stream(_request, _info, _model):
            raise RuntimeError("boom from ollama")
            yield ""  # pragma: no cover

        router.detect_provider = fake_detect  # type: ignore[method-assign]
        router._stream_ollama = broken_stream  # type: ignore[method-assign]

        text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"])))

        self.assertIn("Fallback:", text)
        self.assertEqual(router.last_stream_metadata["provider"], "fallback")
        self.assertEqual(router.last_stream_metadata["fallback_reason"], "ollama: boom from ollama")
        self.assertEqual(router.last_stream_metadata["attempts"][0]["provider"], "ollama")
        self.assertFalse(router.last_stream_metadata["attempts"][0]["success"])
        self.assertIn("boom from ollama", router.last_stream_metadata["attempts"][0]["error"])

    def test_empty_ollama_stream_records_failed_attempt_before_fallback(self):
        router = ProviderRouter({"provider_order": ["ollama", "fallback"]})
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=["llama3.2:3b"],
            base_url="http://localhost:11434",
        )

        def fake_detect(provider):
            if provider == "ollama":
                return info
            return ProviderInfo(name="fallback", available=True, message="fallback")

        def empty_stream(_request, _info, _model):
            if False:
                yield ""  # pragma: no cover

        router.detect_provider = fake_detect  # type: ignore[method-assign]
        router._stream_ollama = empty_stream  # type: ignore[method-assign]

        text = "".join(router.stream(ProviderRequest(prompt="hello", provider_order=["ollama", "fallback"])))

        self.assertIn("Fallback:", text)
        self.assertEqual(router.last_stream_metadata["provider"], "fallback")
        self.assertIn("empty response", router.last_stream_metadata["fallback_reason"])
        self.assertFalse(router.last_stream_metadata["attempts"][0]["success"])

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

    def test_ollama_stream_sends_fast_generation_options(self):
        router = ProviderRouter({"provider_order": ["ollama"], "ollama_keep_alive": "45m"})
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=["llama3.2:3b"],
            base_url="http://localhost:11434",
        )
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield '{"response":"Yo","done":false}'
                yield '{"response":"","done":true,"eval_count":120,"eval_duration":2000000000,"prompt_eval_count":20,"prompt_eval_duration":500000000}'

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

        request = ProviderRequest(
            prompt="hello",
            model="llama3.2:3b",
            options={"num_ctx": 1024},
            timeout=12.0,
            max_tokens=88,
        )

        with patch("modules.provider_router.OLLAMA_SESSION.post", side_effect=fake_post):
            text = "".join(router._stream_ollama(request, info, "llama3.2:3b"))

        self.assertEqual(text, "Yo")
        self.assertEqual(captured["json"]["keep_alive"], "45m")
        self.assertTrue(captured["json"]["stream"])
        self.assertEqual(captured["json"]["options"]["num_predict"], 88)
        self.assertEqual(captured["json"]["options"]["num_ctx"], 1024)
        self.assertEqual(captured["timeout"], (5.0, 12.0))
        self.assertEqual(router._last_ollama_throughput["eval_count"], 120)
        self.assertEqual(router._last_ollama_throughput["tokens_per_second"], 60.0)

    def test_ollama_stream_extends_timeout_for_auto_resolved_blackhills_model(self):
        router = ProviderRouter({"provider_order": ["ollama"], "ollama_keep_alive": "45m"})
        model = "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest"
        info = ProviderInfo(
            name="ollama",
            available=True,
            message="ok",
            models=[model],
            base_url="http://localhost:11434",
        )
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield '{"response":"Yo","done":false}'
                yield '{"response":"","done":true}'

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

        request = ProviderRequest(
            prompt="hello",
            model="",
            options={"num_ctx": 1024},
            timeout=12.0,
            max_tokens=88,
        )

        with patch("modules.provider_router.OLLAMA_SESSION.post", side_effect=fake_post):
            text = "".join(router._stream_ollama(request, info, model))

        self.assertEqual(text, "Yo")
        self.assertEqual(captured["json"]["model"], model)
        self.assertEqual(captured["timeout"], (5.0, 180.0))


if __name__ == "__main__":
    unittest.main()
