"""Release gates on research quality: ranking, passage selection, staying within the sources.

The parts that need no model run here on every push. The answers a real model wrote are kept in
docs/benchmarks and checked for still describing the prompts the app builds.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from modules import web_research

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import research_benchmark as bench  # noqa: E402

CASES = bench.load_cases()
ANSWERABLE = [case for case in CASES if not case.get("unanswerable")]
UNANSWERABLE = [case for case in CASES if case.get("unanswerable")]
SAVED = REPO_ROOT / "docs" / "benchmarks" / "research_dolphin3-8b.json"


# ---- the cases themselves ---------------------------------------------------------------------


@pytest.mark.parametrize("case", ANSWERABLE, ids=[case["id"] for case in ANSWERABLE])
def test_only_the_pages_marked_as_answering_contain_the_answer(case):
    for item in case["results"]:
        assert bench.has_fact(case, item["text"]) == item["relevant"], item["url"]
    assert any(item["relevant"] for item in case["results"])


@pytest.mark.parametrize("case", UNANSWERABLE, ids=[case["id"] for case in UNANSWERABLE])
def test_unanswerable_cases_really_lack_the_answer(case):
    assert not any(item["relevant"] for item in case["results"])
    for item in case["results"]:
        assert not re.search(case["must_not_match"], item["text"], flags=re.IGNORECASE), item["url"]


def test_case_ids_and_urls_are_unique():
    assert len({case["id"] for case in CASES}) == len(CASES)
    urls = [item["url"] for case in CASES for item in case["results"]]
    assert len(set(urls)) == len(urls)


# ---- gates that need no model -----------------------------------------------------------------


def test_the_answering_page_is_ranked_within_the_pages_that_get_read():
    """Measured 2026-11-23: first in 7 of 9, within the first two in 9 of 9."""

    result = bench.ranking(CASES)
    assert result["cases"] == len(ANSWERABLE)
    assert result["answering_page_in_first_two"] == result["cases"], result["rows"]
    assert result["answering_page_first"] >= 7, result["rows"]
    assert result["mean_reciprocal_rank"] >= 0.88


def test_the_excerpt_taken_from_an_answering_page_contains_the_answer():
    result = bench.passages(CASES)
    assert result["answer_in_excerpt"] == result["pages"] == len(ANSWERABLE), result["rows"]
    assert all(row["excerpt_chars"] <= web_research.BRIEF_PAGE_CHARS for row in result["rows"])


# ---- judging an answer ------------------------------------------------------------------------


def _case(case_id):
    return next(case for case in CASES if case["id"] == case_id)


def _prompt(case):
    return web_research.build_summary_prompt(case["question"], bench.as_search_results(case), bench.as_pages(case, 2), brief=True)


def test_a_correct_answer_within_its_sources_is_judged_so():
    case = _case("tidewater_version")
    verdict = bench.judge(case, "The latest stable release is Tidewater 4.2, published on 3 March 2026.", _prompt(case))
    assert verdict == {"outside_sources": [], "app_warned": False, "correct": True}


def test_a_version_from_the_model_s_memory_is_outside_the_sources():
    case = _case("tidewater_version")
    verdict = bench.judge(case, "The latest release is Tidewater 5.0, which came out in 2024.", _prompt(case))
    assert verdict["correct"] is False
    assert "number 5.0" in verdict["outside_sources"] and "wrong: 5.0" in verdict["outside_sources"]
    assert "number 2024" in verdict["outside_sources"]


def test_an_invented_link_is_outside_the_sources():
    case = _case("quillfeather_port")
    answer = "It listens on port 8472. Source: https://quillfeather.example/docs/ports-and-firewalls"
    verdict = bench.judge(case, answer, _prompt(case))
    assert verdict["correct"] is True
    assert verdict["outside_sources"] == ["link https://quillfeather.example/docs/ports-and-firewalls"]


def test_unanswerable_cases_are_passed_only_by_saying_so():
    case = _case("kestrel_price")
    prompt = _prompt(case)
    assert bench.judge(case, "The web results do not mention the price of the Kestrel K9.", prompt)["said_so"] is True
    assert bench.judge(case, "The Kestrel K9 costs $499.", prompt)["said_so"] is False
    assert bench.judge(case, "The results do not say, but it is usually around 450 dollars.", prompt)["said_so"] is False
    founder = _case("vellmar_founder")
    assert bench.judge(founder, "Vellmar Shipping was founded by Henrik Vellmar in 1887.", _prompt(founder))["said_so"] is False


def test_the_app_s_own_warning_is_not_judged_as_part_of_the_answer():
    case = _case("tidewater_version")
    answer = "The latest release is Tidewater 4.2." + "\n\n⚠️ Not found in the sources: 9.9. This may come from the model's older training data, so double-check it."
    verdict = bench.judge(case, answer, _prompt(case))
    assert verdict["correct"] and verdict["outside_sources"] == [] and verdict["app_warned"]


# ---- the app's own guard against invented links -------------------------------------------------


SOURCES = "[1] Docs\nURL: https://quillfeather.example/docs/sync-server\nSnippet: listens on port 8472. See https://quillfeather.example/changelog for changes."


@pytest.mark.parametrize(
    "answer",
    [
        "See https://quillfeather.example/docs/sync-server.",
        "See [the docs](https://quillfeather.example/docs/sync-server/).",
        "See https://quillfeather.example/docs/sync-server?utm_source=feed#ports",
        "Changes are listed at https://quillfeather.example/changelog, which the page links to.",
        "More on the project's site, https://quillfeather.example.",
        "The documentation is at https://quillfeather.example/docs/.",
        "It listens on port 8472.",
    ],
)
def test_links_that_were_retrieved_are_not_flagged(answer):
    assert web_research.unlisted_links(answer, SOURCES) == []
    assert web_research.unlisted_links_note(answer, SOURCES) == ""


def test_another_page_on_a_retrieved_site_is_still_flagged():
    assert web_research.unlisted_links("See https://quillfeather.example/docs/ports.", SOURCES) == ["https://quillfeather.example/docs/ports"]
    assert web_research.unlisted_links("See https://quillfeather.example/?page=secret.", SOURCES) == ["https://quillfeather.example/?page=secret"]
    assert web_research.unlisted_links("See https://quillfeather.example.evil.test/docs/.", SOURCES) == ["https://quillfeather.example.evil.test/docs/"]


def test_links_that_were_not_retrieved_are_flagged_once_each():
    answer = "Sources: https://quillfeather.example/docs/ports and https://example.org/guide. Again: https://example.org/guide."
    assert web_research.unlisted_links(answer, SOURCES) == ["https://quillfeather.example/docs/ports", "https://example.org/guide"]
    note = web_research.unlisted_links_note(answer, SOURCES)
    assert "Not among the pages that were retrieved" in note and "https://example.org/guide" in note


def test_a_research_summary_that_cites_an_invented_link_carries_the_warning():
    case = _case("quillfeather_port")
    results, pages = bench.as_search_results(case), bench.as_pages(case)
    made_up = "The server listens on port 8472.\n\nSource list:\n- https://quillfeather.example/docs/network-ports"
    text, generated = web_research.summarize_research_result(case["question"], results, pages, ai_callback=lambda prompt: made_up)
    assert generated
    assert "Not among the pages that were retrieved: https://quillfeather.example/docs/network-ports" in text
    honest = "The server listens on port 8472.\n\nSource list:\n- https://quillfeather.example/docs/sync-server"
    text, _generated = web_research.summarize_research_result(case["question"], results, pages, ai_callback=lambda prompt: honest)
    assert "Not among the pages" not in text


# ---- the saved live result ------------------------------------------------------------------------


def test_saved_live_answers_describe_the_prompts_the_app_builds_now():
    """If this fails the web-answer prompt changed: run tools/research_benchmark.py again with a real
    model and save the result, instead of editing the fingerprints or the counts."""

    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    chat = saved["chat_answers"]
    rows = {row["id"]: row for row in chat["rows"]}
    assert set(rows) == {case["id"] for case in CASES}
    for case in CASES:
        assert rows[case["id"]]["prompt"] == bench.prompt_fingerprint(_prompt(case)), case["id"]
    assert chat["answerable"] == len(ANSWERABLE) and chat["unanswerable"] == len(UNANSWERABLE)
    assert chat["correct"] == sum(rows[case["id"]]["correct"] for case in ANSWERABLE)
    assert chat["said_so"] == sum(rows[case["id"]]["said_so"] for case in UNANSWERABLE)
    # Re-judge the saved answers with the current judge: the counts must not depend on an old judge.
    for case in CASES:
        row = rows[case["id"]]
        again = bench.judge(case, row["answer"], _prompt(case))
        assert again["outside_sources"] == row["outside_sources"], case["id"]
        assert again.get("correct") == row.get("correct") and again.get("said_so") == row.get("said_so"), case["id"]


def test_release_gate_on_measured_answer_quality():
    """Floors from the measurement saved in docs/benchmarks/research_dolphin3-8b.json.

    Not a target: they are there so that a prompt or retrieval change which makes the real model's
    answers worse cannot be saved without someone noticing.
    """

    chat = json.loads(SAVED.read_text(encoding="utf-8"))["chat_answers"]
    assert chat["correct"] >= chat["answerable"] - 1
    assert chat["answers_with_something_outside_their_sources"] <= 2
