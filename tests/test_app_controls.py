import unittest
from pathlib import Path
from unittest.mock import patch

import app
from streamlit.testing.v1 import AppTest

# Newer Streamlit resolves a relative AppTest path against this test file, not the working
# directory, so point at app.py in the repo root explicitly.
APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
# Seconds the whole page may take. It shares the machine with the per-tab runs of tests/test_ui_tabs.py;
# at 25 s this test failed once in a parallel run (it passed in four more), so it has the same limit as those.
PAGE_TIMEOUT = 90


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

    def test_the_owners_saved_chat_model_wins_over_a_newly_installed_one(self):
        from modules.nexus_config import DEFAULT_CONFIG
        from ui.sidebar import choose_chat_model

        # Ollama lists the newest model first; qwen2.5-coder:7b was installed after dolphin3:8b.
        installed = ["qwen2.5-coder:7b", "dolphin3:8b"]
        self.assertEqual(DEFAULT_CONFIG["chat_model"], "dolphin3:8b")
        self.assertEqual(choose_chat_model(installed, DEFAULT_CONFIG["chat_model"], "fast"), "dolphin3:8b")
        self.assertEqual(choose_chat_model(installed, "qwen2.5-coder:7b"), "qwen2.5-coder:7b")
        # A saved model that is not installed falls back to the app's guess.
        self.assertEqual(choose_chat_model(["llama3.2:3b"], "dolphin3:8b"), "llama3.2:3b")

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
        app_test = AppTest.from_file(APP_PATH, default_timeout=PAGE_TIMEOUT)
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
        app_test = AppTest.from_file(APP_PATH, default_timeout=PAGE_TIMEOUT)
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
        with patch("ui.chat_tab.add_message") as add_message, patch("ui.chat_tab.save_session_history") as save_history:
            saved = app.persist_assistant_response("Provider answer", {})

        self.assertEqual(saved, "Provider answer")
        add_message.assert_called_once_with("assistant", "Provider answer", meta=None)
        save_history.assert_called_once()

    def test_persist_empty_assistant_response_saves_visible_fallback(self):
        with patch("ui.chat_tab.add_message") as add_message, patch("ui.chat_tab.save_session_history") as save_history:
            saved = app.persist_assistant_response("", {"fallback_reason": "empty stream"})

        self.assertIn("Fallback:", saved)
        self.assertIn("empty stream", saved)
        add_message.assert_called_once_with("assistant", saved, meta=None)
        save_history.assert_called_once()

    def test_persisted_answer_records_how_it_was_produced(self):
        result = {"provider": "ollama", "model": "dolphin3:8b", "success": True, "elapsed": 3.0}
        with patch("ui.chat_tab.add_message") as add_message, patch("ui.chat_tab.save_session_history"):
            app.persist_assistant_response("Provider answer", result)

        meta = add_message.call_args.kwargs["meta"]
        self.assertEqual((meta["provider"], meta["model"], meta["locality"]), ("ollama", "dolphin3:8b", "local"))

    def test_model_check_caption_only_says_working_after_text_came_back(self):
        self.assertIn("has not answered yet", app.model_check_caption(None))
        self.assertIn("answered a test prompt in 9.3s", app.model_check_caption({"ok": True, "seconds": 9.31, "source": "test"}))
        self.assertIn("wrote the last answer", app.model_check_caption({"ok": True, "seconds": None, "source": "answer"}))
        self.assertEqual(app.model_check_caption({"ok": False, "error": "refused"}), "Model check failed: refused")

    def test_context_window_caption_explains_how_the_prompt_was_fitted(self):
        self.assertEqual(app.context_window_caption({}), "")
        line = app.context_window_caption(
            {
                "prompt_tokens_estimated": 883,
                "prompt_tokens_allowed": 900,
                "num_ctx": 2048,
                "reply_tokens": 384,
                "model_window": 131072,
                "limited_by": "speed",
                "trim_steps": ["retrieved knowledge shortened", "retrieved knowledge shortened", "4 oldest recent message(s) left out"],
                "older_messages": 12,
            }
        )
        self.assertIn("about 883 tokens of 900 allowed (limited by how fast this machine reads a prompt)", line)
        self.assertIn("2048-token window that also holds a reply of up to 384 tokens", line)
        self.assertIn("the model itself can read 131072 tokens", line)
        self.assertIn("in this order: retrieved knowledge shortened, 4 oldest recent message(s) left out.", line)
        self.assertIn("12 older message(s) were condensed", line)

    def test_data_locality_caption_states_where_prompts_can_go(self):
        local_first = ["ollama", "openai", "anthropic", "fallback"]

        self.assertIn("stay on this machine", app.data_locality_caption(local_first, False, []))
        blocked = app.data_locality_caption(local_first, False, ["anthropic"])
        self.assertIn("Anthropic is set up but will not be used as a fallback", blocked)
        allowed = app.data_locality_caption(local_first, True, ["openai", "anthropic"])
        self.assertIn("may be sent to OpenAI or Anthropic", allowed)
        cloud_first = app.data_locality_caption(["anthropic", "ollama", "fallback"], False, ["anthropic"])
        self.assertIn("are sent to Anthropic", cloud_first)
        # A cloud provider listed first but without a key cannot receive anything.
        self.assertIn("stay on this machine", app.data_locality_caption(["openai", "ollama", "fallback"], False, []))

    def test_merge_chat_timing_trace_adds_render_save_and_total_ms(self):
        with patch("ui.chat_tab.time.perf_counter", side_effect=[10.25]):
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
