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
