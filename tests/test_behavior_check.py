"""The real-model behaviour check: its question list, its bookkeeping, and the saved result."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import behavior_check  # noqa: E402

from modules.behavior_policy import CONTENT_RULE_REPLY  # noqa: E402
from modules.nexus_core import NexusCore  # noqa: E402

SAVED = ROOT / "docs" / "benchmarks" / "behavior_dolphin3-8b.json"
PROMPTS = behavior_check.load_prompts()


def stand_in_core(answer_for) -> NexusCore:
    """A real core whose model is a stand-in: it answers with whatever `answer_for(prompt text)` returns."""

    core = NexusCore()

    def stream(request):
        core.provider_router.last_stream_metadata = {
            "provider": "ollama",
            "model": request.model,
            "success": True,
            "attempts": [{"provider": "ollama", "success": True}],
            "fallback_reason": "",
        }
        yield answer_for(request.prompt)

    def judge(request):
        return SimpleNamespace(text="CLOTHED" if request.prompt.rstrip().endswith("Dressed:") else "NO")

    core.provider_router.stream = stream  # type: ignore[method-assign]
    core.provider_router.generate_or_raise = judge  # type: ignore[method-assign]
    core.provider_router.detect_provider = lambda *_a, **_k: SimpleNamespace(available=True, models=["stand-in"], name="ollama")  # type: ignore[method-assign]
    return core


def test_the_list_covers_what_the_owner_named():
    groups = {prompt["group"] for prompt in PROMPTS}

    assert {"adult subjects", "drugs", "money", "controversial subjects", "the owner's own instructions", "ordinary questions about minors"} <= groups
    assert len({prompt["id"] for prompt in PROMPTS}) == len(PROMPTS) >= 16


def test_with_a_stand_in_model_no_question_is_stopped_by_the_app_and_each_arrives_unchanged():
    """What the app does with these questions does not depend on the model: it passes every one on."""

    core = stand_in_core(lambda _prompt: "A full answer.")

    result = behavior_check.run(core, behavior_check.chat_settings("stand-in", "http://127.0.0.1:9"), PROMPTS)

    summary = result["summary"]
    assert summary["stopped_by_app"] == [] and summary["not_answered"] == [] and summary["declined_by_model"] == []
    assert summary["message_changed_or_fenced"] == []
    assert all(row["provider"] == "ollama" for row in result["rows"])
    # Only the two questions that name a minor are looked at by the rule's check; it lets them through.
    looked_at = {row["id"] for row in result["rows"] if row["content_rule_stage"] != "not_a_candidate"}
    assert looked_at == {"minors-1", "minors-2"}


def test_a_refusal_by_the_model_is_counted_as_the_models_and_a_stop_by_the_app_as_the_apps():
    refusing = stand_in_core(lambda _prompt: "I'm sorry, but I can't help with that.")
    settings = behavior_check.chat_settings("stand-in", "http://127.0.0.1:9")

    declined = behavior_check.run(refusing, settings, PROMPTS[:2])["summary"]
    assert declined["declined_by_model"] == [PROMPTS[0]["id"], PROMPTS[1]["id"]] and declined["stopped_by_app"] == []

    stopped = behavior_check.summarize(
        [{"id": "x", "group": "g", "stopped_by_app": True, "answered_by_model": False, "declined_by_model": False, "fenced_or_scanned": False, "the_message_reached_the_model_unchanged": True}]
    )
    assert stopped["stopped_by_app"] == ["x"] and stopped["not_answered"] == []
    assert CONTENT_RULE_REPLY in behavior_check.APP_TEXTS


def test_explicit_writing_is_not_stored():
    core = stand_in_core(lambda _prompt: "Explicit text that should not be kept in the repository.")
    prompt = next(item for item in PROMPTS if item.get("store_opening") is False)

    row = behavior_check.check_one(core, prompt, behavior_check.chat_settings("stand-in", "http://127.0.0.1:9"))

    assert row["answered_by_model"] and "Explicit text" not in json.dumps(row)


def test_the_saved_run_with_the_real_model_shows_nothing_stopped_by_the_app():
    saved = json.loads(SAVED.read_text(encoding="utf-8"))

    assert saved["model"] == "dolphin3:8b"
    assert {row["id"] for row in saved["rows"]} == {prompt["id"] for prompt in PROMPTS}
    summary = saved["summary"]
    assert summary["stopped_by_app"] == []
    assert summary["message_changed_or_fenced"] == []
    assert summary["not_answered"] == []
