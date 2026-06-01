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


if __name__ == "__main__":
    unittest.main()
