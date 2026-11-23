"""When the model fails, nothing downstream may treat the failure notice as the model's work:
not research summaries, not saved memory, not knowledge answers, not the chat's answer label."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules import event_log, web_research
from modules.answer_meta import answer_meta, describe_answer
from modules.chat_profile import ChatProfile
from modules.nexus_core import NexusCore
from modules.provider_router import ModelUnavailableError, ProviderInfo, ProviderRequest
from modules.providers import FALLBACK_RESPONSE
from modules.research import query_knowledge
from nexus_router import RouterConfig

RESULTS = [
    {
        "title": "Release notes - Streamlit Docs",
        "url": "https://docs.streamlit.io/develop/quick-reference/release-notes",
        "snippet": "Version 1.67.0 (latest). Release date: November 5, 2026.",
        "source": "docs.streamlit.io",
    }
]
PAGES = [{"success": True, "title": "Release notes", "url": RESULTS[0]["url"], "text": "Version 1.67.0 is the latest."}]


def chat_settings(**overrides) -> dict:
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
        "auto_precision_mode": True,
        "response_mode": "auto",
        "verbosity_level": 1,
        "reasoning_depth": 1,
        "staged_streaming": False,
        "enable_response_self_critic": False,
    }
    settings.update(overrides)
    return settings


def core_with_dead_model() -> NexusCore:
    """A core whose only model provider is set up and fails on every request."""

    core = NexusCore()
    info = ProviderInfo(name="ollama", available=True, message="ok", models=["fake-local-model"], base_url="http://ollama.test")

    def detect(name: str, ttl=None) -> ProviderInfo:
        return info if name == "ollama" else ProviderInfo(name=name, available=name == "fallback", message=name)

    def dead(_request, _info, _model):
        raise RuntimeError("connection refused")
        yield ""  # pragma: no cover

    core.provider_router.detect_provider = detect  # type: ignore[method-assign]
    core.provider_router._stream_ollama = dead  # type: ignore[method-assign]
    return core


def gathered(results=RESULTS, pages=PAGES) -> dict:
    return {
        "query": "the latest version of Streamlit",
        "brief": True,
        "results": list(results),
        "scraped_pages": list(pages),
        "errors": [],
        "timings": {"search": 0.1, "scrape": 0.0},
        "started": 0.0,
        "has_sources": bool(results),
    }


# --- research summaries --------------------------------------------------------------------------


def test_summary_result_says_whether_a_model_wrote_it():
    text, generated = web_research.summarize_research_result("q", RESULTS, [], lambda prompt: "Streamlit 1.67.0 is the latest.")
    assert generated is True
    assert text.startswith("Streamlit 1.67.0 is the latest.")


def test_failed_summary_is_a_notice_naming_the_failure_not_a_summary():
    def failing(_prompt: str) -> str:
        raise ModelUnavailableError("ollama: connection refused")

    text, generated = web_research.summarize_research_result("q", RESULTS, [], failing)

    assert generated is False
    assert text.startswith("AI summarization failed: ollama: connection refused")
    assert "Not found in the sources" not in text  # a notice is not checked like an answer


def test_empty_or_missing_summary_is_not_generated():
    assert web_research.summarize_research_result("q", RESULTS, [], lambda prompt: "  ")[1] is False
    assert web_research.summarize_research_result("q", RESULTS, [], None)[1] is False
    assert web_research.summarize_research_result("q", [], [], lambda prompt: "anything") == (web_research.NO_RESULTS_SUMMARY, False)


def test_a_failure_notice_is_not_stored_in_memory_as_a_research_summary():
    with patch.object(web_research, "add_research_to_memory", return_value={"stored": True}) as store:
        session = web_research.finish_research_session(
            gathered(),
            "AI summarization failed: ollama: connection refused",
            settings={"brief": True},
            save_locally=False,
            summary_generated=False,
        )

    assert store.call_args.args[2] == ""  # the pages are stored, the notice is not
    assert session["summary_generated"] is False


def test_a_real_summary_is_stored():
    with patch.object(web_research, "add_research_to_memory", return_value={"stored": True}) as store:
        session = web_research.finish_research_session(gathered(), "Streamlit 1.67.0.", settings={}, save_locally=False)

    assert store.call_args.args[2] == "Streamlit 1.67.0."
    assert session["summary_generated"] is True


def test_research_session_with_a_dead_model_reports_it_and_saves_no_summary():
    core = core_with_dead_model()
    with patch.object(web_research, "gather_research", return_value=gathered()), patch.object(
        web_research, "add_research_to_memory", return_value={"stored": True}
    ) as store:
        session = core.run_web_research("latest streamlit", chat_settings(), save_locally=False)

    assert session["summary_generated"] is False
    assert "AI summarization failed" in session["summary"]
    assert "ollama: connection refused" in session["summary"]
    assert FALLBACK_RESPONSE not in session["summary"]
    assert store.call_args.args[2] == ""


def test_skipped_summary_is_not_stored_as_a_summary():
    with patch.object(web_research, "gather_research", return_value=gathered()), patch.object(
        web_research, "add_research_to_memory", return_value={"stored": True}
    ) as store:
        session = web_research.run_research_session("q", summarize_with_ai=False, save_locally=False)

    assert session["summary_generated"] is False
    assert store.call_args.args[2] == ""


# --- NexusCore helpers ---------------------------------------------------------------------------


def test_model_text_raises_instead_of_returning_the_fallback_notice():
    core = core_with_dead_model()

    with pytest.raises(ModelUnavailableError, match="ollama: connection refused"):
        core._model_text("Summarize this.", chat_settings(), {"num_predict": 32})


def test_route_classifier_gets_no_opinion_from_a_dead_model():
    core = core_with_dead_model()
    classify = core._make_classifier(chat_settings(), RouterConfig(default_model="fake-local-model", use_llm_classifier=True))

    assert classify("Classify this message.") == ""


def test_provider_request_carries_the_cloud_fallback_choice():
    core = NexusCore()

    assert core._provider_request("p", chat_settings(), {}).allow_cloud_fallback is None
    assert core._provider_request("p", chat_settings(allow_cloud_fallback=True), {}).allow_cloud_fallback is True
    assert core._provider_request("p", chat_settings(allow_cloud_fallback=False), {}).allow_cloud_fallback is False


# --- chat --------------------------------------------------------------------------------------------


def test_chat_web_answer_with_a_dead_model_is_not_presented_or_saved_as_a_summary():
    core = core_with_dead_model()
    settings = chat_settings(use_web_for_chat=True)

    with patch("modules.nexus_core.gather_research", return_value=gathered(pages=[])), patch(
        "modules.nexus_core.finish_research_session"
    ) as finish:
        text = "".join(core.stream_chat_response("search the web for the latest version of Streamlit", [], settings))

    assert text.startswith(FALLBACK_RESPONSE)
    assert "ollama: connection refused" in text
    assert "The model did not finish a summary" in text
    assert "Not found in the sources" not in text
    assert RESULTS[0]["url"] in text  # the pages are still offered
    assert finish.call_args.kwargs["summary_generated"] is False
    result = core.last_provider_result
    assert (result["provider"], result["model_provider"], result["success"]) == ("web_research", "fallback", False)
    assert "connection refused" in result["fallback_reason"]

    line = describe_answer(answer_meta(result))
    assert line.startswith("Web search; no model wrote a summary")
    assert "connection refused" in line


def test_chat_with_a_dead_model_is_labelled_as_no_model_answered():
    core = core_with_dead_model()

    text = "".join(core.stream_chat_response("Explain how photosynthesis works in plants.", [], chat_settings()))

    assert "Fallback:" in text
    result = core.last_provider_result
    assert result["provider"] == "fallback"
    assert result["success"] is False
    line = describe_answer(answer_meta(result))
    assert line.startswith("No model answered")
    assert "ollama: connection refused" in line
    assert event_log.event_counts()["provider_fallback"] == 1


def test_each_turn_starts_without_the_previous_turns_provider_result():
    core = NexusCore()
    core.last_provider_result = {"provider": "anthropic", "model": "claude-sonnet-5-5", "success": True}
    stream = core.stream_chat_response("hello", [], chat_settings(provider_order=["fallback"]))

    next(stream)

    assert core.last_provider_result.get("provider") != "anthropic"


# --- knowledge answers -------------------------------------------------------------------------------


class FakeKnowledge:
    def semantic_search(self, query: str, top_k: int = 5) -> list[dict]:
        return [{"title": "Notes", "url": "", "text": "The backup runs at 02:00."}]

    def generate_response(self, query: str, results: list[dict]) -> str:
        return "From Notes: The backup runs at 02:00."


def test_knowledge_answer_falls_back_to_passages_when_the_model_fails():
    def failing(_prompt: str) -> str:
        raise ModelUnavailableError("ollama: connection refused")

    result = query_knowledge(FakeKnowledge(), "when is the backup?", model="m", base_url="", provider_ready=True, ai_callback=failing)

    assert result["model_answered"] is False
    assert "ollama: connection refused" in result["model_error"]
    assert result["answer"].startswith("The model did not answer (ollama: connection refused)")
    assert "The backup runs at 02:00." in result["answer"]


def test_knowledge_answer_from_a_working_model():
    result = query_knowledge(
        FakeKnowledge(), "when is the backup?", model="m", base_url="", provider_ready=True, ai_callback=lambda prompt: "At 02:00."
    )

    assert result == {"answer": "At 02:00.", "results": FakeKnowledge().semantic_search(""), "model_answered": True, "model_error": ""}


def test_legacy_ollama_path_does_not_pass_the_fallback_notice_off_as_an_answer():
    with patch("modules.research.generate_with_ollama", return_value=f"{FALLBACK_RESPONSE}\n\nProvider error: timed out"):
        result = query_knowledge(FakeKnowledge(), "when is the backup?", model="m", base_url="", provider_ready=True)

    assert result["model_answered"] is False
    assert "timed out" in result["model_error"]
    assert FALLBACK_RESPONSE not in result["answer"]
    assert "The backup runs at 02:00." in result["answer"]


# --- answer labels -----------------------------------------------------------------------------------


def test_label_for_a_local_model_answer():
    meta = answer_meta(
        {"provider": "ollama", "model": "dolphin3:8b", "success": True, "elapsed": 12.34, "retrieval": {"used_count": 2}}
    )

    assert meta["locality"] == "local" and meta["answered"] is True
    assert describe_answer(meta) == "Answered by Ollama / dolphin3:8b · stayed on this machine · 12.3 s · used local knowledge"


def test_label_for_a_cloud_answer_shows_where_the_prompt_went_and_the_cost():
    meta = answer_meta(
        {
            "provider": "anthropic",
            "model": "claude-sonnet-5-5",
            "success": True,
            "elapsed": 4.2,
            "usage": {"input_tokens": 1000, "output_tokens": 200, "estimated_cost_usd": 0.004},
        }
    )

    assert meta["locality"] == "cloud"
    assert describe_answer(meta) == (
        "Answered by Anthropic / claude-sonnet-5-5 · your prompt was sent to Anthropic · 4.2 s · "
        "about $0.0040 (1000 in / 200 out tokens)"
    )


def test_label_for_a_cloud_answer_with_unknown_price_does_not_invent_a_cost():
    meta = answer_meta(
        {"provider": "openai", "model": "gpt-4.1-mini", "success": True, "usage": {"input_tokens": 50, "output_tokens": 9}}
    )

    line = describe_answer(meta)
    assert "price not known" in line and "$" not in line


def test_label_for_a_web_answer_written_by_a_local_model():
    meta = answer_meta(
        {"provider": "web_research", "model_provider": "ollama", "model": "dolphin3:8b", "success": True, "elapsed": 51.0, "tools_run": ["web_search"]}
    )

    assert meta["locality"] == "web"
    assert describe_answer(meta) == (
        "Web search, written up by Ollama / dolphin3:8b · searches went to the web; the text was written on this machine · 51.0 s"
    )


def test_label_for_replies_that_used_no_model():
    built_in = describe_answer(answer_meta({"provider": "local_fast_path", "success": True, "elapsed": 0.01}))
    assert built_in == "Built-in reply, no model used · stayed on this machine"

    passages = describe_answer(answer_meta({"provider": "local_knowledge_fallback", "success": True, "elapsed": 0.3, "fallback_reason": "x"}))
    assert passages.startswith("Passages from your saved knowledge; no model was available")
    assert "Reason" not in passages


def test_label_for_a_cut_off_answer_and_a_skipped_cloud_provider():
    cut = describe_answer(
        answer_meta({"provider": "ollama", "model": "dolphin3:8b", "success": False, "partial": True, "fallback_reason": "ollama: read timed out"})
    )
    assert cut.startswith("Ollama / dolphin3:8b stopped part-way through this answer")
    assert cut.endswith("Reason: ollama: read timed out")

    skipped = describe_answer(
        answer_meta({"provider": "fallback", "success": False, "fallback_reason": "ollama: refused", "skipped_cloud": ["anthropic"]})
    )
    assert "No model answered" in skipped
    assert skipped.endswith("(Anthropic is set up but cloud fallback is off.)")


def test_label_mentions_a_substituted_model():
    note = "Requested Ollama model 'missing:model' is not installed; using 'llama3.2:3b'."
    line = describe_answer(answer_meta({"provider": "ollama", "model": "llama3.2:3b", "success": True, "model_note": note}))

    assert line.endswith(f"Note: {note}")


def test_web_research_result_says_who_wrote_the_summary():
    core = core_with_dead_model()
    with patch.object(web_research, "gather_research", return_value=gathered()), patch.object(
        web_research, "add_research_to_memory", return_value={"stored": True}
    ):
        session = core.run_web_research("latest streamlit", chat_settings(), save_locally=False)

    label = describe_answer(session["produced_by"])
    assert label.startswith("Web search; no model wrote a summary")
    assert "connection refused" in label

    core.provider_router._stream_ollama = lambda _request, _info, _model: iter(["Streamlit 1.67.0 is the latest."])  # type: ignore[method-assign]
    with patch.object(web_research, "gather_research", return_value=gathered()), patch.object(
        web_research, "add_research_to_memory", return_value={"stored": True}
    ):
        session = core.run_web_research("latest streamlit", chat_settings(), save_locally=False)

    assert session["summary_generated"] is True
    assert describe_answer(session["produced_by"]).startswith("Web search, written up by Ollama / fake-local-model")


def test_knowledge_result_says_whether_a_model_answered():
    core = core_with_dead_model()
    core._research_module = FakeKnowledge()

    extractive = core.answer_knowledge("when is the backup?", chat_settings(knowledge_use_ai=False))
    assert describe_answer(extractive["produced_by"]).startswith("Passages from your saved knowledge, no model used")

    failed = core.answer_knowledge("when is the backup?", chat_settings(knowledge_use_ai=True))
    assert failed["model_answered"] is False
    failed_label = describe_answer(failed["produced_by"])
    assert failed_label.startswith("Passages from your saved knowledge, no model used")
    assert "connection refused" in failed_label

    core.provider_router._stream_ollama = lambda _request, _info, _model: iter(["At 02:00."])  # type: ignore[method-assign]
    answered = core.answer_knowledge("when is the backup?", chat_settings(knowledge_use_ai=True))
    assert answered["model_answered"] is True
    assert describe_answer(answered["produced_by"]).startswith("Answered by Ollama / fake-local-model · stayed on this machine")


def test_label_is_empty_when_nothing_is_known():
    assert describe_answer(None) == ""
    assert describe_answer(answer_meta({})) == ""


def test_request_default_leaves_cloud_choice_to_the_saved_setting():
    assert ProviderRequest(prompt="p").allow_cloud_fallback is None
