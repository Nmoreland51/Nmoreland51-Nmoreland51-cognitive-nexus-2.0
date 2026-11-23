"""The claim-stance rules: release gate over the labelled files, and the behaviours behind them.

Four files under tests/fixtures. The rules were developed against stance_benchmark.json and
stance_heldout_round1.json, so those must stay fully right. Rounds 2 and 3 were never used to
adjust the rules; their scores are the honest estimate and are gated only against getting worse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from modules import reality_research_agent as agent

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import stance_benchmark  # noqa: E402


def _items(name: str) -> list[dict[str, str]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["items"]


def _wrong(name: str) -> list[tuple[str, str, str, str]]:
    return [
        (item["label"], got, item["claim"], item["passage"])
        for item in _items(name)
        if (got := agent.stance_of(item["claim"], item["passage"])) != item["label"]
    ]


@pytest.mark.parametrize("name", ["stance_benchmark.json", "stance_heldout_round1.json"])
def test_development_sets_stay_fully_right(name):
    assert _wrong(name) == []


def test_held_out_round_has_not_got_worse():
    """38 of 47 right with 5 false "supports" when first measured (2026-11-23).

    A floor, not a target: do not adjust the rules to these items. If the rules change because of
    them, write a new held-out round and move this file to the development list above.
    """

    items = _items("stance_heldout_round2.json")
    wrong = _wrong("stance_heldout_round2.json")
    false_supports = [row for row in wrong if row[1] == "supports"]
    assert len(items) - len(wrong) >= 38, wrong
    assert len(false_supports) <= 5, false_supports


def test_third_held_out_round_has_not_got_worse():
    """23 of 30 right with 5 false "supports" on the rules alone when first measured (2026-11-23).

    A third of this round is passages that look like support and are not; the model's second
    reading (not run here) took the false supports from 5 to 3. Same rule as round 2: a floor.
    """

    wrong = _wrong("stance_heldout_round3.json")
    assert 30 - len(wrong) >= 23, wrong
    assert len([row for row in wrong if row[1] == "supports"]) <= 5
    assert [row for row in wrong if row[1] == "contradicts"] == []  # the rules claimed no contradiction that was not one


def test_saved_measurement_is_of_the_rules_and_prompt_the_app_has_now():
    """docs/benchmarks/stance.json holds what the real model said. It describes this code only while
    the rules score the same and the question put to the model is the same. If this fails, run
    tools/stance_benchmark.py --judge-model again and save the result."""

    saved = json.loads((REPO_ROOT / "docs" / "benchmarks" / "stance.json").read_text(encoding="utf-8"))
    assert saved["model"]["second_reading_prompt"] == stance_benchmark.second_reading_fingerprint()
    for name, path in stance_benchmark.FILES.items():
        now = stance_benchmark.score(json.loads(path.read_text(encoding="utf-8"))["items"], agent.stance_of)
        then = saved["rules"][name]
        assert (now["correct"], now["false_supports"], now["items"]) == (then["correct"], then["false_supports"], then["items"]), name
    for name in ("held_out", "held_out_round_3"):
        with_model = saved["rules_and_model"][name]["supporting_passages_only"]
        # The second reading can only take support away, so it cannot add a false one.
        assert with_model["false_supports"] <= saved["rules"][name]["false_supports"]
        assert with_model["false_contradicts"] == saved["rules"][name]["false_contradicts"]


def test_every_labelled_file_uses_the_three_labels_and_has_no_duplicates():
    seen: set[tuple[str, str]] = set()
    for name in ("stance_benchmark.json", "stance_heldout_round1.json", "stance_heldout_round2.json", "stance_heldout_round3.json"):
        for item in _items(name):
            assert item["label"] in {"supports", "contradicts", "mentions"}
            key = (item["claim"], item["passage"])
            assert key not in seen, f"{key} is in more than one file: a held-out item must not also be development data"
            seen.add(key)


# ---- numbers ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, amounts, years",
    [
        ("The bridge opened in 1962.", set(), {"1962"}),
        ("In 2020, the bridge closed.", set(), {"2020"}),
        ("It is 2000 metres long.", {2000.0}, set()),
        ("About 9.5 million people live there.", {9_500_000.0}, set()),
        ("A population of 9,500,000.", {9_500_000.0}, set()),
        ("The film won five awards.", {5.0}, set()),
        ("She wrote twenty-five books and twenty five plays.", {25.0}, set()),
        ("Three hundred thousand copies were sold.", {300_000.0}, set()),
        ("A million copies were sold.", {1_000_000.0}, set()),
        ("No one survived, and one of the boats sank.", set(), set()),
        ("Mars has one large moon.", {1.0}, set()),
        ("Vitamin B12 is needed.", set(), set()),
        ("It cost 1,999 dollars in 1999.", {1999.0}, {"1999"}),
    ],
)
def test_amounts_and_years_are_read_from_text(text, amounts, years):
    assert agent._numbers(text) == (amounts, years)


def test_the_same_figure_rounded_differently_is_not_a_contradiction():
    claim = "Mount Everest is 8,849 metres tall"
    assert agent.stance_of(claim, "Mount Everest is 8,848.86 metres tall.") == "supports"
    assert agent.stance_of(claim, "Mount Everest is 8,611 metres tall.") == "contradicts"


def test_a_figure_in_words_and_in_digits_is_the_same_figure():
    assert agent.stance_of("The city has 2 million residents", "The city has two million residents.") == "supports"
    assert agent.stance_of("The city has 2 million residents", "The city has five million residents.") == "contradicts"


def test_a_different_year_contradicts_only_what_happens_once():
    assert agent.stance_of("The bridge opened in 1975", "The bridge opened in 1962.") == "contradicts"
    assert agent.stance_of("The Tigers won the cup in 2024", "The Tigers won the cup in 2019.") == "mentions"


# ---- what a passage has to cover ----------------------------------------------------------------


def test_names_numbers_and_the_first_and_last_terms_must_be_covered():
    profile = agent._profile("The Great Barrier Reef is off the coast of Australia")
    assert profile.terms == ("great", "barrier", "reef", "off", "coast", "australia")
    assert profile.needed == 5
    assert profile.required == {"great", "barrier", "reef", "australia"}
    assert agent._profile("The stadium holds 54,000 spectators").needed == 4  # short claims: every term


def test_a_passage_about_someone_else_is_not_support():
    assert agent.stance_of("Shakespeare wrote Don Quixote", "Cervantes wrote Don Quixote.") == "mentions"
    assert agent.stance_of("Shakespeare wrote Don Quixote", "Cervantes wrote Don Quixote, while Shakespeare wrote Hamlet.") == "mentions"
    assert agent.stance_of("Unemployment rose last year", "Unemployment figures for last year were published on Monday.") == "mentions"


def test_words_spread_over_independent_clauses_do_not_address_the_claim():
    passage = "Berlin is the capital of Germany, while Paris is the capital of France."
    assert agent.stance_of("Paris is the capital of Germany", passage) == "mentions"
    assert agent.stance_of("Berlin is the capital of Germany", passage) == "supports"


# ---- negation, opposites, asides ----------------------------------------------------------------


def test_irregular_opposites_are_known_in_every_form():
    assert agent.stance_of("Unemployment rose last year", "Unemployment fell last year.") == "contradicts"
    assert agent.stance_of("Unemployment rose last year", "Unemployment has fallen since last year.") == "contradicts"
    assert agent.stance_of("Unemployment rose last year", "Unemployment did not fall last year; it rose.") == "supports"
    assert agent.stance_of("The team won the final", "The team lost the final.") == "contradicts"


def test_an_aside_about_something_else_is_not_a_negation_of_the_claim():
    passage = "Canberra, not Sydney, is the capital of Australia."
    assert agent.stance_of("The capital of Australia is Canberra", passage) == "supports"
    assert agent.stance_of("The capital of Australia is Sydney", passage) == "contradicts"
    assert agent.stance_of("The capital of Australia is Sydney", "The capital of Australia is Canberra rather than Sydney.") == "contradicts"
    assert agent.stance_of("The tower is 324 metres high", "The tower is 324 metres, not 300 metres, high.") == "supports"
    assert agent.stance_of("The tower is 300 metres high", "The tower is 324 metres, not 300 metres, high.") == "contradicts"


def test_set_aside_reports_whether_the_claim_s_own_version_was_rejected():
    terms = agent._claim_terms("The capital of Australia is Sydney")
    remaining, rejected = agent._set_aside("Canberra, not Sydney, is the capital of Australia.", terms)
    assert rejected and "Sydney" not in remaining and "Canberra" in remaining
    remaining, rejected = agent._set_aside("The mayor, not least because of the rain, stayed home.", terms)
    assert not rejected


def test_a_refutation_in_another_clause_counts_only_when_it_refers_back():
    assert agent.stance_of("The moon landing was staged", "Some say the moon landing was staged, but that has been debunked.") == "contradicts"
    assert agent.stance_of("The Earth is round", "The Earth is round, and the flat-earth idea is a myth.") == "supports"
    assert agent.stance_of("Bell invented the telephone", "Bell invented the telephone, and Edison did not.") == "supports"


# ---- passages that settle nothing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "claim, passage",
    [
        ("Chocolate causes acne", "Whether chocolate causes acne has long been debated."),
        ("The senator supports the bill", "It is unclear whether the senator supports the bill."),
        ("The senator supports the bill", "It is not yet known if the senator supports the bill."),
        ("The bridge will collapse", "Engineers say the bridge could collapse if it is not repaired."),
        ("The mayor attended the opening ceremony", "Critics claim the mayor did not attend the opening ceremony."),
        ("Unemployment rose last year", "Unemployment may have fallen last year."),
        ("The drug cures migraines", "The drug may cure migraines in some patients."),
        ("The actor is retiring", "Is the actor retiring?"),
    ],
)
def test_open_questions_hedges_and_reported_views_settle_nothing(claim, passage):
    assert agent.stance_of(claim, passage) == "mentions"


def test_an_outright_refutation_counts_even_when_the_claim_is_attributed_or_hedged():
    assert agent.stance_of("The moon landing was staged", "The claim that the moon landing was staged has been debunked many times.") == "contradicts"
    assert agent.stance_of("Vaccines cause autism", "The idea that vaccines could cause autism is a myth.") == "contradicts"


def test_an_open_question_stated_by_the_claim_itself_can_be_supported():
    claim = "It is unclear whether the senator supports the bill"
    assert agent.stance_of(claim, "It is unclear whether the senator supports the bill.") == "supports"


def test_the_caveat_says_what_the_rules_do_and_what_they_miss():
    assert "not by understanding" in agent.CLAIM_CHECK_CAVEAT
    assert "missed" in agent.CLAIM_CHECK_CAVEAT
