import unittest
from unittest.mock import patch

import app
from streamlit.testing.v1 import AppTest


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

    def test_demo_safe_mode_setting_helper(self):
        self.assertTrue(app.is_demo_safe({"demo_safe_mode": True}))
        self.assertFalse(app.is_demo_safe({"demo_safe_mode": False}))
        self.assertFalse(app.is_demo_safe({}))

    def test_get_chat_model_prefers_blackhills_when_installed(self):
        model = app.get_chat_model(
            [
                "llama3.2:3b",
                "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
            ]
        )

        self.assertEqual(model, "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest")

    def test_get_chat_model_prefers_small_model_for_turbo_throughput(self):
        model = app.get_chat_model(
            [
                "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
                "llama3.2:3b",
                "nomic-embed-text:latest",
            ],
            throughput_mode="turbo",
        )

        self.assertEqual(model, "llama3.2:3b")

    def test_demo_safe_sanitizer_hides_local_paths_services_and_env_names(self):
        text = (
            r"C:\Users\Nmore\project\secret.txt "
            "http://localhost:8501/_stcore/health "
            "OPENAI_API_KEY is not set"
        )

        sanitized = app.sanitize_demo_text(text)

        self.assertIn("[local path hidden]", sanitized)
        self.assertIn("[local service hidden]", sanitized)
        self.assertIn("[environment detail hidden]", sanitized)
        self.assertNotIn("C:\\Users", sanitized)
        self.assertNotIn("localhost:8501", sanitized)
        self.assertNotIn("OPENAI_API_KEY", sanitized)

    def test_tab_labels_use_demo_safe_overview_order(self):
        self.assertEqual(
            app.TAB_LABELS[:10],
            [
                "Home / Overview",
                "Chat",
                "Reality-First Research",
                "Web Research",
                "Files / Knowledge",
                "Memory",
                "Image Generation",
                "Gallery",
                "Diagnostics",
                "Settings",
            ],
        )
        self.assertIn("Tools / Utilities", app.TAB_LABELS)

    def test_streamlit_overview_and_demo_safe_mode_render(self):
        app_test = AppTest.from_file("app.py", default_timeout=25)
        app_test.run()

        self.assertEqual(len(app_test.exception), 0)
        self.assertEqual([tab.label for tab in app_test.tabs], app.TAB_LABELS)
        self.assertTrue(
            any(
                "A compact control-room view" in str(getattr(element, "value", ""))
                for element in app_test.caption
            )
        )

        for checkbox in app_test.checkbox:
            if checkbox.label == "Demo Safe Mode":
                checkbox.set_value(True)
                break
        else:
            self.fail("Demo Safe Mode checkbox was not rendered")

        app_test.run()
        self.assertEqual(len(app_test.exception), 0)
        self.assertTrue(
            any(
                "Demo Safe Mode is on" in str(getattr(element, "value", ""))
                for element in [*app_test.info, *app_test.success]
            )
        )

    def test_auto_precision_mode_defaults_on_in_sidebar(self):
        app_test = AppTest.from_file("app.py", default_timeout=25)
        app_test.run()

        self.assertEqual(len(app_test.exception), 0)
        for checkbox in app_test.checkbox:
            if checkbox.label == "Auto Precision Mode":
                self.assertTrue(checkbox.value)
                break
        else:
            self.fail("Auto Precision Mode checkbox was not rendered")

    def test_normalize_assistant_response_joins_streamlit_string_chunks(self):
        response = app.normalize_assistant_response(["Hello", " ", "from Nexus"])

        self.assertEqual(response, "Hello from Nexus")

    def test_empty_assistant_response_message_is_visible(self):
        message = app.empty_assistant_response_message({"fallback_reason": "empty stream"})

        self.assertIn("Fallback:", message)
        self.assertIn("empty stream", message)

    def test_persist_assistant_response_saves_non_empty_assistant_text(self):
        with patch("app.add_message") as add_message, patch("app.save_session_history") as save_history:
            saved = app.persist_assistant_response("Provider answer", {})

        self.assertEqual(saved, "Provider answer")
        add_message.assert_called_once_with("assistant", "Provider answer")
        save_history.assert_called_once()

    def test_persist_empty_assistant_response_saves_visible_fallback(self):
        with patch("app.add_message") as add_message, patch("app.save_session_history") as save_history:
            saved = app.persist_assistant_response("", {"fallback_reason": "empty stream"})

        self.assertIn("Fallback:", saved)
        self.assertIn("empty stream", saved)
        add_message.assert_called_once_with("assistant", saved)
        save_history.assert_called_once()

    def test_merge_chat_timing_trace_adds_render_save_and_total_ms(self):
        with patch("app.time.perf_counter", side_effect=[10.25]):
            result = app.merge_chat_timing_trace(
                {"timings": {"planner_ms": 1.2, "provider_total_ms": 42.0}},
                turn_started=10.0,
                render_ms=12.34,
                save_ms=2.22,
            )

        timings = result["timings"]
        self.assertEqual(timings["render_ms"], 12.3)
        self.assertEqual(timings["save_chat_history_ms"], 2.2)
        self.assertEqual(timings["total_ms"], 250.0)
        self.assertEqual(result["elapsed"], 0.25)

    def test_plan_caption_hidden_for_default_casual_chat(self):
        settings = {
            "advanced_mode": False,
            "show_perf_timings": False,
            "router_config": type("Config", (), {"show_debug": False})(),
        }

        self.assertFalse(app.should_show_plan_caption(settings, {"intent": "casual_chat", "mode": "short"}))
        settings["show_perf_timings"] = True
        self.assertFalse(app.should_show_plan_caption(settings, {"intent": "casual_chat", "mode": "short"}))
        settings["advanced_mode"] = True
        self.assertTrue(app.should_show_plan_caption(settings, {"intent": "casual_chat", "mode": "short"}))


if __name__ == "__main__":
    unittest.main()
