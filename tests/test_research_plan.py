"""Planning a web search, judging what comes back, refining, and checking names (modules/research_plan.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from modules.research_plan import SearchPlan, gather_planned, is_listing, judge_results, plan_search, unsourced_names, unsourced_names_note

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import research_relevance_benchmark as bench  # noqa: E402

OMAHA = SearchPlan(
    question="Search the web for the best weed in Omaha.",
    topic="The best cannabis dispensaries and products in Omaha, Nebraska.",
    queries=["best cannabis dispensary Omaha Nebraska", "Omaha cannabis menu prices", "Nebraska cannabis law 2026"],
    off_topic=["lawn", "weed control", "herbicide", "weed killer"],
)


def test_a_plan_is_read_from_the_models_reply_and_a_question_word_is_never_off_topic():
    reply = json.dumps({"topic": "Cannabis in Omaha", "queries": ["cannabis dispensary Omaha", "cannabis dispensary Omaha", "Omaha menus"], "off_topic": ["lawn", "weed", "Omaha", "best"], "wants": "menus with prices"})

    plan = plan_search("best weed in Omaha", lambda prompt, schema: reply)

    assert plan.source == "model" and plan.queries == ["cannabis dispensary Omaha", "Omaha menus"]  # repeated query dropped
    assert plan.off_topic == ["lawn"]  # "weed", "Omaha" and "best" are the question's own words
    assert {"cannabi", "dispensary", "menu"} <= plan.sense_words and "omaha" not in plan.sense_words


@pytest.mark.parametrize("reply", ["not json", json.dumps({"topic": "x"}), json.dumps({"topic": "x", "queries": [], "off_topic": [], "wants": ""})])
def test_without_a_usable_plan_the_question_is_searched_as_typed(reply):
    plan = plan_search("best weed in Omaha", lambda prompt, schema: reply)
    assert plan.source == "as_typed" and plan.queries == ["best weed in Omaha"] and plan.off_topic == []


def test_without_a_model_nothing_is_asked():
    assert plan_search("anything", None).note == "no model"


def test_results_about_another_meaning_are_dropped_and_listing_pages_go_last():
    pool = next(case for case in bench.load() if case["id"] == "omaha_weed")["pool"]

    kept, dropped = judge_results(OMAHA, pool)

    assert {item["about"] for item in dropped} == {"other"} and len(dropped) == 3
    assert all(item["about"] == "asked" for item in kept)
    assert kept[-1]["relevance"]["listing"] and not any(item["relevance"]["listing"] for item in kept[:-1])
    assert "lawn" in " ".join(dropped[0]["relevance"]["other_meaning"] + dropped[1]["relevance"]["other_meaning"])


def test_a_page_with_more_words_of_the_meaning_than_of_another_is_kept():
    page = {"title": "Cannabis dispensary opens next to a lawn care shop in Omaha", "snippet": "The Nebraska cannabis dispensary menu lists flower and edibles.", "url": "https://news.example/a"}
    kept, dropped = judge_results(OMAHA, [page])
    assert kept and not dropped


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        ("https://www.yelp.example/search?find_desc=pizza", "Pizza", True),
        ("https://contractors.example/search?service=crane", "Cranes", True),
        ("https://example.org/a", "Top 10 Best Cannabis Dispensaries in Omaha", True),
        ("https://riversidegreen.example/menu", "Riverside Green Dispensary: menu and prices", False),
    ],
)
def test_listing_pages_are_recognised(url, title, expected):
    assert is_listing({"url": url, "title": title}) is expected


def test_a_poor_first_search_is_refined_with_the_next_query():
    searched = []

    def search(query, max_results=5):
        searched.append(query)
        if query == OMAHA.queries[0]:
            return [{"title": "Weed control Omaha lawn service", "snippet": "lawn weed control", "url": "https://lawn.example/1"}]
        return [
            {"title": "Riverside Green Dispensary menu", "snippet": "cannabis menu and prices near Omaha", "url": "https://riversidegreen.example/menu"},
            {"title": "Omaha cannabis prices compared", "snippet": "cannabis dispensary menu prices", "url": "https://prices.example/omaha"},
        ]

    outcome = gather_planned(OMAHA, search)

    assert searched == OMAHA.queries[:2]  # the first gave nothing usable, the second was enough
    assert [item["url"] for item in outcome["results"]] == ["https://riversidegreen.example/menu", "https://prices.example/omaha"]
    assert outcome["searches"][0] == {"query": OMAHA.queries[0], "returned": 1, "kept": 0, "dropped": 1}
    assert len(outcome["dropped"]) == 1


def test_a_good_first_search_is_not_repeated_and_a_failing_search_does_not_end_the_research():
    calls = []

    def search(query, max_results=5):
        calls.append(query)
        if len(calls) == 1:
            raise RuntimeError("rate limited")
        return [{"title": f"Cannabis dispensary {n}", "snippet": "Omaha cannabis menu", "url": f"https://shop{n}.example/"} for n in range(3)]

    outcome = gather_planned(OMAHA, search)

    assert len(calls) == 2 and outcome["searches"][0]["error"] == "rate limited" and len(outcome["results"]) == 3


def test_names_the_sources_do_not_contain_are_listed():
    answer = "The best option is Green Light in Benson, which has a large menu. Omaha also has Riverside Green Dispensary. According to Yelp, prices vary."
    sources = "Riverside Green Dispensary in Omaha lists flower from $30. Yelp reviews."

    assert unsourced_names(answer, sources, "best weed in Omaha") == ["Green Light", "Benson"]
    assert unsourced_names_note(answer, sources).startswith("\n\nNot found in the sources above: Green Light, Benson")
    assert unsourced_names("Riverside Green Dispensary is in Omaha.", sources) == []
    assert unsourced_names_note("Nothing named here.", sources) == ""


def test_the_benchmark_scores_the_old_pipeline_without_a_model():
    rows = [bench.run_case(case, None) for case in bench.load()]

    omaha = next(row for row in rows if row["id"] == "omaha_weed")
    assert omaha["old"]["about_another_meaning"] == 3  # what the keyword search returns for the question as typed
    assert next(row for row in rows if row["id"] == "chicago_pizza")["old"]["about_another_meaning"] == 0  # the control has nothing to filter
    assert all("new" not in row for row in rows)


def test_the_benchmark_with_a_perfect_planner_drops_every_off_topic_result_and_keeps_the_rest():
    plans = {
        "omaha_weed": OMAHA,
    }

    def planner(question):
        case = next(item for item in bench.load() if item["question"] == question)
        return plans.get(case["id"]) or SearchPlan(question=question, topic=question, queries=[case["typed"]], off_topic=[], source="as_typed")

    row = bench.run_case(next(case for case in bench.load() if case["id"] == "omaha_weed"), planner)

    assert row["new"]["about_another_meaning"] == 0 and row["new"]["dropped_wrongly"] == 0 and row["new"]["about_what_was_asked"] >= 3
