"""A story retold in other words on several sites counts once in a claim check (item 030).

The comparison by meaning is played here by stand-in vectors, so these tests show the counting
logic only. How well the real embedding model tells retellings from independent reports was
measured with tools/retelling_benchmark.py (docs/benchmarks/retellings.json), and
tests/test_live_ollama.py runs one retold and one independent pair through the real model.
"""

from __future__ import annotations

import pytest

from modules import reality_research_agent as agent
from modules import retellings

CLAIM = "verify that the bridge opened in 1962"
RETOLD = (
    "The bridge opened to traffic in 1962 after four years of construction.",
    "Built over four years, the bridge was opened in 1962.",
)
INDEPENDENT = "The bridge opened in 1962 and carried 20,000 cars a day by the end of the decade."


def source(url, text, trust="Medium"):
    return agent.SourceRecord(title=f"Page at {url}", url=url, source=agent.get_domain(url), snippet=text, excerpt=text, trust_label=trust)


def same_meaning(*groups):
    """Stand-in embedding: texts in the same group get the same vector, other groups orthogonal ones."""

    calls = []

    def embed(texts):
        calls.append(list(texts))
        vectors = []
        for text in texts:
            group = next(number for number, members in enumerate(groups) if text in members)
            vectors.append([1.0 if column == group else 0.0 for column in range(len(groups))])
        return vectors

    embed.calls = calls
    return embed


def verdict(sources, **kwargs):
    claims = agent.extract_claim_records(sources)
    return agent.determine_verdict(CLAIM, sources, claims, agent.detect_claim_contradictions(claims), **kwargs)


# ---- the fold itself ------------------------------------------------------------------------------


def test_a_passage_close_in_meaning_to_an_earlier_one_on_another_site_is_folded_into_it():
    embed = same_meaning(["a", "b"], ["c"])
    folds = retellings.fold_retellings(["a", "b", "c"], ["supports"] * 3, ["one.example", "two.example", "three.example"], embed)
    assert folds == [(1, 0, 1.0)]


def test_passages_on_opposite_sides_are_never_folded_however_close():
    # "It opened in 1962" and "it did not open in 1962" embed close together; they are not one story.
    embed = same_meaning(["a", "b"])
    assert retellings.fold_retellings(["a", "b"], ["supports", "contradicts"], ["one.example", "two.example"], embed) == []


def test_passages_that_only_mention_the_claim_are_not_compared():
    embed = same_meaning(["a", "b", "c"])
    assert retellings.fold_retellings(["a", "b", "c"], ["supports", "mentions", "mentions"], ["x", "y", "z"], embed) == []
    assert embed.calls == []  # one passage left to compare: nothing is sent to the model


def test_the_same_site_is_left_to_the_same_site_rule():
    embed = same_meaning(["a", "b"])
    assert retellings.fold_retellings(["a", "b"], ["supports", "supports"], ["one.example", "one.example"], embed) == []


def test_a_retelling_is_folded_into_the_passage_it_is_closest_to():
    vectors = {"first": [1.0, 0.0], "second": [0.0, 1.0], "retelling": [0.5, 0.866]}
    folds = retellings.fold_retellings(
        ["first", "second", "retelling"], ["supports"] * 3, ["a", "b", "c"], lambda texts: [vectors[text] for text in texts], threshold=0.4
    )
    assert folds == [(2, 1, 0.866)]


def test_only_the_measured_model_is_used():
    assert retellings.is_measured_model("all-minilm") and retellings.is_measured_model("all-minilm:latest")
    assert not retellings.is_measured_model("all-minilm:33m")  # a larger model, whose similarities were not measured
    assert not retellings.is_measured_model("nomic-embed-text:latest")


def test_without_the_model_the_reason_is_given_and_nothing_is_downloaded():
    embed, why = retellings.meaning_embedder()  # tests/conftest.py points Ollama at a closed port
    assert embed is None
    assert "all-minilm" in why and "not installed" in why


# ---- in the claim check ---------------------------------------------------------------------------


def test_two_medium_trust_sites_telling_one_story_in_other_words_no_longer_make_it_likely_true():
    sources = [source("https://one.example/a", RETOLD[0]), source("https://two.example/b", RETOLD[1])]
    before = verdict(sources)
    assert before["verdict"] == "LIKELY TRUE"  # counted as two independent sources

    after = verdict(sources, meaning=(same_meaning(list(RETOLD)), "all-minilm:latest"))
    assert after["verdict"] == "WEAKLY SUPPORTED"
    assert [item.url for item in after["evidence"]] == ["https://one.example/a"]
    assert after["repeats"] == [
        {"url": "https://two.example/b", "counted_as": "https://one.example/a", "why": "same story in other words, similarity 1.00,"}
    ]
    note = next(note for note in after["uncertainty"] if "in other words" in note)
    assert "one may be retelling the other" in note and "stronger than shown" in note
    assert after["compared_by_meaning"] is True


def test_independent_reports_with_details_of_their_own_still_count_twice():
    sources = [source("https://one.example/a", RETOLD[0]), source("https://two.example/b", INDEPENDENT)]
    result = verdict(sources, meaning=(same_meaning([RETOLD[0]], [INDEPENDENT]), "all-minilm:latest"))
    assert result["verdict"] == "LIKELY TRUE"
    assert len(result["evidence"]) == 2 and result["repeats"] == []


def test_the_report_lists_the_retelling_with_what_it_was_counted_as():
    sources = [source("https://one.example/a", RETOLD[0]), source("https://two.example/b", RETOLD[1])]
    result = verdict(sources, meaning=(same_meaning(list(RETOLD)), "all-minilm:latest"))
    report = agent.ResearchReport(
        query=CLAIM, timestamp="t", request={}, summary="", final_answer="", sources=sources, claims=[], contradictions=[],
        verdict=result["verdict"], repeated_sources=result["repeats"], uncertainty_notes=result["uncertainty"],
    )
    assert "- https://two.example/b (same story in other words, similarity 1.00, as https://one.example/a)" in report.to_markdown()


def test_when_the_model_is_missing_the_check_says_retellings_may_be_counted_twice():
    sources = [source("https://one.example/a", RETOLD[0]), source("https://two.example/b", RETOLD[1])]
    result = verdict(sources, meaning=(None, "the all-minilm embedding model is not installed"))
    assert result["verdict"] == "LIKELY TRUE"
    assert any(
        note.startswith("Passages were not compared by meaning (the all-minilm embedding model is not installed)") for note in result["uncertainty"]
    )


def test_when_the_model_fails_the_check_goes_on_and_says_so():
    def broken(texts):
        raise RuntimeError("connection refused")

    sources = [source("https://one.example/a", RETOLD[0]), source("https://two.example/b", RETOLD[1])]
    result = verdict(sources, meaning=(broken, "all-minilm:latest"))
    assert result["verdict"] == "LIKELY TRUE" and result["compared_by_meaning"] is False
    assert any("(the embedding model did not answer)" in note for note in result["uncertainty"])


def test_nothing_is_said_about_meaning_when_one_source_could_not_be_counted_twice_anyway():
    result = verdict([source("https://one.example/a", RETOLD[0])], meaning=(None, "not installed"))
    assert not any("compared by meaning" in note for note in result["uncertainty"])


@pytest.mark.parametrize("check, compare, asked", [(True, True, True), (True, False, False), (False, True, False)])
def test_the_model_is_only_looked_for_in_a_claim_check_that_wants_it(check, compare, asked):
    looked = []

    def embedder():
        looked.append(True)
        return None, "not installed"

    def search(query, **kwargs):
        return {"ranked_results": [{"title": "Page", "url": "https://one.example/a", "snippet": RETOLD[0], "excerpt": RETOLD[0], "match_strength": "High"}]}

    request = agent.ResearchRequest(
        query="the bridge opened in 1962", verify_claim=check, compare_meaning=compare, save_report=False, save_to_memory=False, use_ai_summary=False
    )
    agent.run_reality_research(request, settings={}, search_runner=search, meaning_embedder=embedder)
    assert bool(looked) is asked
