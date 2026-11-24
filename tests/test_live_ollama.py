"""Integration tests against a real Ollama server and a real model. Skipped unless CN_LIVE_OLLAMA_URL is set.

    CN_LIVE_OLLAMA_URL=http://localhost:11434 python -m pytest tests/test_live_ollama.py
    CN_LIVE_MODEL=dolphin3:8b       (optional; default: the first chat model the server has)

Every other test plays the model with fixed replies, so it shows that the app's own logic is right
and nothing about what happens with a real model. These send real requests through the same code
the app uses and check what can be checked of a real model's work: that an answer arrives and is
labelled as the model's, that it streams piece by piece, that a reply held to a JSON Schema parses
and matches, that the server reports what the model can do, that the one content rule stops and
lets through with the real model as its judge, and that a whole chat turn goes through the app.

There is no model in CI, so they are run by hand; the last run is recorded in
docs/benchmarks/README.md. Cloud providers are not covered: no key was available.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest

LIVE_URL = os.environ.get("CN_LIVE_OLLAMA_URL", "").strip().rstrip("/")
pytestmark = pytest.mark.skipif(not LIVE_URL, reason="set CN_LIVE_OLLAMA_URL to run against a real Ollama server")
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def the_app_points_at_the_live_server():
    """The suite points the app at a closed port (tests/conftest.py); these tests need the real server."""

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OLLAMA_URL", LIVE_URL)
        yield


@pytest.fixture(scope="module")
def router():
    from modules.provider_router import ProviderRouter

    return ProviderRouter({"provider_order": ["ollama"], "ollama_url": LIVE_URL, "allow_cloud_fallback": False})


@pytest.fixture(scope="module")
def model(router):
    found = router.detect_provider("ollama")
    assert found.available, f"The Ollama server at {LIVE_URL} has no chat model: {found.message}"
    wanted = os.environ.get("CN_LIVE_MODEL", "").strip()
    if wanted:
        assert wanted in found.models, f"{wanted} is not installed; the server has {found.models}"
        return wanted
    return found.models[0]


def request(model: str, prompt: str, max_tokens: int, **extra):
    from modules.provider_router import ProviderRequest

    return ProviderRequest(
        prompt=prompt,
        model=model,
        provider_order=["ollama"],
        base_url=LIVE_URL,
        options={"temperature": 0, "num_predict": max_tokens},
        max_tokens=max_tokens,
        timeout=600.0,
        allow_cloud_fallback=False,
        **extra,
    )


def test_the_server_says_what_the_model_can_do(router, model):
    found = router.capabilities("ollama", model)

    assert found.source == "reported by the Ollama server", found.notes
    assert found.chat is True and found.streaming is True and found.context_window and found.context_window >= 2048
    assert found.structured_output is True  # held to a schema by the server for any model that writes


def test_a_request_is_answered_by_the_real_model_and_labelled_as_its_answer(router, model):
    result = router.generate(request(model, "Reply with the single word: ready", 8))

    assert result.success and result.provider == "ollama" and result.model == model
    assert "ready" in result.text.lower()
    throughput = router._last_ollama_throughput
    assert throughput["eval_count"] > 0 and throughput["tokens_per_second"] > 0 and throughput["prompt_fits"]


def test_the_answer_arrives_piece_by_piece(router, model):
    chunks = list(router.stream(request(model, "Count from one to ten in words, separated by spaces.", 40)))

    assert len(chunks) >= 5, chunks  # one piece per token or so, not the whole answer at once
    assert router.last_stream_metadata["success"] is True and "ten" in "".join(chunks).lower()


def test_a_reply_held_to_a_schema_parses_and_matches_it(router, model):
    schema = {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}}, "required": ["city", "country"]}

    result = router.generate(request(model, "Name the capital city of France and the country it is in.", 60, response_schema=schema))

    reply = json.loads(result.text)
    jsonschema.validate(reply, schema)
    assert "paris" in reply["city"].lower()


def test_the_tool_loop_gets_a_step_it_can_use(router, model):
    from agent import toolcall
    from agent.capabilities import register_assistant_tools
    from agent.model import RouterModel, complete_as
    from agent.registry import ToolRegistry

    tools = toolcall.offered(register_assistant_tools(ToolRegistry()))
    llm = RouterModel(router, model=model, provider_order=["ollama"], num_ctx=4096, allow_cloud=False)

    reply = complete_as(llm, toolcall.build_prompt("What is 12 times 12?", tools, []), toolcall.step_schema(tools), max_tokens=200)

    step, problem = toolcall.parse_step(reply.text, tools)
    assert problem == "" and step is not None, reply.text  # the server let the model write nothing else
    assert step["tool"] == "answer" and "144" in step["answer"]


def _cases():
    sets = json.loads((REPO_ROOT / "tests" / "fixtures" / "content_rule_benchmark.json").read_text(encoding="utf-8"))["sets"]
    text = [case for case in sets["heldout"] if case.get("kind", "text") == "text" and case.get("picked_out", True)]
    # One request the rule must stop and one it must let through, both of which reach the judge.
    return [next(case for case in text if case["expect"] == "stop"), next(case for case in text if case["expect"] == "answer")]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: f"{case['id']}-{case['expect']}")
def test_the_one_content_rule_with_the_real_model_as_its_judge(model, case):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import content_rule_benchmark as bench

    row = bench.run_case(case, bench.model_judge(model, LIVE_URL))

    assert row["picked_out"], "the first look should hand this request to the judge"
    # The model must actually have judged it: a judge that cannot be reached also stops a request (fail-closed).
    assert row["stage"] not in {"judge_unavailable", "judge_unclear"}, row
    assert row["did"] == case["expect"], row


def test_a_whole_chat_turn_goes_through_the_app(model):
    """The path, not the model's arithmetic: the answer comes from the real model, through the app, labelled.

    The first version of this test asked "What is 7 times 6?". Through the app the model answered
    84, 42 and 42 in three tries: chat samples with a temperature of 0.35 to 0.7, and at that
    setting this model sometimes gets simple arithmetic wrong. That is recorded in
    docs/benchmarks/README.md as a finding about answers, not a fault in this path.
    """

    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import behavior_check

    from modules.nexus_core import NexusCore

    core = NexusCore()
    answer = core.generate_chat_response("Reply with this one word and nothing else: lighthouse", [], behavior_check.chat_settings(model, LIVE_URL))

    meta = core.last_provider_result
    assert "lighthouse" in answer.lower(), answer
    assert meta["provider"] == "ollama" and meta["success"] is True and meta["model"] == model
