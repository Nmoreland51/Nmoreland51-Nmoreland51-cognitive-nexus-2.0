"""Planning a web search, judging what comes back, refining, and checking names (modules/research_plan.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from modules.research_plan import SearchPlan, as_typed, gather_planned, is_listing, judge_results, plan_search, unsourced_names, unsourced_names_note

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
    reply = json.dumps({"topic": "Cannabis in Omaha", "queries": ["cannabis dispensary Omaha", "cannabis dispensary Omaha", "Omaha menus"], "context_query": "", "off_topic": ["lawn", "weed", "Omaha", "best"], "wants": "menus with prices"})

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


# ---- round two: the plan as the real model writes it (no off-topic words), and the result judge ----


LAWN_PAGE = {"title": "Best 24 Weed Control Service in Omaha, NE", "snippet": "Lawn weed control and fertilization for Omaha homes.", "url": "https://lawn.example/omaha"}
SHOP_PAGE = {"title": "Riverside Green Dispensary menu", "snippet": "Medical cannabis dispensary near Omaha: menu and prices.", "url": "https://riversidegreen.example/menu"}
THREAD = {"title": "Where in Omaha is THCA sold? r/Omaha", "snippet": "Locals compare smoke shops that sell THCA flower.", "url": "https://forum.example/omaha-thca"}


def _as_the_model_plans(ask):
    """A plan like the real model's: the meaning spelled out, the off-topic list empty."""

    reply = json.dumps({"topic": "Find the best cannabis in Omaha.", "queries": ["best weed in Omaha", "best cannabis dispensary in Omaha"], "context_query": "", "off_topic": [], "wants": "shops with reviews"})
    return plan_search("Search the web for the best weed in Omaha.", lambda prompt, schema: reply if "work out what the person means" in prompt else ask(prompt, schema))


def test_queries_that_spell_the_meaning_out_are_searched_first():
    plan = _as_the_model_plans(lambda prompt, schema: "")
    assert plan.queries == ["best cannabis dispensary in Omaha", "best weed in Omaha"]


def test_the_prompts_own_example_words_are_not_taken_as_off_topic():
    reply = json.dumps({"topic": "Lizards for sale in Austin.", "queries": ["lizard pet shop Austin"], "context_query": "", "off_topic": ["snake", "reptile", "venom", "taxidermy"], "wants": "shops"})
    assert plan_search("Where can I buy a lizard in Austin?", lambda prompt, schema: reply).off_topic == ["taxidermy"]


def test_the_model_is_asked_only_about_results_that_name_none_of_the_meanings_words():
    asked = []

    def judge(prompt, schema):
        asked.append(prompt)
        lines = [line for line in prompt.splitlines() if line[:1].isdigit() and ". " in line]
        return json.dumps({"results": [{"about": "lawn weed control", "same": "no"} if "Lawn" in line else {"about": "THCA in Omaha", "same": "yes"} for line in lines]})

    plan = _as_the_model_plans(judge)
    outcome = gather_planned(plan, lambda query, max_results=5: [LAWN_PAGE, SHOP_PAGE, THREAD])

    assert len(asked) == 1 and "Lawn weed control" in asked[0] and "THCA" in asked[0] and "Riverside" not in asked[0]
    assert sorted(item["url"] for item in outcome["results"]) == sorted([SHOP_PAGE["url"], THREAD["url"]])
    assert outcome["dropped"][0]["relevance"]["reason"] == "judged by the model to be about something else (lawn weed control)"
    assert outcome["searches"][0] == {"query": "best cannabis dispensary in Omaha", "returned": 3, "kept": 2, "dropped": 1, "judged": 2, "judged_off_topic": 1}


@pytest.mark.parametrize("reply", ["not json", json.dumps({"results": [{"about": "x", "same": "maybe"}]}), json.dumps({"results": []})])
def test_a_judgement_that_cannot_be_used_keeps_the_results(reply):
    plan = _as_the_model_plans(lambda prompt, schema: reply)
    outcome = gather_planned(plan, lambda query, max_results=5: [LAWN_PAGE, SHOP_PAGE])

    assert len(outcome["results"]) == 2 and not outcome["dropped"]
    assert outcome["searches"][0]["judge"] == "unavailable: kept"


def test_every_result_is_judged_when_the_plan_adds_no_words_of_its_own():
    """Round two: for "a good gaming mouse" the model saw nothing ambiguous, and pest control got through."""

    calls = []

    def judge(prompt, schema):
        calls.append(prompt)
        lines = [line for line in prompt.splitlines() if line[:1].isdigit() and ". " in line]
        return json.dumps({"results": [{"about": "rodent control" if "Rat" in line else "gaming mice", "same": "no" if "Rat" in line else "yes"} for line in lines]})

    question = "Where can I buy a good gaming mouse in San Diego?"
    plan = SearchPlan(question=question, topic=question, queries=["gaming mouse San Diego"], ask=judge)
    found = [
        {"title": "Mouse and Rat Removal in San Diego", "snippet": "Humane mouse trapping.", "url": "https://pest.example/"},
        {"title": "Gaming mouse in stock, San Diego store", "snippet": "Try gaming mice before you buy.", "url": "https://shop.example/"},
    ]
    outcome = gather_planned(plan, lambda query, max_results=5: found)

    assert not plan.sense_words and len(calls) == 1 and "Rat Removal" in calls[0] and "Gaming mouse in stock" in calls[0]
    assert [item["url"] for item in outcome["results"]] == ["https://shop.example/"]


# ---- the owner's "check relevant legal and availability context" (CN-QA-006) -------------------------------


def test_the_plan_carries_a_search_for_the_law_or_availability_the_answer_depends_on():
    reply = {"topic": "Cannabis in Omaha.", "queries": ["cannabis dispensary Omaha"], "context_query": "Nebraska cannabis law 2026", "off_topic": [], "wants": "shops"}
    assert plan_search("best weed in Omaha", lambda prompt, schema: json.dumps(reply)).context_query == "Nebraska cannabis law 2026"
    for copied in ("Ohio fireworks law", "cannabis dispensary Omaha", ""):
        assert plan_search("best weed in Omaha", lambda prompt, schema: json.dumps({**reply, "context_query": copied})).context_query == ""


def test_the_context_search_is_made_even_when_the_first_search_was_enough_and_adds_at_most_two_results():
    searched = []
    law = [
        {"title": "Nebraska medical cannabis: what is legal in 2026", "snippet": "Recreational use remains illegal in Nebraska.", "url": "https://law.example/ne"},
        {"title": "Nebraska cannabis law explained", "snippet": "Possession limits in Nebraska.", "url": "https://law.example/limits"},
        {"title": "Cannabis law in Nebraska and Iowa", "snippet": "What changes across the river.", "url": "https://law.example/iowa"},
        {"title": "2025 in the United States - Wikipedia", "snippet": "Events of the year.", "url": "https://wiki.example/2025"},
    ]
    shops = [
        {"title": f"Cannabis dispensary {n}", "snippet": "Omaha cannabis menu", "url": f"https://shop{n}.example/"} for n in range(5)
    ]

    def search(query, max_results=5):
        searched.append(query)
        return law if "law" in query else shops

    plan = SearchPlan(question="best weed in Omaha", topic="Cannabis in Omaha.", queries=["cannabis dispensary Omaha", "Omaha cannabis menu"], context_query="Nebraska cannabis law 2026")
    outcome = gather_planned(plan, search)

    assert searched == ["cannabis dispensary Omaha", "Nebraska cannabis law 2026"]
    assert [item["url"] for item in outcome["results"]] == ["https://shop0.example/", "https://shop1.example/", "https://shop2.example/", "https://law.example/ne", "https://law.example/limits"]
    assert all(item["relevance"].get("context") for item in outcome["results"][3:])
    assert outcome["searches"][-1] == {"query": "Nebraska cannabis law 2026", "purpose": "law or availability", "returned": 4, "kept": 2, "dropped": 0}


def test_a_failing_context_search_is_recorded_and_the_rest_is_kept():
    def search(query, max_results=5):
        if "law" in query:
            raise RuntimeError("rate limited")
        return [{"title": "Cannabis dispensary", "snippet": "Omaha cannabis menu", "url": "https://shop.example/"}]

    plan = SearchPlan(question="best weed in Omaha", topic="Cannabis in Omaha.", queries=["cannabis dispensary Omaha"], context_query="Nebraska cannabis law")
    outcome = gather_planned(plan, search, min_relevant=1)

    assert [item["url"] for item in outcome["results"]] == ["https://shop.example/"]
    assert outcome["searches"][-1]["error"] == "rate limited" and outcome["searches"][-1]["purpose"] == "law or availability"


def test_a_plan_without_a_model_asks_nothing():
    plan = as_typed("best pizza in Chicago")
    outcome = gather_planned(plan, lambda query, max_results=5: [{"title": "Chicago pizza", "snippet": "deep dish", "url": "https://pizza.example/"}])
    assert len(outcome["results"]) == 1 and outcome["searches"][0] == {"query": "best pizza in Chicago", "returned": 1, "kept": 1, "dropped": 0}


@pytest.mark.parametrize("case_id", ["omaha_weed", "omaha_lawn_weeds"])
def test_the_benchmark_with_a_perfect_judge_keeps_only_the_meant_sense_for_either_meaning(case_id):
    """The plumbing, with the judge answering from the fixture's labels: either meaning of "weed"."""

    case = next(item for item in bench.load() if item["id"] == case_id)
    label = {item["title"]: item["about"] for item in case["pool"]}

    def judge(prompt, schema):
        lines = [line.split(". ", 1)[1] for line in prompt.splitlines() if line[:1].isdigit() and ". " in line]
        titles = [next(title for title in label if line.startswith(title)) for line in lines]
        return json.dumps({"results": [{"about": title, "same": "yes" if label[title] == "asked" else "no"} for title in titles]})

    topic = "Find the best cannabis in Omaha." if case_id == "omaha_weed" else "How do I remove weeds from my lawn in Omaha?"
    queries = ["best cannabis dispensary in Omaha"] if case_id == "omaha_weed" else ["weed removal services Omaha", "lawn care companies Omaha"]

    def planner(question):
        return SearchPlan(question=question, topic=topic, queries=queries, ask=judge)

    row = bench.run_case(case, planner)

    assert row["new"]["about_another_meaning"] == 0 and row["new"]["dropped_wrongly"] == 0 and row["new"]["about_what_was_asked"] >= 2


def test_the_benchmark_with_a_perfect_planner_drops_every_off_topic_result_and_keeps_the_rest():
    plans = {
        "omaha_weed": OMAHA,
    }

    def planner(question):
        case = next(item for item in bench.load() if item["question"] == question)
        return plans.get(case["id"]) or SearchPlan(question=question, topic=question, queries=[case["typed"]], off_topic=[], source="as_typed")

    row = bench.run_case(next(case for case in bench.load() if case["id"] == "omaha_weed"), planner)

    assert row["new"]["about_another_meaning"] == 0 and row["new"]["dropped_wrongly"] == 0 and row["new"]["about_what_was_asked"] >= 3
