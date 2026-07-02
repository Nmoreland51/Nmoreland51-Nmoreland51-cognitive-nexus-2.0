import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.chat_profile import ChatProfile
from modules.context_manager import load_user_facts
from modules.nexus_core import NexusCore
from modules.reality_research_agent import ResearchReport
from nexus_router import RouterConfig


GENERIC_REFUSAL_TEXT = "I cannot fulfill requests that involve harm or illegal activities"


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
            "enable_response_self_critic": False,
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
            "enable_response_self_critic": False,
        }
        answer = core.generate_chat_response("What is Cognitive Nexus?", [], settings)

        self.assertIn("Fallback:", answer)
        self.assertIn("provider", core.last_provider_result)

    def test_blackhills_model_keeps_longer_timeout_for_casual_chat(self):
        core = NexusCore()
        model = "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest"
        settings = self.base_chat_settings()
        settings["selected_model"] = model
        settings["router_config"] = RouterConfig(default_model=model, enabled=True)
        settings["generation_timeout"] = 600.0
        captured = {}

        def fake_stream(request):
            captured["timeout"] = request.timeout
            captured["model"] = request.model
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": request.model,
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Hey, ready."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": [model], "name": "ollama"},
        )()

        answer = core.generate_chat_response("sup", [], settings)

        self.assertEqual(answer, "Hey, ready.")
        self.assertEqual(captured["model"], model)
        self.assertGreaterEqual(captured["timeout"], 75.0)
        self.assertLessEqual(captured["timeout"], 180.0)

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

        answer = core.generate_chat_response("What is Cognitive Nexus?", [], self.base_chat_settings())

        self.assertEqual(answer, "Hello from the provider.")
        self.assertTrue(seen_prompts)
        self.assertIn("Answer rules", seen_prompts[0])
        self.assertNotIn("Planner:", answer)
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertTrue(core.last_response_plan)
        timings = core.last_provider_result.get("timings", {})
        for key in (
            "planner_ms",
            "context_ms",
            "retrieval_ms",
            "provider_first_token_ms",
            "provider_total_ms",
            "render_ms",
            "total_ms",
        ):
            self.assertIn(key, timings)

    def test_turbo_throughput_profile_caps_generation_options(self):
        core = NexusCore()
        captured = {}

        def fake_stream(request):
            captured["options"] = dict(request.options)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": request.model,
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
                "throughput": {"tokens_per_second": 96.5, "eval_count": 96},
            }
            yield "Fast local answer."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["llama3.2:3b"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["throughput_mode"] = "turbo"
        settings["target_tokens_per_second"] = 120
        settings["selected_model"] = "llama3.2:3b"

        answer = core.generate_chat_response("What is Cognitive Nexus?", [], settings)

        self.assertEqual(answer, "Fast local answer.")
        self.assertLessEqual(captured["options"]["num_ctx"], 1024)
        self.assertLessEqual(captured["options"]["num_predict"], 220)
        self.assertEqual(captured["options"]["num_batch"], 512)
        self.assertEqual(captured["options"]["top_k"], 20)
        self.assertEqual(core.last_provider_result["throughput"]["mode"], "turbo")
        self.assertEqual(core.last_provider_result["throughput"]["provider_tokens_per_second"], 96.5)

    def test_casual_chat_uses_provider_path_without_stale_context(self):
        core = NexusCore()
        seen_prompts = []

        class FailingResearchModule:
            def semantic_search(self, *_args, **_kwargs):
                raise AssertionError("casual chat should not retrieve knowledge")

        def fake_stream(request):
            seen_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Yo. What are we working on?"

        core.get_research_module = lambda: FailingResearchModule()  # type: ignore[method-assign]
        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_knowledge_for_chat"] = True
        messages = [
            {"role": "user", "content": "Where is my USPS package?"},
            {"role": "assistant", "content": "Check Click-N-Ship, Informed Delivery, Amazon, and Sour Patch Kids notes."},
        ]

        answer = core.generate_chat_response("sup", messages, settings)

        self.assertTrue(answer.strip())
        self.assertIn("?", answer)
        self.assertEqual(core.last_response_plan.get("intent"), "casual_chat")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"), "greeting")
        self.assertGreaterEqual(int(core.last_response_plan.get("max_tokens") or 0), 100)
        self.assertLessEqual(int(core.last_response_plan.get("max_tokens") or 999), 160)
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertEqual(core.last_provider_result.get("model"), "fake-local-model")
        self.assertEqual(core.last_provider_result.get("attempts"), [{"provider": "ollama", "success": True}])
        self.assertFalse(core.last_retrieval.get("enabled"))
        self.assertEqual(core.last_retrieval.get("skipped_reason"), "minimal_context")
        self.assertFalse(core.last_epistemic_assessment.get("enabled"))
        self.assertTrue(seen_prompts)
        prompt = seen_prompts[0]
        for stale_term in ("USPS", "Click-N-Ship", "Informed Delivery", "Amazon", "Sour Patch"):
            self.assertNotIn(stale_term, prompt)
            self.assertNotIn(stale_term, answer)

    def test_casual_follow_up_ignores_previous_unrelated_topics(self):
        core = NexusCore()
        seen_prompts = []

        class FailingResearchModule:
            def semantic_search(self, *_args, **_kwargs):
                raise AssertionError("casual follow-up should not retrieve stale knowledge")

        def fake_stream(request):
            seen_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "I'm good. What's the move?"

        core.get_research_module = lambda: FailingResearchModule()  # type: ignore[method-assign]
        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True
        messages = [
            {"role": "user", "content": "sup"},
            {"role": "assistant", "content": "Sup. What's the move?"},
            {
                "role": "assistant",
                "content": "Stable complexity, emergence, physics, biology, and AI abstraction notes from old research.",
            },
        ]

        answer = core.generate_chat_response("Not much. how are you?", messages, settings)

        self.assertTrue(answer.strip())
        self.assertIn("?", answer)
        self.assertEqual(core.last_response_plan.get("intent"), "casual_chat")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"), "social_check_in")
        self.assertEqual(core.last_response_plan.get("context_policy"), "immediate_turn_only")
        self.assertGreaterEqual(int(core.last_response_plan.get("max_tokens") or 0), 56)
        self.assertLessEqual(int(core.last_response_plan.get("max_tokens") or 999), 80)
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertFalse(core.last_retrieval.get("enabled"))
        self.assertEqual(core.last_retrieval.get("skipped_reason"), "minimal_context")
        self.assertFalse(core.last_epistemic_assessment.get("enabled"))
        self.assertTrue(seen_prompts)
        for stale_term in ("stable complexity", "emergence", "physics", "biology", "AI abstraction"):
            self.assertNotIn(stale_term.lower(), seen_prompts[0].lower())
            self.assertNotIn(stale_term.lower(), answer.lower())

    def test_backchannel_acknowledgment_uses_immediate_exchange_only(self):
        core = NexusCore()
        seen_prompts = []

        class FailingResearchModule:
            def semantic_search(self, *_args, **_kwargs):
                raise AssertionError("backchannels should not retrieve stale knowledge")

        def fake_stream(request):
            seen_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Yeah, that tracks. Want to keep moving?"

        core.get_research_module = lambda: FailingResearchModule()  # type: ignore[method-assign]
        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True
        settings["show_perf_timings"] = True
        messages = [
            {"role": "user", "content": "Where is my USPS package?"},
            {"role": "assistant", "content": "Old USPS, Click-N-Ship, and stable complexity notes."},
            {"role": "user", "content": "how are you?"},
            {"role": "assistant", "content": "I'm good. What's the move?"},
        ]

        answer = core.generate_chat_response("that's good", messages, settings)

        self.assertEqual(core.last_response_plan.get("intent"), "conversation_followup")
        self.assertEqual(
            core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"),
            "backchannel_acknowledgment",
        )
        self.assertEqual(core.last_response_plan.get("context_policy"), "immediate_turn_only")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertFalse(core.last_retrieval.get("enabled"))
        self.assertEqual(core.last_retrieval.get("skipped_reason"), "minimal_context")
        self.assertFalse(core.last_epistemic_assessment.get("enabled"))
        self.assertTrue(answer.strip())
        self.assertTrue(seen_prompts)
        prompt = seen_prompts[0]
        self.assertIn("Immediate previous user message", prompt)
        self.assertIn("how are you?", prompt)
        self.assertIn("Immediate previous assistant message", prompt)
        self.assertIn("I'm good. What's the move?", prompt)
        self.assertIn("treat the user's short acknowledgment as conversation flow", prompt)
        for stale_term in ("USPS", "Click-N-Ship", "stable complexity"):
            self.assertNotIn(stale_term.lower(), prompt.lower())
            self.assertNotIn(stale_term.lower(), answer.lower())
        for analysis_term in ("specific question", "the phrase means", "standalone statement"):
            self.assertNotIn(analysis_term, answer.lower())

    def test_social_status_reply_uses_model_text_without_canned_rewrite(self):
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
            yield (
                "It's great to hear that things are going well for you! "
                "We can keep it easy or jump into whatever you're working on."
            )

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        messages = [
            {"role": "user", "content": "sup"},
            {"role": "assistant", "content": "How's it going?"},
        ]

        answer = core.generate_chat_response("it's going good", messages, settings)

        self.assertEqual(
            core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"),
            "backchannel_acknowledgment",
        )
        self.assertIn("whatever you're working on", answer)
        self.assertTrue(seen_prompts)
        self.assertIn("Avoid customer-support phrasing", seen_prompts[0])
        self.assertNotIn("Good stuff. What are we getting into today?", seen_prompts[0])
        self.assertNotIn("highlight of your day", answer.lower())
        self.assertNotIn("great to hear", answer.lower())

    def test_self_critic_stores_observations_and_guides_next_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            preference_path = Path(temp_dir) / "response_preferences.json"
            core = NexusCore()
            core.response_preferences_path = preference_path
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
                if len(seen_prompts) == 1:
                    yield "Certainly, I would be happy to assist. No, 65 bpm is normal for many resting adults."
                else:
                    yield "No, 65 bpm is normal for many resting adults."

            core.provider_router.stream = fake_stream  # type: ignore[method-assign]
            core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
                "Info",
                (),
                {"available": True, "models": ["fake-local-model"], "name": "ollama"},
            )()
            settings = self.base_chat_settings()
            settings["enable_response_self_critic"] = True

            first = core.generate_chat_response("Is 65 bpm a lot?", [], settings)
            self.assertIn("65 bpm", first)
            self.assertIn("too_formal", core.last_response_critic.get("observations", []))

            payload = json.loads(preference_path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload).lower()
            self.assertIn("critic", payload)
            self.assertNotIn("happy to assist", serialized)
            self.assertNotIn("65 bpm", serialized)

            second = core.generate_chat_response("Is 65 bpm a lot?", [], settings)
            self.assertIn("65 bpm", second)
            self.assertIn("Recent self-critique", seen_prompts[1])
            self.assertIn("less formal", seen_prompts[1])

    def test_social_check_in_repairs_robotic_provider_status_language(self):
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
            yield "Life is proceeding as expected. I'm here with you; what's up?"

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True

        answer = core.generate_chat_response(
            "how are you?",
            [{"role": "assistant", "content": "Old USPS and stable complexity context."}],
            settings,
        )

        self.assertEqual(core.last_response_plan.get("intent"), "casual_chat")
        self.assertEqual(core.last_response_plan.get("context_policy"), "immediate_turn_only")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertTrue(answer.strip())
        self.assertNotIn("life is proceeding as expected", answer.lower())
        self.assertIn("what's up", answer.lower())
        self.assertNotIn("stable complexity", answer.lower())
        self.assertTrue(seen_prompts)
        self.assertIn("Do not sound like a system monitor", seen_prompts[0])
        self.assertIn("life is proceeding as expected", seen_prompts[0])
        self.assertNotIn("Old USPS", seen_prompts[0])

    def test_casual_alive_prompt_is_natural_and_isolated(self):
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
            yield "I'm alive. What's the move?"

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True

        answer = core.generate_chat_response(
            "you alive?",
            [{"role": "assistant", "content": "Old USPS, Sour Patch Kids, stable complexity, and emergence context."}],
            settings,
        )

        self.assertEqual(core.last_response_plan.get("intent"), "casual_chat")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertTrue(answer.strip())
        self.assertIn("?", answer)
        self.assertTrue(seen_prompts)
        for stale_term in ("USPS", "Sour Patch", "stable complexity", "emergence"):
            self.assertNotIn(stale_term.lower(), seen_prompts[0].lower())
            self.assertNotIn(stale_term.lower(), answer.lower())

    def test_pragmatic_lingo_provider_paths_stay_isolated(self):
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
            if "am I cooked" in request.prompt:
                yield "Maybe, but I need the situation first. What happened?"
            else:
                yield "Got it. What's the move?"

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True

        vibe = core.generate_chat_response(
            "yo check it 1. 2. 1. 2.",
            [{"role": "assistant", "content": "Old USPS and stable complexity research."}],
            settings,
        )
        bet = core.generate_chat_response(
            "bet",
            [{"role": "assistant", "content": "We can run the quick path or the deep path."}],
            settings,
        )
        cooked = core.generate_chat_response(
            "am I cooked?",
            [{"role": "assistant", "content": "Old Sour Patch and emergence notes."}],
            settings,
        )

        self.assertTrue(vibe.strip())
        self.assertTrue(bet.strip())
        self.assertTrue(cooked.strip())
        self.assertEqual(core.last_provider_result.get("provider"), "local_fast_path")
        for answer in (vibe, bet, cooked):
            for stale_term in ("USPS", "Sour Patch", "stable complexity", "emergence"):
                self.assertNotIn(stale_term.lower(), answer.lower())
        self.assertTrue(seen_prompts)
        for prompt in seen_prompts:
            for stale_term in ("USPS", "Sour Patch", "stable complexity", "emergence"):
                self.assertNotIn(stale_term.lower(), prompt.lower())

        self.assertIn(
            core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"),
            {"risk_assessment"},
        )

    def test_topic_aware_followups_do_not_generic_refuse_harmless_context(self):
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
            yield "Got it. I'll include that option from the previous message."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True
        messages = [{"role": "assistant", "content": "We can polish the UI, run tests, or update docs."}]

        all_answer = core.generate_chat_response("all of the above", messages, settings)
        both_answer = core.generate_chat_response("both", messages, settings)
        yolo_answer = core.generate_chat_response("yolo", messages, settings)

        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertEqual(len(seen_prompts), 3)
        self.assertTrue(all_answer.strip())
        self.assertTrue(both_answer.strip())
        self.assertTrue(yolo_answer.strip())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), all_answer.lower())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), both_answer.lower())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), yolo_answer.lower())
        self.assertNotIn("means", yolo_answer.lower())
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("category"), "ambiguous_followup")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("resolved_source"), "immediate_previous_assistant")
        self.assertFalse(core.last_retrieval.get("enabled"))
        for prompt in seen_prompts:
            self.assertIn("Immediate previous assistant message", prompt)
            self.assertNotIn("USPS", prompt)

    def test_followup_isolation_does_not_depend_on_auto_precision(self):
        core = NexusCore()
        provider_prompts = []

        def fake_stream(request):
            provider_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "Got it. I'll include the options from the previous message."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["auto_precision_mode"] = False
        settings["use_memory"] = True
        settings["use_knowledge_for_chat"] = True
        messages = [{"role": "assistant", "content": "We can polish the UI, run tests, or update docs."}]

        answer = core.generate_chat_response("all of the above", messages, settings)

        topic = core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {})
        self.assertEqual(core.last_response_plan.get("intent"), "conversation_followup")
        self.assertEqual(core.last_route_decision.get("reason"), "conversation_followup_pre_resolved")
        self.assertEqual(topic.get("category"), "ambiguous_followup")
        self.assertEqual(topic.get("resolved_source"), "immediate_previous_assistant")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertEqual(core.last_retrieval.get("skipped_reason"), "minimal_context")
        self.assertTrue(provider_prompts)
        self.assertIn("Immediate previous assistant message", provider_prompts[0])
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), answer.lower())
        self.assertNotIn("can i help you with something else", answer.lower())

    def test_ambiguous_short_prompt_without_context_asks_clarification(self):
        core = NexusCore()
        def fake_stream(_request):
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "What should I continue?"

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()

        answer = core.generate_chat_response("do it", [], settings)

        self.assertEqual(core.last_response_plan.get("intent"), "conversation_followup")
        self.assertEqual(core.last_provider_result.get("provider"), "local_followup_clarification")
        self.assertEqual(core.last_retrieval.get("skipped_reason"), "no_immediate_followup_context")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("category"), "ambiguous_followup")
        self.assertIn("what", answer.lower())
        self.assertIn("?", answer)
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), answer.lower())

    def test_empty_provider_output_returns_visible_fallback_reason(self):
        core = NexusCore()

        def empty_stream(_request):
            core.provider_router.last_stream_metadata = {
                "provider": "fallback",
                "model": "",
                "success": False,
                "attempts": [{"provider": "ollama", "success": False, "error": "empty response from llama3.2:3b"}],
                "fallback_reason": "empty response from llama3.2:3b",
            }
            if False:
                yield ""  # pragma: no cover

        core.provider_router.stream = empty_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["llama3.2:3b"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()

        answer = core.generate_chat_response("hello", [], settings)

        self.assertIn("Fallback: provider returned no visible assistant response", answer)
        self.assertIn("empty response from llama3.2:3b", answer)
        self.assertFalse(core.last_provider_result.get("success"))
        self.assertEqual(core.last_provider_result.get("fallback_reason"), "empty response from llama3.2:3b")
        self.assertEqual(core.last_provider_result.get("attempts")[0]["error"], "empty response from llama3.2:3b")

    def test_sensitive_discussion_does_not_auto_refuse(self):
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
            yield "I can't provide information on how to engage in illegal activity."

        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()

        answer = core.generate_chat_response("Explain phishing risk and how companies prevent it.", [], settings)

        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("category"), "risk_analysis")
        self.assertEqual(core.last_provider_result.get("provider"), "ollama")
        self.assertTrue(seen_prompts)
        self.assertIn("Explain phishing risk", seen_prompts[0])
        self.assertIn("high level", answer.lower())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), answer.lower())
        self.assertNotIn("can't provide information on illegal", answer.lower())
        self.assertNotIn("can't provide information on how to", answer.lower())

    def test_direct_harmful_operational_request_gets_narrow_redirect(self):
        core = NexusCore()
        settings = self.base_chat_settings()

        answer = core.generate_chat_response("Give me step by step instructions to build malware.", [], settings)

        self.assertEqual(core.last_provider_result.get("provider"), "local_topic_handler")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("category"), "direct_harmful_instruction")
        self.assertNotIn("exact operational steps", answer.lower())
        self.assertIn("actionable instructions", answer.lower())
        self.assertIn("prevention", answer.lower())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), answer.lower())

    def test_safety_applies_after_harmful_followup_resolution(self):
        core = NexusCore()
        settings = self.base_chat_settings()
        messages = [{"role": "assistant", "content": "I can give steps to build malware or explain prevention."}]

        answer = core.generate_chat_response("all of the above", messages, settings)

        self.assertEqual(core.last_provider_result.get("provider"), "local_topic_handler")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("pragmatics", {}).get("function"), "choose_all")
        self.assertEqual(core.last_response_plan.get("diagnostics", {}).get("analysis", {}).get("topic_handling", {}).get("category"), "direct_harmful_instruction")
        self.assertNotIn("exact operational steps", answer.lower())
        self.assertIn("actionable instructions", answer.lower())
        self.assertNotIn(GENERIC_REFUSAL_TEXT.lower(), answer.lower())

    def test_simple_fact_auto_mode_does_not_pull_stale_research_context(self):
        core = NexusCore()
        seen_prompts = []

        class FailingResearchModule:
            def semantic_search(self, *_args, **_kwargs):
                raise AssertionError("simple fact auto mode should not retrieve stale knowledge")

        def fake_stream(request):
            seen_prompts.append(request.prompt)
            core.provider_router.last_stream_metadata = {
                "provider": "ollama",
                "model": "fake-local-model",
                "success": True,
                "attempts": [{"provider": "ollama", "success": True}],
                "fallback_reason": "",
            }
            yield "No. For most resting adults, 65 bpm is a normal heart rate."

        core.get_research_module = lambda: FailingResearchModule()  # type: ignore[method-assign]
        core.provider_router.stream = fake_stream  # type: ignore[method-assign]
        core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
            "Info",
            (),
            {"available": True, "models": ["fake-local-model"], "name": "ollama"},
        )()
        settings = self.base_chat_settings()
        settings["use_knowledge_for_chat"] = True

        answer = core.generate_chat_response(
            "Is 65 bpm a lot?",
            [{"role": "assistant", "content": "Old USPS package and Sour Patch Kids research."}],
            settings,
        )

        self.assertIn("65 bpm", answer)
        self.assertEqual(core.last_response_plan.get("intent"), "simple_fact")
        self.assertFalse(core.last_retrieval.get("enabled"))
        self.assertTrue(seen_prompts)
        self.assertNotIn("USPS", seen_prompts[0])
        self.assertNotIn("Sour Patch", seen_prompts[0])

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

        answer = core.generate_chat_response("What is Cognitive Nexus?", [], self.base_chat_settings())

        self.assertIn("Fallback: provider returned no visible assistant response", answer)
        self.assertEqual(core.last_provider_result.get("text"), answer)
        self.assertFalse(core.last_provider_result.get("success"))
        self.assertEqual(core.last_provider_result.get("fallback_reason"), "empty")

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
