"""The owner's text reaches the model on every turn, and the length and form of an answer follow the owner's message.

Found with the real model on 2026-11-25 (tools/answer_attribution.py, docs/benchmarks/attribution_dolphin3-8b.json):

  * On a quick turn (most messages) Ollama was sent no system prompt at all. The owner's behaviour text,
    persona and the content rule line never reached a local model, which kept its own built-in line
    ("You are Dolphin, a helpful AI assistant."). The Behaviour panel showed a system prompt that was not sent.
  * The app's own length and format rules overrode what the owner asked: "Reply with only yes or no: is
    Pluto a planet?" came back as a sentence (the model alone answered "No"), and "Be detailed" got
    "Answer under 75 words" and a 140-token limit (58 words, against 392 from the model alone).

These tests use stand-ins for the model and the model server. The measurement is the evidence for the real model.
"""

from __future__ import annotations

import pytest

from modules.behavior_policy import (
    ANSWER_SHAPE_HELP,
    CONTENT_RULE,
    REQUEST_REPLY_TOKENS,
    SHORT_REPLY_TOKENS,
    apply_behavior_changes,
    effective_policy,
    policy_from,
)
from modules.nexus_core import NexusCore
from modules.provider_router import ProviderInfo, ProviderRequest, ProviderRouter
from modules.response_planner import plan_response
from tests.test_context_budget import _Ollama, ollama_router

# Requests in which the owner says how long an answer should be, or in what form.
OWNER_SAYS_HOW = (
    "Reply with only yes or no: is Pluto a planet?",
    "How does caffeine affect sleep? Be detailed.",
    "Give me a detailed 12-week plan for learning Spanish, week by week.",
    "Why did the Western Roman Empire fall? Give me a full essay.",
    "Compare PostgreSQL and SQLite for a small web app. I want a long answer.",
)
# What the per-kind rules said. None of it may appear unless the owner chose "By kind of message".
KIND_RULES = (
    "Answer rules",
    "1-3 short sentences",
    "under 75 words",
    "Maximum output",
    "compact paragraph",
    "Start with '1.'",
    "exactly 3 short concrete steps",
    "Stay under 180 words",
    "smallest safe fix",
    "avoid broad theory",
)


def test_by_default_the_app_adds_no_length_or_format_rule_of_its_own():
    core = NexusCore()
    for message in (*OWNER_SAYS_HOW, "What is cerebral palsy?", "hey", "Explain recursion."):
        plan = plan_response(user_message=message, messages=[], route_category="standard_conversation", settings={"auto_precision_mode": True})
        prompt = core.build_planned_chat_prompt(f"User request:\n{message}\n\nFinal answer:", plan)
        assert plan.diagnostics["answer_shape"] == "request", message
        assert plan.instructions == "", message
        assert plan.max_tokens == REQUEST_REPLY_TOKENS and plan.num_ctx >= 4096, message
        assert not [rule for rule in KIND_RULES if rule in prompt], (message, prompt)
        assert "social_presence" not in plan.diagnostics and "backchannel_continuity" not in plan.diagnostics


def test_a_length_stated_in_the_message_is_passed_on():
    plan = plan_response(user_message="Write a 600-word story about a lighthouse keeper.", messages=[], route_category="standard_conversation", settings={})

    assert "Length: the user asked for" in plan.instructions
    assert plan.max_tokens >= REQUEST_REPLY_TOKENS


def test_the_owners_response_controls_still_count():
    short = plan_response(user_message="Explain recursion.", messages=[], route_category="standard_conversation", settings={"auto_precision_mode": False, "response_mode": "short"})
    deep = plan_response(user_message="Explain recursion.", messages=[], route_category="standard_conversation", settings={"auto_precision_mode": False, "response_mode": "deep"})

    assert short.instructions == "Keep the answer short unless the message asks for more." and short.max_tokens == SHORT_REPLY_TOKENS
    assert deep.instructions == "Give a thorough, complete answer." and deep.max_tokens == REQUEST_REPLY_TOKENS


def test_by_kind_of_message_keeps_the_earlier_rules_for_an_owner_who_wants_them():
    plan = plan_response(user_message="What is cerebral palsy?", messages=[], route_category="standard_conversation", settings={"auto_precision_mode": True, "answer_shape": "kind"})

    assert plan.intent == "simple_fact" and plan.max_tokens <= 160
    assert "Answer in 1-3 short sentences" in NexusCore().build_planned_chat_prompt("Q\n\nFinal answer:", plan)


def test_the_setting_is_the_owners_and_is_validated():
    assert policy_from({}).answer_shape == "request"
    assert policy_from({"answer_shape": "kind"}).answer_shape == "kind"
    assert policy_from({"answer_shape": "something else"}).answer_shape == "request"
    assert apply_behavior_changes({}, {"answer_shape": "kind"})["answer_shape"] == "kind"
    with pytest.raises(ValueError):
        apply_behavior_changes({}, {"answer_shape": "short"})
    application = effective_policy({})["application"]
    assert application["answer_shape"] == ANSWER_SHAPE_HELP["request"]
    assert "system message" in application["system_prompt_sent_as"]


def test_ollama_is_sent_the_system_prompt_as_its_system_message(monkeypatch):
    server = _Ollama(window=8192, prompt_tokens=80)
    router, info = ollama_router(monkeypatch, server)
    owner = "You are the owner's assistant. Talk like a pirate."

    text = "".join(router._stream_ollama(ProviderRequest(prompt="User request:\nhi\n\nFinal answer:", system_prompt=owner, options={"num_ctx": 2048, "num_predict": 64}), info, "m"))
    without = "".join(router._stream_ollama(ProviderRequest(prompt="Summarise this page.", options={"num_ctx": 2048, "num_predict": 64}), info, "m"))

    assert text == without == "Answer."
    assert server.generate_calls[0]["system"] == owner and owner not in server.generate_calls[0]["prompt"]
    # A request without a system prompt (a summary, a check) leaves the field out: nothing is invented.
    assert "system" not in server.generate_calls[1]


def test_a_local_model_without_a_system_field_gets_the_system_prompt_first():
    router = ProviderRouter({"provider_order": ["hf_local"]})
    seen: list[str] = []

    def pipeline(prompt, **_options):
        seen.append(prompt)
        return [{"generated_text": prompt + " Arr."}]

    router._hf_pipeline = pipeline
    info = ProviderInfo(name="hf_local", available=True, message="ok", models=["local"], base_url="")
    answer = router._generate_hf_local(ProviderRequest(prompt="User request:\nhi", system_prompt="Talk like a pirate.", max_tokens=16), info)

    assert seen == ["Talk like a pirate.\n\nUser request:\nhi"] and answer == "Arr."


def _stand_in_core(seen: list) -> NexusCore:
    core = NexusCore()

    def stream(request):
        seen.append(request)
        core.provider_router.last_stream_metadata = {
            "provider": "ollama",
            "model": "fake-local-model",
            "success": True,
            "attempts": [{"provider": "ollama", "success": True}],
            "fallback_reason": "",
        }
        yield "Arr, here it is."

    core.provider_router.stream = stream  # type: ignore[method-assign]
    core.provider_router.detect_provider = lambda *_args, **_kwargs: type(  # type: ignore[method-assign]
        "Info", (), {"available": True, "models": ["fake-local-model"], "name": "ollama"}
    )()
    return core


def _settings(**extra):
    from modules.chat_profile import ChatProfile
    from nexus_router import RouterConfig

    return {
        "chat_profile": ChatProfile(enabled=False),
        "router_config": RouterConfig(default_model="fake-local-model", enabled=True),
        "provider_order": ["ollama", "fallback"],
        "selected_model": "fake-local-model",
        "base_url": "http://localhost:11434",
        "use_memory": False,
        "use_knowledge_for_chat": False,
        "use_web_for_chat": False,
        "generation_timeout": 5.0,
        "enable_reality_grounding": False,
        "enable_reality_first_reasoning": False,
        "auto_precision_mode": True,
        "staged_streaming": False,
        "enable_response_self_critic": False,
        **extra,
    }


def test_every_chat_turn_sends_the_owners_text_once_as_the_system_prompt():
    seen: list = []
    core = _stand_in_core(seen)
    owner = "Always answer like a pirate and call me skipper."
    messages = (
        "What is cerebral palsy?",
        "Plan the next steps for my vegetable garden project.",
        "My Python script crashes with a KeyError when it reads the config file. How do I fix it?",
    )
    kinds = set()
    for message in messages:
        # With Auto Precision on, nearly every message is a quick turn; off, a plan or a bug report is a full one.
        core.generate_chat_response(message, [], _settings(behavior_text=owner, auto_precision_mode=message == messages[0]))
        request = seen[-1]
        assert owner in request.system_prompt and CONTENT_RULE in request.system_prompt, message
        assert core.last_prompt["system"] == request.system_prompt  # what the Behaviour panel shows is what was sent
        assert owner not in request.prompt and CONTENT_RULE not in request.prompt, message  # sent once
        kinds.add("full" if core.last_response_plan["context_policy"] == "project_memory" and request.prompt.count("Active route:") else "quick")
    assert kinds == {"quick", "full"}  # both ways a prompt is built were seen


HISTORY = [
    {"role": "user", "content": "From now on, answer only in French."},
    {"role": "assistant", "content": "D'accord, je réponds en français."},
    {"role": "user", "content": "Tell me about the Roman Empire."},
    {"role": "assistant", "content": "The Roman Empire ruled the Mediterranean for centuries."},
]


def test_a_quick_turn_keeps_the_conversation_and_the_owners_standing_instructions():
    seen: list = []
    core = _stand_in_core(seen)

    for message in ("What is the capital of Peru?", "What about its economy?"):
        core.generate_chat_response(message, HISTORY, _settings())
        prompt = seen[-1].prompt
        assert "From now on, answer only in French." in prompt and "Roman Empire" in prompt, prompt
        assert "Do not bring in old chat" not in prompt
        # Still a quick turn: none of the app's memory notes, files or research.
        assert "Relevant memory" not in prompt and "Relevant files/knowledge" not in prompt


def test_by_default_the_model_answers_what_the_app_used_to_answer_itself():
    for message, built_in in (("am I cooked?", "local_fast_path"), ("do it", "local_followup_clarification")):
        seen: list = []
        core = _stand_in_core(seen)
        core.generate_chat_response(message, [], _settings())
        assert core.last_provider_result.get("provider") == "ollama" and seen, message

        by_kind_seen: list = []
        by_kind = _stand_in_core(by_kind_seen)
        by_kind.generate_chat_response(message, [], _settings(answer_shape="kind"))
        assert by_kind.last_provider_result.get("provider") == built_in and not by_kind_seen, message


def test_by_kind_of_message_a_quick_turn_is_still_the_bare_message():
    seen: list = []
    core = _stand_in_core(seen)

    core.generate_chat_response("What is the capital of Peru?", HISTORY, _settings(answer_shape="kind"))

    assert "French" not in seen[-1].prompt and "Do not bring in old chat" in seen[-1].prompt


def test_the_temperature_is_the_routes_unless_the_owner_chose_by_kind_of_message():
    seen: list = []
    core = _stand_in_core(seen)

    core.generate_chat_response("What is cerebral palsy?", [], _settings())
    owners = float(seen[-1].options["temperature"])
    core.generate_chat_response("What is cerebral palsy?", [], _settings(answer_shape="kind"))
    by_kind = float(seen[-1].options["temperature"])

    assert by_kind <= 0.1 < owners


def test_the_research_simulation_route_no_longer_rewrites_the_models_words():
    from modules.chat_profile import ChatProfile

    answer = "Maybe the bridge holds.\n\nHowever, the cables are old. I think they need checking."
    profile = ChatProfile(enabled=True, synthesis_confidence=0.9, corporate_hedging_penalty=-0.6)
    settings = {"chat_profile": profile, "enable_reality_grounding": True, "show_grounding_notes": False}

    assert NexusCore()._audit_answer(answer, label="chat", route_category="research_simulation", settings=settings) == answer
