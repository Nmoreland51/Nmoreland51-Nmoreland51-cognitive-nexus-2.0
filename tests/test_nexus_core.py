import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.chat_profile import ChatProfile
from modules.context_manager import load_user_facts
from modules.nexus_core import NexusCore
from modules.reality_research_agent import ResearchReport
from nexus_router import RouterConfig


class NexusCoreTests(unittest.TestCase):
    def base_chat_settings(self, provider_order=None):
        return {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="fake-local-model", enabled=True),
            "provider_order": provider_order or ["ollama", "fallback"],
            "selected_model": "fake-local-model",
            "base_url": "http://localhost:11434",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
            "enable_reality_grounding": False,
            "enable_reality_first_reasoning": False,
            "auto_precision_mode": True,
            "response_mode": "auto",
            "verbosity_level": 1,
            "reasoning_depth": 1,
            "staged_streaming": False,
        }

    def test_core_fallback_chat_response(self):
        core = NexusCore()
        settings = {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="", enabled=True),
            "provider_order": ["fallback"],
            "selected_model": "",
            "base_url": "",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
        }
        answer = core.generate_chat_response("hello", [], settings)

        self.assertIn("Fallback:", answer)
        self.assertIn("provider", core.last_provider_result)

    def test_fallback_chat_uses_local_knowledge_when_retrieved(self):
        core = NexusCore()

        class FakeResearchModule:
            def semantic_search(self, query, top_k=3):
                return [
                    {
                        "title": "Cognitive Nexus notes",
                        "url": "local://notes/cognitive-nexus",
                        "text": "Cognitive Nexus stores Markdown notes, research reports, and retrieved knowledge chunks for local-first recall.",
                        "score": 0.91,
                    }
                ]

        core.get_research_module = lambda: FakeResearchModule()  # type: ignore[method-assign]
        settings = {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="", enabled=True),
            "provider_order": ["fallback"],
            "selected_model": "",
            "base_url": "",
            "use_memory": False,
            "use_knowledge_for_chat": True,
            "knowledge_top_k": 3,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
            "enable_reality_grounding": False,
        }

        answer = core.generate_chat_response("what does Cognitive Nexus store in local knowledge?", [], settings)

        self.assertIn("extractive answer from saved material", answer)
        self.assertIn("Markdown notes", answer)
        self.assertEqual(core.last_provider_result.get("provider"), "local_knowledge_fallback")
        self.assertEqual(core.last_provider_result.get("sources"), 1)
        self.assertEqual(core.last_retrieval.get("used_count"), 1)

    def test_explicit_memory_command_works_without_adaptive_memory_or_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "user_profile.json"
            with patch("modules.context_manager.USER_PROFILE_FILE", profile_path):
                core = NexusCore()
                settings = {
                    "chat_profile": ChatProfile(enabled=False),
                    "router_config": RouterConfig(default_model="", enabled=True),
                    "provider_order": ["fallback"],
                    "selected_model": "",
                    "base_url": "",
                    "use_memory": False,
                    "use_knowledge_for_chat": False,
                    "use_web_for_chat": False,
                    "show_sources": True,
                    "generation_timeout": 5.0,
                    "max_context_chars": 4000,
                    "recent_message_limit": 4,
                    "enable_reality_grounding": False,
                }

                answer = core.generate_chat_response("remember that my preferred editor is VS Code", [], settings)

                self.assertIn("I'll remember that", answer)
                self.assertEqual(core.last_provider_result.get("provider"), "local_memory")
                self.assertEqual(load_user_facts(profile_path), ["my preferred editor is VS Code"])

    def test_exact_reply_instruction_bypasses_provider_and_grounding_rewrite(self):
        core = NexusCore()
        settings = {
            "chat_profile": ChatProfile(enabled=True),
            "router_config": RouterConfig(default_model="fake-local-model", enabled=True),
            "provider_order": ["ollama", "fallback"],
            "selected_model": "fake-local-model",
            "base_url": "http://localhost:11434",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
            "enable_reality_grounding": True,
            "enable_reality_first_reasoning": True,
            "epistemic_mode": "strict_fact",
            "response_mode": "short",
            "verbosity_level": 1,
            "reasoning_depth": 1,
            "staged_streaming": False,
        }

        answer = core.generate_chat_response("Reply with exactly: Core stability check passed.", [], settings)

        self.assertEqual(answer, "Core stability check passed.")
        self.assertEqual(core.last_provider_result.get("provider"), "direct_response")
        self.assertEqual(core.last_reality_audit.get("reason"), "direct_response_instruction")

    def test_chat_suppresses_prompt_scaffolding_from_model_output(self):
        core = NexusCore()

        def fake_stream(_request):
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield 'User request: "Cognitive Nexus is online."\n\n'
            yield "Response plan:\n- Intent: concise_answer\n- Mode: short\n\n"
            yield "Answer: Cognitive Nexus is online and ready."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="fake-local-model", enabled=True),
            "provider_order": ["ollama", "fallback"],
            "selected_model": "fake-local-model",
            "base_url": "http://localhost:11434",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
            "enable_reality_grounding": False,
            "enable_reality_first_reasoning": False,
            "response_mode": "short",
            "verbosity_level": 1,
            "reasoning_depth": 1,
            "staged_streaming": False,
        }

        answer = "".join(core.stream_chat_response("say nexus online", [], settings))

        self.assertEqual(answer, "Cognitive Nexus is online and ready.")
        self.assertNotIn("Response plan", core.last_provider_result["text"])
        self.assertNotIn("User request", core.last_provider_result["text"])

    def test_simple_chat_calls_provider_after_auto_precision_planning(self):
        core = NexusCore()
        seen_prompts = []

        def fake_stream(request):
            seen_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Hello from the provider."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()

        answer = core.generate_chat_response("hello", [], self.base_chat_settings())

        self.assertEqual(answer, "Hello from the provider.")
        self.assertTrue(seen_prompts)
        self.assertIn("Adaptive response plan", seen_prompts[0])
        self.assertNotIn("Planner:", answer)
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertTrue(core.last_response_plan)

    def test_simple_fact_still_produces_provider_answer_after_planning(self):
        core = NexusCore()

        def fake_stream(_request):
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Cognitive Nexus is a local-first AI control center."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()

        answer = core.generate_chat_response("What is Cognitive Nexus?", [], self.base_chat_settings())

        self.assertIn("local-first AI control center", answer)
        self.assertEqual(core.last_response_plan.get("intent"), "simple_fact")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")

    def test_empty_provider_stream_returns_visible_fallback_not_silence(self):
        core = NexusCore()

        def fake_stream(_request):
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": False,
                "attempts": [{"provider": "ollama", "success": False, "error": "empty"}],
                "fallback_reason": "empty",
            }
            if False:
                yield ""

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()

        answer = core.generate_chat_response("hello", [], self.base_chat_settings())

        self.assertIn("Fallback: provider returned no visible assistant response", answer)
        self.assertEqual(core.last_provider_result.get("text"), answer)
        self.assertTrue(core.last_provider_result.get("success"))

    def test_status_snapshot_contains_comfyui_and_providers(self):
        core = NexusCore()
        snapshot = core.status_snapshot(["fallback"])

        self.assertIn("providers", snapshot)
        self.assertIn("comfyui", snapshot)

    def test_research_command_routes_to_reality_agent(self):
        core = NexusCore()
        settings = {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="", enabled=True),
            "provider_order": ["fallback"],
            "selected_model": "",
            "base_url": "",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
            "enable_reality_research_agent": True,
            "enable_reality_grounding": False,
        }
        fake_report = ResearchReport(
            query="Cognitive Nexus",
            timestamp="2026-05-09T00:00:00",
            request={},
            summary="Grounded summary.",
            final_answer="Grounded answer.",
        )
        core.run_reality_research = lambda *_args, **_kwargs: fake_report  # type: ignore[method-assign]

        answer = "".join(core.stream_chat_response("research Cognitive Nexus", [], settings))

        self.assertIn("Reality-First Research Agent engaged", answer)
        self.assertIn("Grounded answer", answer)
        self.assertEqual(core.last_provider_result.get("provider"), "reality_research_agent")


if __name__ == "__main__":
    unittest.main()
