import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cognitive_nexus_ai as app


def build_core():
    core = app.CognitiveNexusCore.__new__(app.CognitiveNexusCore)
    core.learning_system = SimpleNamespace(
        refresh_all_knowledge=lambda: "refreshed",
        handle_memory_command=lambda message: None,
        extract_turn_signals=lambda message, recent_messages=None: app.TurnSignals(),
        observe_turn=lambda message, signals: app.AdaptivePolicy(),
        build_context_bundle=lambda message, recent_messages=None, signals=None, policy=None: app.ContextBundle(
            policy=policy or app.AdaptivePolicy(),
            short_term_context=["User: context"],
        ),
        add_conversation=lambda user, assistant, route="", signals=None, used_web_search=False: {
            "turn_id": "turn_test",
            "feedback_state": {"rating": "", "correction": ""},
        },
        get_memory_overview=lambda: {},
    )
    core.search_system = SimpleNamespace(search_web=lambda query, max_results=5: {"results": []})
    core.fallback_system = app.FallbackResponseSystem()
    core.openchat_service = SimpleNamespace(
        is_ready_for_interactive_chat=lambda: False,
        generate_response=lambda *args, **kwargs: None,
    )
    core.ollama_manager = SimpleNamespace(generate_response=lambda *args, **kwargs: None)
    core._image_generator = None
    core.current_provider = "fallback"
    core._provider_checked = True
    return core


class IntentRoutingTests(unittest.TestCase):
    def test_greetings_route_to_casual_chat(self):
        core = build_core()

        decision = core.determine_intent("hello there")

        self.assertEqual(decision.route, "casual_chat")
        self.assertEqual(decision.reason, "casual_or_supportive_turn")

    def test_casual_banter_routes_to_casual_chat(self):
        core = build_core()

        decision = core.determine_intent("tell me a joke")

        self.assertEqual(decision.route, "casual_chat")

    def test_general_knowledge_routes_to_local_knowledge(self):
        core = build_core()

        decision = core.determine_intent("what is photosynthesis")

        self.assertEqual(decision.route, "local_knowledge")
        self.assertEqual(decision.search_query, "")

    def test_explicit_search_routes_to_forced_web_search(self):
        core = build_core()

        decision = core.determine_intent("search the web for streamlit session state")

        self.assertEqual(decision.route, "forced_web_search")
        self.assertEqual(decision.search_query, "streamlit session state")

    def test_current_info_routes_to_web_search(self):
        core = build_core()

        decision = core.determine_intent("what's the weather today")

        self.assertEqual(decision.route, "web_search")
        self.assertEqual(decision.reason, "time_sensitive_request")

    def test_ambiguous_factual_prompt_stays_local(self):
        core = build_core()

        decision = core.determine_intent("who is Ada Lovelace")

        self.assertEqual(decision.route, "local_knowledge")

    def test_short_follow_up_routes_to_casual_chat(self):
        core = build_core()

        decision = core.determine_intent("tell me more")

        self.assertEqual(decision.route, "casual_chat")

    def test_process_message_uses_local_handler_for_local_requests(self):
        core = build_core()

        with patch.object(core, "_handle_local_query", return_value=app.ChatResult(answer="local answer")) as local_mock, \
             patch.object(core, "_handle_search_query", return_value=app.ChatResult(answer="search answer", used_web_search=True)) as search_mock:
            response = core.process_message("explain recursion", enable_search=True, show_sources=True)

        local_mock.assert_called_once()
        search_mock.assert_not_called()
        self.assertIn("local answer", response.answer)
        self.assertIn("Nathaniel", response.answer)
        self.assertEqual(response.route, "local_knowledge")

    def test_process_message_uses_search_for_current_requests(self):
        core = build_core()
        expected = app.ChatResult(
            answer="Web search used for current information.\n\nsearch answer",
            used_web_search=True,
            search_note="Web search used for current information.",
            route="web_search",
            route_reason="time_sensitive_request",
        )

        with patch.object(core, "_handle_search_query", return_value=expected) as search_mock, \
             patch.object(core, "_handle_local_query", return_value=app.ChatResult(answer="local")):
            response = core.process_message("latest OpenAI news", enable_search=True, show_sources=True)

        search_mock.assert_called_once()
        self.assertTrue(response.used_web_search)
        self.assertEqual(response.search_note, "Web search used for current information.")
        self.assertEqual(response.route, "web_search")
        self.assertIn("Cognitive Nexus AI", response.answer)
        self.assertIn("Nathaniel", response.answer)

    def test_process_message_falls_back_locally_when_search_disabled(self):
        core = build_core()

        with patch.object(core, "_handle_local_query", return_value=app.ChatResult(answer="local answer")), \
             patch.object(core, "_handle_search_query", return_value=app.ChatResult(answer="search answer", used_web_search=True)):
            response = core.process_message("current bitcoin price", enable_search=False, show_sources=True)

        self.assertFalse(response.used_web_search)
        self.assertEqual(response.route, "web_search")
        self.assertEqual(
            response.search_note,
            "Live web search is turned off, so this answer is based on local knowledge.",
        )
        self.assertIn(response.search_note, response.answer)
        self.assertIn("Nathaniel", response.answer)

    def test_search_handler_includes_short_note_and_optional_sources(self):
        core = build_core()
        core.search_system = SimpleNamespace(
            search_web=lambda query, max_results=5: {
                "results": [
                    {
                        "title": "Example Result",
                        "snippet": "This is a relevant snippet.",
                        "url": "https://example.com",
                        "source": "Example",
                        "type": "search_result",
                    }
                ]
            }
        )

        response = core._handle_search_query(
            "latest OpenAI news",
            "context",
            show_sources=True,
            route="web_search",
            route_reason="time_sensitive_request",
        )

        self.assertTrue(response.used_web_search)
        self.assertEqual(response.search_note, "Web search used for current information.")
        self.assertIn("Web search used for current information.", response.answer)
        self.assertIn("**Sources:**", response.answer)
        self.assertIn("Nathaniel", response.answer)

    def test_identity_query_mentions_nathaniel(self):
        core = build_core()

        response = core.process_message("who are you", enable_search=True, show_sources=True)

        self.assertIn("Cognitive Nexus AI", response.answer)
        self.assertIn("Nathaniel", response.answer)


if __name__ == "__main__":
    unittest.main()
