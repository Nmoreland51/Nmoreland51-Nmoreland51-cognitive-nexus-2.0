import unittest

from modules.core_health import (
    check_imports,
    check_provider_status,
    choose_local_probe_order,
    run_provider_probe,
    summarize_health,
)
from modules.provider_router import ProviderInfo, ProviderResult
from modules.providers import FALLBACK_RESPONSE


class CoreHealthTests(unittest.TestCase):
    def test_check_imports_reports_success_and_failure(self):
        rows = check_imports(("json", "definitely_missing_cognitive_nexus_module"))

        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[1]["status"], "error")
        self.assertIn("ModuleNotFoundError", rows[1]["message"])

    def test_provider_status_normalizes_detection_rows(self):
        class FakeRouter:
            def detect_provider(self, name, ttl=0):
                return ProviderInfo(
                    name=name,
                    available=name == "ollama",
                    message="ready" if name == "ollama" else "offline",
                    models=["llama3.2:3b"] if name == "ollama" else [],
                    base_url="http://localhost:11434" if name == "ollama" else "",
                )

        rows = check_provider_status(["ollama", "fallback"], config={"provider_order": []}, router=FakeRouter())

        self.assertEqual(rows[0]["name"], "ollama")
        self.assertEqual(rows[0]["status"], "ready")
        self.assertEqual(rows[0]["model_count"], 1)
        self.assertEqual(rows[1]["status"], "offline")

    def test_probe_order_keeps_local_providers_and_fallback(self):
        order = choose_local_probe_order(["openai", "ollama", "anthropic", "fallback"])

        self.assertEqual(order, ["ollama", "fallback"])

    def test_provider_probe_requires_real_provider_not_fallback(self):
        class FakeFallbackRouter:
            def __init__(self, _config):
                pass

            def generate(self, _request):
                return ProviderResult(
                    text=FALLBACK_RESPONSE,
                    provider="fallback",
                    success=True,
                    attempts=[{"provider": "fallback", "success": True}],
                )

        probe = run_provider_probe(
            ["ollama", "fallback"],
            config={"provider_order": ["ollama", "fallback"], "ollama_url": "http://localhost:11434"},
            router_factory=FakeFallbackRouter,
        )

        self.assertEqual(probe["status"], "error")
        self.assertFalse(probe["success"])
        self.assertIn("fallback", probe["error"].lower())

    def test_provider_probe_accepts_real_local_provider(self):
        class FakeOllamaRouter:
            def __init__(self, _config):
                pass

            def generate(self, request):
                self.request = request
                return ProviderResult(
                    text="Cognitive Nexus works.",
                    provider="ollama",
                    model="llama3.2:3b",
                    success=True,
                    attempts=[{"provider": "ollama", "success": True}],
                )

        probe = run_provider_probe(
            ["ollama", "fallback"],
            config={"provider_order": ["ollama", "fallback"], "ollama_url": "http://localhost:11434"},
            router_factory=FakeOllamaRouter,
        )

        self.assertEqual(probe["status"], "ok")
        self.assertTrue(probe["success"])
        self.assertEqual(probe["provider"], "ollama")

    def test_summarize_health_marks_degraded_without_real_model_provider(self):
        summary = summarize_health(
            import_rows=[{"status": "ok"}],
            provider_rows=[{"name": "fallback", "available": True}],
            storage_rows=[{"required": True, "status": "ok"}],
            probe={"status": "not_run"},
        )

        self.assertEqual(summary["status"], "degraded")
        self.assertFalse(summary["provider_ready"])


if __name__ == "__main__":
    unittest.main()
