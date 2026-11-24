"""Diagnostics shows how the last answer was made, without its text."""

from __future__ import annotations

from ui.answer_diagnostics import answer_rows


def test_a_cut_off_answer_shows_why_and_with_what_limits():
    rows = {row["What"]: row["Value"] for row in answer_rows(
        {
            "provider": "ollama",
            "model": "dolphin3:8b",
            "stopped_because": "length",
            "generation": {"num_predict": 384, "num_ctx": 2048, "temperature": 0.55, "requested_words": [450, 550], "words_written": 307, "throughput_profile": "fast"},
            "timings": {"provider_first_token_ms": 15600.0, "total_ms": 86900.0},
            "attempts": [{"provider": "ollama", "success": True}],
            "text": "the answer itself must not appear",
        },
        {"stage": "not_a_candidate"},
    )}

    assert rows["Answered by"] == "ollama / dolphin3:8b" and rows["Why the model stopped"].startswith("hit its token limit")
    assert (rows["Length asked for"], rows["Length written"], rows["Token limit given to the model"]) == ("450 to 550 words", "307 words", "384")
    assert rows["Speed profile"] == "fast" and rows["First word after"] == "15.6 s" and rows["Total time"] == "86.9 s"
    assert rows["Content rule"] == "not looked at closer (nothing to check)"
    assert "must not appear" not in str(rows)


def test_a_calculation_an_unclear_check_and_a_web_answer_are_described():
    calculated = {row["What"]: row["Value"] for row in answer_rows({"provider": "calculator", "calculation": {"expression": "7 * 6", "value": 42}, "elapsed": 0.01}, {"stage": "judge_unclear"})}
    assert calculated["Calculation"] == "7 * 6 = 42" and calculated["Content rule"] == "the check could not decide (not a finding)"

    web = {row["What"]: row["Value"] for row in answer_rows({"provider": "web_research", "search_plan": {"source": "model", "queries": ["cannabis dispensary Omaha", "Omaha cannabis prices"]}})}
    assert web["Search plan"] == "model: cannabis dispensary Omaha; Omaha cannabis prices"
    assert answer_rows({}) == [] and answer_rows(None) == []


def test_a_web_answer_shows_what_was_searched_judged_and_left_out():
    rows = answer_rows(
        {
            "provider": "web_research",
            "search_plan": {"source": "model", "question": "best weed in Omaha", "topic": "The best cannabis in Omaha.", "queries": ["best cannabis dispensary in Omaha"]},
            "searches": [
                {"query": "best cannabis dispensary in Omaha", "returned": 5, "kept": 3, "dropped": 2, "judged": 2, "judged_off_topic": 2},
                {"query": "Nebraska cannabis law", "purpose": "law or availability", "returned": 0, "kept": 0, "dropped": 0, "error": "rate limited"},
            ],
            "dropped_results": [{"title": "Best 24 Weed Control Service in Omaha", "url": "https://lawn.example/", "reason": "judged by the model to be about something else (lawn weed control)"}],
        }
    )
    shown = [(row["What"], row["Value"]) for row in rows]

    assert ("Taken to mean", "The best cannabis in Omaha.") in shown
    assert ("Search", "best cannabis dispensary in Omaha: 5 found, 3 kept, 2 dropped, 2 judged by the model") in shown
    assert ("Search for law or availability", "Nebraska cannabis law: failed (rate limited)") in shown
    assert ("Left out", "Best 24 Weed Control Service in Omaha: judged by the model to be about something else (lawn weed control)") in shown
