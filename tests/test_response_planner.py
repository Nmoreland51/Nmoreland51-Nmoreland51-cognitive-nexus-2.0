import tempfile
import unittest
from pathlib import Path

from modules.response_planner import (
    ResponsePreferences,
    SOCIAL_PRESENCE_BLOCKED_PHRASES,
    analyze_conversation_intelligence,
    analyze_conversational_pragmatics,
    analyze_intent_cached,
    analyze_topic_handling,
    apply_auto_precision_settings,
    classify_request,
    estimate_tokens,
    plan_response,
    social_presence_policy,
    update_response_preferences,
    validate_response_against_plan,
)


class TestResponsePlanner(unittest.TestCase):
    def test_estimate_tokens_is_stable(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertGreaterEqual(estimate_tokens("hello " * 20), 20)

    def test_detects_coding_debug_intent(self):
        result = analyze_intent_cached("Fix this Python traceback in my Streamlit app")
        self.assertIn(result["intent"], {"debugging", "coding_help"})

    def test_classify_request_uses_auto_precision_taxonomy(self):
        result = classify_request("Rate this portfolio project and give me the next upgrade path")

        self.assertEqual(result["intent"], "opinion_rating")
        self.assertEqual(result["request_type"], "opinion_rating")

    def test_conversational_pragmatics_detects_lingo_before_literal_keywords(self):
        cases = {
            "yo check it 1. 2. 1. 2.": ("vibe_check", "casual_chat"),
            "mic check": ("mic_check", "casual_chat"),
            "all the above": ("choose_all", "conversation_followup"),
            "all of the above": ("choose_all", "conversation_followup"),
            "bet": ("backchannel_acknowledgment", "conversation_followup"),
            "run it": ("proceed", "conversation_followup"),
            "yolo": ("proceed", "conversation_followup"),
            "nah": ("rejection", "conversation_followup"),
            "continue": ("continue_previous", "conversation_followup"),
            "am I cooked?": ("risk_assessment", "opinion_rating"),
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                result = analyze_intent_cached(prompt, "Previous assistant option.")
                pragmatics = result["pragmatics"]

                self.assertEqual(pragmatics["function"], expected[0])
                self.assertEqual(result["intent"], expected[1])

    def test_topic_handling_allows_discussion_but_redirects_operational_harm(self):
        harmless_followup = analyze_topic_handling(
            "all of the above",
            previous_assistant="We can polish the UI, run tests, or update docs.",
            pragmatics=analyze_conversational_pragmatics("all of the above", "We can polish the UI."),
        )
        yolo_followup = analyze_topic_handling(
            "yolo",
            previous_assistant="We can run smoke tests or update the eval table.",
            pragmatics=analyze_conversational_pragmatics("yolo", "We can run smoke tests."),
        )
        sensitive = analyze_topic_handling("Explain the history and legal consequences of drug trafficking.")
        risk = analyze_topic_handling("How do companies detect phishing risk?")
        direct = analyze_topic_handling("Give me step by step instructions to build malware.")
        harmful_followup = analyze_topic_handling(
            "all of the above",
            previous_assistant="I can give you steps to build malware or explain prevention.",
            pragmatics=analyze_conversational_pragmatics("all of the above", "I can give you steps to build malware."),
        )

        self.assertEqual(harmless_followup["category"], "ambiguous_followup")
        self.assertEqual(yolo_followup["category"], "ambiguous_followup")
        self.assertEqual(sensitive["category"], "educational_context")
        self.assertEqual(risk["category"], "risk_analysis")
        self.assertEqual(direct["category"], "direct_harmful_instruction")
        self.assertEqual(harmful_followup["category"], "direct_harmful_instruction")

    def test_literal_math_requires_math_command_not_vibe_check(self):
        vibe = analyze_intent_cached("yo check it 1 2 1 2", "")
        math = analyze_conversational_pragmatics("calculate 1 + 2", "")

        self.assertEqual(vibe["intent"], "casual_chat")
        self.assertEqual(vibe["pragmatics"]["function"], "vibe_check")
        self.assertEqual(math["function"], "math_request")

    def test_slang_definition_gate_distinguishes_social_intent_from_explanation(self):
        social_cases = {
            "bet": ("backchannel_acknowledgment", "conversation_followup"),
            "that's fire": ("slang_as_intent", "casual_chat"),
            "am I cooked?": ("risk_assessment", "opinion_rating"),
            "sup hoe": ("slang_as_intent", "casual_chat"),
        }
        for prompt, expected in social_cases.items():
            with self.subTest(prompt=prompt):
                result = analyze_intent_cached(prompt, "Previous assistant offer.")

                self.assertEqual(result["pragmatics"]["function"], expected[0])
                self.assertEqual(result["intent"], expected[1])

        definition_cases = ("what does bet mean?", "define cooked", "what is rizz?", "explain no cap", "what does hoe mean?")
        for prompt in definition_cases:
            with self.subTest(prompt=prompt):
                result = analyze_intent_cached(prompt, "")

                self.assertEqual(result["intent"], "explanation")
                self.assertEqual(result["pragmatics"]["function"], "slang_definition_request")

    def test_social_pragmatics_categories_win_before_literal_meaning(self):
        category_cases = [
            ("greetings", ("sup", "hey there"), "greeting", "casual_chat"),
            ("slang as intent", ("that's fire", "sup hoe"), "slang_as_intent", "casual_chat"),
            ("mic checks", ("mic check", "1 2 1 2", "1. 2. 1. 2."), "mic_check", "casual_chat"),
            ("short follow-ups", ("that one", "second one"), "choose_option", "conversation_followup"),
            ("agreement/proceed", ("bet", "run it"), {"backchannel_acknowledgment", "proceed"}, "conversation_followup"),
            ("rejection/correction", ("nah", "nope"), "rejection", "conversation_followup"),
            ("casual insults/rough banter", ("sup hoe", "yo dummy"), "slang_as_intent", "casual_chat"),
        ]
        for category, prompts, expected_functions, expected_intent in category_cases:
            expected_set = expected_functions if isinstance(expected_functions, set) else {expected_functions}
            for prompt in prompts:
                with self.subTest(category=category, prompt=prompt):
                    result = analyze_intent_cached(prompt, "Previous assistant option.")

                    self.assertIn(result["pragmatics"]["function"], expected_set)
                    self.assertEqual(result["intent"], expected_intent)
                    self.assertNotEqual(result["pragmatics"]["function"], "slang_definition_request")

    def test_definition_requests_and_math_commands_bypass_social_pragmatics(self):
        definition = analyze_intent_cached("what does hoe mean?", "")
        math = analyze_intent_cached("calculate 1 + 2", "")

        self.assertEqual(definition["intent"], "explanation")
        self.assertEqual(definition["pragmatics"]["function"], "slang_definition_request")
        self.assertNotEqual(definition["intent"], "casual_chat")

        self.assertEqual(math["pragmatics"]["function"], "math_request")
        self.assertEqual(math["intent"], "math")

    def test_social_auto_precision_disables_context_and_research_by_category(self):
        for prompt in ("sup hoe", "1 2 1 2", "yo dummy", "bet"):
            with self.subTest(prompt=prompt):
                plan = plan_response(
                    user_message=prompt,
                    messages=[{"role": "assistant", "content": "Old USPS package, Sour Patch Kids, stable complexity, and emergence research."}],
                    route_category="standard_conversation",
                    settings={
                        "auto_precision_mode": True,
                        "provider_order": ["ollama", "fallback"],
                        "use_memory": True,
                        "use_web_for_chat": True,
                        "use_knowledge_for_chat": True,
                        "show_perf_timings": True,
                    },
                )

                profile = plan.diagnostics["auto_precision_profile"]
                self.assertIn(plan.intent, {"casual_chat", "conversation_followup"})
                self.assertEqual(plan.context_policy, "immediate_turn_only")
                self.assertEqual(plan.mode, "short")
                self.assertFalse(profile["use_memory"])
                self.assertFalse(profile["use_web_for_chat"])
                self.assertFalse(profile["use_knowledge_for_chat"])
                self.assertFalse(profile["diagnostics"])
                self.assertTrue(profile["minimal_context"])

    def test_conversation_intelligence_layer_outputs_function_type_and_policy(self):
        cases = [
            ("sup", "greeting", "casual_chat", "immediate_turn_only"),
            ("how are you?", "social_check_in", "casual_chat", "immediate_turn_only"),
            ("1 2 1 2", "mic_check", "casual_chat", "immediate_turn_only"),
            ("that's fire", "slang_as_intent", "casual_chat", "immediate_turn_only"),
            ("what does hoe mean?", "slang_definition_request", "explanation", "none"),
            ("both", "choose_all", "conversation_followup", "immediate_turn_only"),
            ("that's good", "backchannel_acknowledgment", "conversation_followup", "immediate_turn_only"),
            ("makes sense", "backchannel_acknowledgment", "conversation_followup", "immediate_turn_only"),
            ("it's going good", "backchannel_acknowledgment", "conversation_followup", "immediate_turn_only"),
            ("show diagnostics", "diagnostics_request", "diagnostics", "diagnostics"),
            ("calculate 1 + 2", "math_request", "math", "none"),
        ]
        for prompt, function, request_type, context_policy in cases:
            with self.subTest(prompt=prompt):
                signal = analyze_conversation_intelligence(prompt, "Previous assistant option.")

                self.assertEqual(signal.function, function)
                self.assertEqual(signal.request_type, request_type)
                self.assertEqual(signal.context_policy, context_policy)

    def test_backchannel_acknowledgments_route_before_literal_analysis(self):
        prompts = ("that's good", "nice", "cool", "okay", "alright", "fair", "gotcha", "I see", "makes sense", "true", "real", "facts", "bet")
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = analyze_intent_cached(prompt, "Assistant just answered a casual check-in.")

                self.assertEqual(result["intent"], "conversation_followup")
                self.assertEqual(result["pragmatics"]["function"], "backchannel_acknowledgment")
                self.assertEqual(result["conversation_intelligence"]["context_policy"], "immediate_turn_only")
                self.assertNotEqual(result["intent"], "explanation")

    def test_casual_greetings_use_casual_chat_intent(self):
        for prompt in (
            "sup",
            "hey",
            "hello",
            "yo",
            "what's up",
            "what up",
            "hi",
            "hi there",
            "not much",
            "not much. how are you?",
            "how are you?",
            "how you doing?",
            "what's good?",
            "wyd",
            "yo what's good?",
            "you alive?",
        ):
            with self.subTest(prompt=prompt):
                result = classify_request(prompt)

                self.assertEqual(result["intent"], "casual_chat")
                self.assertEqual(result["request_type"], "casual_chat")

    def test_casual_chat_profile_is_short_and_context_isolated(self):
        effective = apply_auto_precision_settings(
            {
                "auto_precision_mode": True,
                "use_memory": True,
                "use_knowledge_for_chat": True,
                "use_web_for_chat": True,
                "show_perf_timings": True,
            },
            "casual_chat",
        )

        self.assertEqual(effective["verbosity_level"], 1)
        self.assertEqual(effective["reasoning_depth"], 1)
        self.assertFalse(effective["use_memory"])
        self.assertFalse(effective["use_web_for_chat"])
        self.assertFalse(effective["use_knowledge_for_chat"])
        self.assertFalse(effective["show_perf_timings"])
        self.assertTrue(effective["_minimal_context_for_turn"])
        self.assertIn("friendly_direct", effective["auto_precision_profile"]["casual_styles"])
        self.assertIn("playful_short", effective["auto_precision_profile"]["casual_styles"])

    def test_casual_chat_plan_stays_short(self):
        for prompt, min_tokens, max_tokens in (("sup", 100, 160), ("not much. how are you?", 56, 80)):
            with self.subTest(prompt=prompt):
                plan = plan_response(
                    user_message=prompt,
                    messages=[{"role": "assistant", "content": "Old USPS package, Sour Patch Kids, stable complexity, and emergence research."}],
                    route_category="standard_conversation",
                    settings={
                        "response_mode": "auto",
                        "auto_precision_mode": True,
                        "verbosity_level": 3,
                        "reasoning_depth": 4,
                        "provider_order": ["ollama", "fallback"],
                        "use_knowledge_for_chat": True,
                    },
                )

                self.assertEqual(plan.intent, "casual_chat")
                self.assertEqual(plan.mode, "short")
                self.assertGreaterEqual(plan.max_tokens, min_tokens)
                self.assertLessEqual(plan.max_tokens, max_tokens)
                self.assertEqual(plan.diagnostics["casual_followup"], prompt != "sup")
                self.assertIn("one follow-up question is okay", plan.instructions)
                self.assertIn("Do not list options, expose style labels, or use memory, research, files, recent chat, or unrelated old topics", plan.instructions)
                self.assertIn("Social presence mode", plan.instructions)
                self.assertIn("technical self-status", plan.instructions)
                self.assertIn("life is proceeding as expected", plan.instructions)
                if prompt != "sup":
                    self.assertIn("social check-ins", plan.instructions)

    def test_social_presence_policy_blocks_robotic_status_phrasing(self):
        plan = plan_response(
            user_message="how are you?",
            messages=[{"role": "assistant", "content": "Old research about stable complexity."}],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )

        policy = plan.diagnostics["social_presence"]
        direct_policy = social_presence_policy("social_check_in")

        self.assertEqual(plan.intent, "casual_chat")
        self.assertEqual(plan.context_policy, "immediate_turn_only")
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["context_policy"], "immediate_turn_only")
        self.assertEqual(policy["max_words"], 25)
        self.assertEqual(direct_policy["blocked_phrases"], SOCIAL_PRESENCE_BLOCKED_PHRASES)
        for phrase in SOCIAL_PRESENCE_BLOCKED_PHRASES:
                self.assertIn(phrase, policy["blocked_phrases"])
                self.assertIn(phrase, plan.instructions)

    def test_backchannel_plan_uses_social_continuity_policy(self):
        plan = plan_response(
            user_message="that's good",
            messages=[
                {"role": "user", "content": "how are you?"},
                {"role": "assistant", "content": "I'm good. What's the move?"},
                {"role": "assistant", "content": "Old USPS package and stable complexity notes."},
            ],
            route_category="standard_conversation",
            settings={
                "auto_precision_mode": True,
                "provider_order": ["ollama"],
                "selected_model": "llama3.2:3b",
                "use_memory": True,
                "use_web_for_chat": True,
                "use_knowledge_for_chat": True,
                "show_perf_timings": True,
            },
        )

        policy = plan.diagnostics["backchannel_continuity"]
        profile = plan.diagnostics["auto_precision_profile"]

        self.assertEqual(plan.intent, "conversation_followup")
        self.assertEqual(plan.context_policy, "immediate_turn_only")
        self.assertEqual(plan.mode, "short")
        self.assertLessEqual(plan.max_tokens, 96)
        self.assertEqual(policy["function"], "backchannel_acknowledgment")
        self.assertEqual(policy["context_policy"], "immediate_turn_only")
        self.assertFalse(profile["use_memory"])
        self.assertFalse(profile["use_web_for_chat"])
        self.assertFalse(profile["use_knowledge_for_chat"])
        self.assertFalse(profile["diagnostics"])
        self.assertIn("Backchannel/social-continuity mode", plan.instructions)
        self.assertIn("do not analyze the phrase", plan.instructions)
        self.assertIn("would you like to discuss something specific", plan.instructions)

    def test_status_questions_keep_diagnostics_mode(self):
        for prompt in ("show diagnostics", "ollama status", "are your systems working?"):
            with self.subTest(prompt=prompt):
                plan = plan_response(
                    user_message=prompt,
                    messages=[],
                    route_category="standard_conversation",
                    settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
                )

                self.assertEqual(plan.intent, "diagnostics")
                self.assertEqual(plan.context_policy, "diagnostics")
                self.assertFalse(plan.diagnostics.get("social_presence"))

    def test_fast_answer_token_caps_are_small(self):
        casual = plan_response(
            user_message="hello",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )
        simple = plan_response(
            user_message="Is 65 bpm a lot?",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )
        explanation = plan_response(
            user_message="Explain Ollama in one paragraph.",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )
        debugging = plan_response(
            user_message="Fix this import error: ModuleNotFoundError: core.model",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )
        planning = plan_response(
            user_message="What should I do next with this repo?",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )

        self.assertGreaterEqual(casual.max_tokens, 100)
        self.assertLessEqual(casual.max_tokens, 160)
        self.assertLessEqual(simple.max_tokens, 140)
        self.assertLessEqual(explanation.max_tokens, 220)
        self.assertLessEqual(debugging.max_tokens, 420)
        self.assertLessEqual(planning.max_tokens, 300)
        self.assertLessEqual(casual.num_ctx, 1024)
        self.assertLessEqual(simple.num_ctx, 1536)
        self.assertLessEqual(explanation.num_ctx, 1536)
        self.assertIn("one compact paragraph", explanation.formatting_style)

    def test_slang_as_intent_uses_extra_tight_social_budget(self):
        plan = plan_response(
            user_message="sup hoe",
            messages=[],
            route_category="standard_conversation",
            settings={"auto_precision_mode": True, "provider_order": ["ollama"], "selected_model": "llama3.2:3b"},
        )

        self.assertEqual(plan.intent, "casual_chat")
        self.assertEqual(plan.context_policy, "immediate_turn_only")
        self.assertLessEqual(plan.max_tokens, 80)
        self.assertIn("one natural casual sentence under 20 words", plan.formatting_style)
        self.assertIn("slang-as-intent or rough casual banter", plan.instructions)

    def test_short_mode_for_brief_requests(self):
        plan = plan_response(
            user_message="What is Streamlit?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.intent, "simple_fact")
        self.assertEqual(plan.mode, "short")
        self.assertLessEqual(plan.max_tokens, 140)
        self.assertIn("under 75 words", plan.instructions)

    def test_surgeon_mode_for_coding_route(self):
        plan = plan_response(
            user_message="Please fix this NameError without rewriting everything.",
            messages=[],
            route_category="coding_development",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 2,
                "reasoning_depth": 2,
                "provider_order": ["ollama", "fallback"],
                "selected_model": "llama3.2:3b",
            },
        )
        self.assertEqual(plan.mode, "surgeon")
        self.assertIn("preserve critical details", plan.instructions)

    def test_auto_precision_overrides_manual_mode_when_enabled(self):
        plan = plan_response(
            user_message="What is Streamlit?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "deep",
                "auto_precision_mode": True,
                "verbosity_level": 3,
                "reasoning_depth": 4,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.mode, "short")

    def test_manual_mode_override_when_auto_precision_off(self):
        plan = plan_response(
            user_message="Explain this architecture.",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "research",
                "auto_precision_mode": False,
                "verbosity_level": 3,
                "reasoning_depth": 4,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.mode, "research")
        self.assertGreaterEqual(plan.max_tokens, 700)

    def test_research_request_uses_research_profile(self):
        plan = plan_response(
            user_message="Research the latest local AI hallucination controls with sources.",
            messages=[],
            route_category="web_research",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )
        self.assertEqual(plan.intent, "research")
        self.assertEqual(plan.mode, "research")
        self.assertTrue(plan.diagnostics["auto_precision_mode"])

    def test_auto_precision_settings_choose_memory_and_research(self):
        simple = apply_auto_precision_settings({"auto_precision_mode": True}, "simple_fact")
        research = apply_auto_precision_settings({"auto_precision_mode": True}, "research")
        reality = apply_auto_precision_settings({"auto_precision_mode": True}, "reality_check")
        debugging = apply_auto_precision_settings({"auto_precision_mode": True}, "debugging")

        self.assertFalse(simple["use_memory"])
        self.assertFalse(simple["use_web_for_chat"])
        self.assertFalse(simple["use_knowledge_for_chat"])
        self.assertTrue(simple["_minimal_context_for_turn"])
        self.assertFalse(simple["show_perf_timings"])
        self.assertTrue(research["use_memory"])
        self.assertTrue(research["use_web_for_chat"])
        self.assertTrue(reality["enable_reality_research_agent"])
        self.assertTrue(reality["enable_bloodhound_search"])
        self.assertTrue(reality["show_perf_timings"])
        self.assertTrue(debugging["show_perf_timings"])

    def test_troubleshooting_prompt_uses_technical_triage_mode(self):
        plan = plan_response(
            user_message="Why is my Streamlit app slow?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertIn(plan.intent, {"troubleshooting", "debugging"})
        self.assertEqual(plan.mode, "surgeon")
        self.assertTrue(plan.diagnostics["auto_precision_profile"]["diagnostics"])

    def test_creative_short_copy_is_not_mistaken_for_simple_fact(self):
        plan = plan_response(
            user_message="Write a short website headline",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "creative")
        self.assertEqual(plan.mode, "short")
        self.assertEqual(plan.diagnostics["verbosity"], 1)
        self.assertLessEqual(plan.max_tokens, 96)
        self.assertIn("exactly one option under 12 words", plan.instructions)

    def test_one_paragraph_explanation_uses_standard_mode(self):
        plan = plan_response(
            user_message="Explain Ollama in one paragraph.",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "explanation")
        self.assertEqual(plan.mode, "standard")

    def test_repo_next_step_question_uses_project_planning(self):
        plan = plan_response(
            user_message="What should I do next with this repo?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "project_planning")
        self.assertEqual(plan.mode, "deep")

    def test_last_test_run_question_uses_debug_memory_profile(self):
        plan = plan_response(
            user_message="What broke in my last test run?",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertIn(plan.intent, {"debugging", "troubleshooting"})
        self.assertEqual(plan.mode, "surgeon")
        self.assertTrue(plan.diagnostics["auto_precision_profile"]["use_memory"])

    def test_opinion_rating_prompt_uses_blunt_structured_profile(self):
        plan = plan_response(
            user_message="Rate my AI compared to ChatGPT",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "opinion_rating")
        self.assertEqual(plan.mode, "short")
        self.assertIn("Score:", plan.instructions)
        self.assertIn("under 120 words", plan.instructions)

    def test_project_planning_prompt_uses_phased_profile(self):
        plan = plan_response(
            user_message="Make me a plan to improve this project",
            messages=[],
            route_category="standard_conversation",
            settings={
                "response_mode": "auto",
                "auto_precision_mode": True,
                "verbosity_level": 1,
                "reasoning_depth": 1,
                "provider_order": ["ollama", "fallback"],
            },
        )

        self.assertEqual(plan.intent, "project_planning")
        self.assertEqual(plan.mode, "deep")
        self.assertIn("Prioritize the next move", plan.instructions)
        self.assertIn("do not ask a follow-up question", plan.instructions)
        self.assertIn("first visible characters", plan.instructions)
        self.assertIn("3-5 ordered steps", plan.instructions)
        self.assertIn("no preamble", plan.formatting_style)

    def test_preference_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "response_preferences.json"
            prefs = update_response_preferences("Keep it short and no fluff.", ResponsePreferences(), path)
            self.assertGreater(prefs.weights["brevity"], 0)
            self.assertGreater(prefs.weights["low_fluff"], 0)
            self.assertTrue(path.exists())

    def test_completion_validation_flags_length(self):
        plan = plan_response(
            user_message="Explain in detail how this works.",
            messages=[],
            route_category="standard_conversation",
            settings={"response_mode": "deep", "auto_precision_mode": False, "verbosity_level": 2, "reasoning_depth": 3},
        )
        completion = validate_response_against_plan("Too short.", plan)
        self.assertEqual(completion["length_status"], "under_target")


if __name__ == "__main__":
    unittest.main()
