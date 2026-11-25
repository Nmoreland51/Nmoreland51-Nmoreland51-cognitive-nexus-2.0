"""The tools that find where a refusal, a redirect or a short answer comes from (2026-11-25): their bookkeeping.

The real runs are in docs/benchmarks/ (attribution_dolphin3-8b.json, configurations_coding_agents.json).
Here the model server is played by a stand-in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import answer_attribution as attribution  # noqa: E402
import configuration_compare as compare  # noqa: E402

from nexus_router import RouteDecision  # noqa: E402


class _Stream:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def iter_lines(self, decode_unicode: bool = False):
        yield from self.lines


class _Server:
    """Answers a streamed request with two pieces of text and anything else with nothing."""

    def __init__(self) -> None:
        self.posted: list[tuple[str, dict]] = []

    def post(self, url, json=None, **_kwargs):
        self.posted.append((url, json))
        if json and json.get("stream"):
            return _Stream(['{"response": "Hello ", "done": false}', '{"response": "there.", "done": true, "done_reason": "stop", "eval_count": 2}'])
        return None


def test_the_recorder_keeps_each_request_as_sent_and_the_text_that_came_back():
    server = _Server()
    with attribution.Recorder(server, seed=11) as recorder:
        server.post("http://ollama.test/api/generate", json={"model": "m", "prompt": "a check", "stream": False, "options": {"num_predict": 6}})
        streamed = server.post("http://ollama.test/api/generate", json={"model": "m", "prompt": "the chat", "stream": True, "options": {"num_predict": 400}})
        text = "".join(json.loads(line)["response"] for line in streamed.iter_lines(decode_unicode=True))

    assert text == "Hello there."
    chat = recorder.chat_call()
    assert chat is not None and chat["payload"]["prompt"] == "the chat"
    assert chat["payload"]["options"] == {"num_predict": 400, "seed": 11}  # the only change: a fixed seed
    assert chat["received"] == "Hello there." and chat["done_reason"] == "stop" and chat["eval_count"] == 2
    assert len(recorder.calls) == 2
    assert server.post.__func__ is _Server.post  # put back afterwards


def test_the_model_alone_gets_only_its_own_settings():
    payload = attribution.direct_payload("dolphin3:8b", "Is Pluto a planet?")

    assert payload == {
        "model": "dolphin3:8b",
        "prompt": "Is Pluto a planet?",
        "options": {"seed": attribution.SEED, "num_ctx": 4096, "num_predict": 2048},
    }


def test_each_answer_is_described_without_storing_explicit_writing():
    refusal = attribution.describe("I'm sorry, but I can't assist with that.", "stop", True)
    cut = attribution.describe("word " * 30, "length", False)

    assert refusal["reads_like_refusal"] and refusal["words"] == 8 and not refusal["cut_by_length_limit"]
    assert cut["cut_by_length_limit"] and cut["words"] == 30 and cut["opening"].startswith("[not stored")


def test_the_summary_says_where_each_difference_was_seen():
    def part(words, refusal=False, ended="stop"):
        return {"words": words, "reads_like_refusal": refusal, "cut_by_length_limit": ended == "length", "ended": ended}

    rows = [
        {"id": "a", "group": "g", "app": {"stopped_by_app": False}, "direct": part(392), "displayed": part(58, ended="length"), "stored_equals_displayed": True, "displayed_equals_received": True},
        {"id": "b", "group": "g", "app": {"stopped_by_app": False}, "direct": part(8, refusal=True), "displayed": part(8, refusal=True), "stored_equals_displayed": False, "displayed_equals_received": False},
    ]
    summary = attribution.summarize(rows)

    assert summary["reads_like_refusal"] == {"direct": ["b"], "nexus": [], "displayed": ["b"]}
    assert summary["cut_by_length_limit"] == {"direct": [], "displayed": ["a"]}
    assert summary["changed_after_the_model"] == ["b"] and summary["stored_differs_from_displayed"] == ["b"]
    assert summary["by_group"]["g"] == {"asked": 2, "median_words_direct": 392, "median_words_displayed": 58}


def test_the_research_configuration_routes_the_message_as_a_web_question():
    def route_message(message, config, classifier=None):
        return RouteDecision(category="standard_conversation", reason="r", confidence=0.5, model="m", generation_options={})

    decision = compare._forced_web_route(route_message)("Which coding agents can I run locally?", None)

    # Auto Precision keeps web search on only for the web_research category.
    assert decision.category == "web_research" and decision.requires_web_search
    assert decision.search_query == "Which coding agents can I run locally?"


def test_the_requests_are_named_once_and_some_were_written_before_any_change():
    prompts = attribution.load_prompts()
    ids = [prompt["id"] for prompt in prompts]

    assert len(ids) == len(set(ids)) == 27
    assert all(prompt["text"].strip() and prompt["group"] for prompt in prompts)
    assert sum(1 for prompt in prompts if prompt.get("held_out")) == 6
