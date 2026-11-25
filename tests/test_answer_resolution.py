"""An answer the app could not ground can be answered again: looked up on the web, or by another model.

Found on 2026-11-25 with the owner's own question ("Which coding agents can I run locally ... compare?"):
dolphin3:8b listed IDEs, alone through Ollama as through the app, and with the word "illegal" taken out it
listed TensorFlow and PyTorch. The app rated the answer LOW CONFIDENCE and delivered it with nothing to be
done about it. With the chat's web search the same model named AI coding agents from the pages it read.
(tools/configuration_compare.py; the runs are in docs/benchmarks/configurations_coding_agents.json.)

Model and model server are played by stand-ins here.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from modules.answer_resolution import is_ungrounded, other_models, resolution_label, resolution_settings
from modules.behavior_policy import UNGROUNDED_HELP, apply_behavior_changes, effective_policy, policy_from
from modules.nexus_core import NexusCore
from modules.research_plan import SearchPlan
from tests.test_answer_shape import _settings


def test_an_answer_is_ungrounded_when_a_model_wrote_it_without_sources_and_it_is_rated_low():
    model_answer = {"provider": "ollama", "sources": 0}
    assert is_ungrounded(model_answer, {"confidence": {"level": "LOW CONFIDENCE"}})
    assert is_ungrounded(model_answer, {"confidence": {"level": "SPECULATIVE"}})
    assert not is_ungrounded(model_answer, {"confidence": {"level": "HIGH CONFIDENCE"}})
    assert not is_ungrounded({"provider": "ollama", "sources": 2}, {"confidence": {"level": "LOW CONFIDENCE"}})
    # Nothing to look up or ask again: the app's own replies, and no model at all.
    for provider in ("fallback", "local_fast_path", "content_rule", "adaptive_memory"):
        assert not is_ungrounded({"provider": provider}, {"confidence": {"level": "LOW CONFIDENCE"}}), provider


def test_the_same_question_again_on_the_web_or_by_another_model_on_every_route():
    from nexus_router import RouterConfig

    settings = {"selected_model": "dolphin3:8b", "router_config": RouterConfig(default_model="dolphin3:8b", creative_model="dolphin3:8b", technical_model="dolphin3:8b")}

    web = resolution_settings(settings, research=True)
    other = resolution_settings(settings, model="qwen2.5-coder:7b")

    assert web["_force_web_research"] and web["use_web_for_chat"] and "_force_web_research" not in settings
    assert other["selected_model"] == "qwen2.5-coder:7b"
    config = other["router_config"]
    assert {config.default_model, config.creative_model, config.technical_model, config.sensitive_model, config.current_info_model} == {"qwen2.5-coder:7b"}
    assert settings["router_config"].default_model == "dolphin3:8b"  # the owner's settings are not changed
    assert other_models(["dolphin3:8b", "qwen2.5-coder:7b", "llama3.2:3b", "mistral", "phi"], "dolphin3:8b") == ["qwen2.5-coder:7b", "llama3.2:3b", "mistral"]
    assert resolution_label(True, "") == "Looked up on the web and answered again"
    assert resolution_label(False, "qwen2.5-coder:7b") == "Answered again by qwen2.5-coder:7b"


def test_the_setting_is_the_owners_and_is_validated():
    assert policy_from({}).ungrounded_answers == "offer"
    assert policy_from({"ungrounded_answers": "research"}).ungrounded_answers == "research"
    assert apply_behavior_changes({}, {"ungrounded_answers": "off"})["ungrounded_answers"] == "off"
    assert effective_policy({})["application"]["ungrounded_answers"] == UNGROUNDED_HELP["offer"]


def test_a_question_the_owner_asks_to_have_looked_up_goes_through_the_chats_web_search(monkeypatch):
    """The web answer carries the owner's system prompt and takes the length and form the question asks for."""

    sent: list = []
    core = NexusCore()

    def stream(request):
        sent.append(request)
        core.provider_router.last_stream_metadata = {"provider": "ollama", "model": "fake-local-model", "success": True, "attempts": [], "fallback_reason": ""}
        yield "Aider and Continue run locally."

    core.provider_router.stream = stream  # type: ignore[method-assign]
    core.provider_router.detect_provider = lambda *_args, **_kwargs: type("Info", (), {"available": True, "models": ["fake-local-model"], "name": "ollama"})()  # type: ignore[method-assign]
    core.plan_web_search = lambda message, settings: SearchPlan(question=message, topic=message, queries=[message], source="as_typed")  # type: ignore[method-assign]
    page = {"url": "https://example.org/agents", "title": "Local coding agents", "text": "Aider and Continue run locally with Ollama.", "success": True}
    gathered = {
        "results": [{"title": "Local coding agents", "url": page["url"], "snippet": "Aider, Continue", "source": "example.org"}],
        "scraped_pages": [page],
        "has_sources": True,
        "timings": {},
        "searches": [],
        "dropped": [],
    }
    monkeypatch.setattr("modules.nexus_core.gather_research", lambda *args, **kwargs: dict(gathered))
    monkeypatch.setattr("modules.nexus_core.finish_research_session", lambda *args, **kwargs: {})  # nothing saved to disk
    owner = "Always answer like a pirate."

    answer = core.generate_chat_response("Which coding agents can I run locally?", [], _settings(behavior_text=owner, _force_web_research=True))

    assert answer.startswith("Aider and Continue run locally.")
    summary = sent[-1]
    assert owner in summary.system_prompt
    assert "in the length and form the question asks for" in summary.prompt and "2-3 short sentences" not in summary.prompt
    assert summary.options["num_predict"] > 160


def _chat_with_stand_in(mode: str) -> None:
    import streamlit as st

    import ui.chat_tab as chat
    from modules.chat_profile import ChatProfile
    from nexus_router import RouterConfig

    class StandIn:
        """Answers without sources and is rated low; looked up on the web, it has sources."""

        def __init__(self) -> None:
            self.config = {"ungrounded_answers": mode}
            self.calls: list[dict] = []

        def stream_chat_response(self, question, messages, settings):
            research = bool(settings.get("_force_web_research"))
            self.calls.append({"question": question, "research": research, "model": settings.get("selected_model"), "history": [m["content"] for m in messages]})
            st.session_state.last_provider_result = {
                "provider": "web_search" if research else "ollama",
                "model_provider": "ollama",
                "model": settings.get("selected_model"),
                "success": True,
                "sources": 2 if research else 0,
                "elapsed": 1.0,
            }
            st.session_state.last_reality_audit = {"confidence": {"level": "HIGH CONFIDENCE" if research else "LOW CONFIDENCE"}}
            yield "Aider and Continue, from the pages read." if research else "TensorFlow and PyTorch."

    core = st.session_state.setdefault("stand_in_core", StandIn())
    chat.get_nexus_core = lambda: core
    chat.sync_core_diagnostics = lambda *args, **kwargs: None
    chat.save_session_history = lambda *args, **kwargs: None
    chat.record_perf = lambda *args, **kwargs: None
    chat.render_chat_tab(
        {
            "router_config": RouterConfig(default_model="dolphin3:8b"),
            "selected_model": "dolphin3:8b",
            "chat_models": ["dolphin3:8b", "qwen2.5-coder:7b"],
            "provider_order": ["ollama", "fallback"],
            "chat_profile": ChatProfile(enabled=False),
        }
    )


QUESTION = "Which coding agents can I run locally?"


def _captions(page) -> str:
    return "\n".join(item.value for item in page.caption)


def test_under_an_ungrounded_answer_the_owner_can_have_it_looked_up_or_asked_again():
    page = AppTest.from_function(_chat_with_stand_in, args=("offer",), default_timeout=30).run()
    page.chat_input[0].set_value(QUESTION).run()

    assert not page.exception
    assert "This answer used no sources and is rated low" in _captions(page)
    assert page.button(key="chat_resolve_model_1").label == "Ask qwen2.5-coder:7b"

    page.button(key="chat_resolve_web").click().run()

    assert not page.exception
    calls = page.session_state["stand_in_core"].calls
    assert [call["research"] for call in calls] == [False, True]
    assert calls[1]["question"] == QUESTION and calls[1]["history"] == [QUESTION]  # asked again without the poor answer
    assert "Looked up on the web and answered again" in _captions(page)
    assert [message["content"] for message in page.session_state["messages"]] == [QUESTION, "TensorFlow and PyTorch.", "Aider and Continue, from the pages read."]
    assert not [button for button in page.button if button.key == "chat_resolve_web"]  # offered once


def test_another_installed_model_can_answer_the_same_question():
    page = AppTest.from_function(_chat_with_stand_in, args=("offer",), default_timeout=30).run()
    page.chat_input[0].set_value(QUESTION).run()
    page.button(key="chat_resolve_model_1").click().run()

    calls = page.session_state["stand_in_core"].calls
    assert calls[1]["model"] == "qwen2.5-coder:7b" and not calls[1]["research"]
    assert "Answered again by qwen2.5-coder:7b" in _captions(page)


def test_with_the_owners_setting_the_web_lookup_follows_by_itself_or_nothing_is_offered():
    by_itself = AppTest.from_function(_chat_with_stand_in, args=("research",), default_timeout=30).run()
    by_itself.chat_input[0].set_value(QUESTION).run()
    assert [call["research"] for call in by_itself.session_state["stand_in_core"].calls] == [False, True]
    assert not [button for button in by_itself.button if button.key == "chat_resolve_web"]

    nothing = AppTest.from_function(_chat_with_stand_in, args=("off",), default_timeout=30).run()
    nothing.chat_input[0].set_value(QUESTION).run()
    assert [call["research"] for call in nothing.session_state["stand_in_core"].calls] == [False]
    assert "This answer used no sources" not in _captions(nothing)
