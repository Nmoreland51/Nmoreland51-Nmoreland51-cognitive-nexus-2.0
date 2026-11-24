"""Which page states each sentence of a research answer (item 028): the rules, and the saved measurement."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modules.claim_map import answer_sentences, map_sentences, not_found_note, sources_from, summary
from ui.answer_diagnostics import sentence_rows

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import claim_map_benchmark  # noqa: E402

BRIDGE = [
    {"title": "Larkspur bridge repainting to begin in spring", "url": "https://news.example/repaint", "snippet": "", "text": "The council has approved a repainting of the Larkspur bridge. Work is expected to take five months and will close one lane at a time.", "retrieved_at": "2026-11-24T08:00:00+00:00"},
    {"title": "Larkspur bridge - history", "url": "https://history.example/bridge", "snippet": "", "text": "The Larkspur bridge opened to traffic in 1962 after four years of construction. The bridge carries four lanes and a footpath on each side.", "retrieved_at": "2026-11-24T08:00:05+00:00"},
]


def kinds(answer, sources=BRIDGE):
    return [(item.kind, item.url) for item in map_sentences(answer, sources)]


def test_the_sentences_of_an_answer_without_the_apps_notes_labels_and_source_list():
    answer = (
        "Direct answer: The bridge opened in 1962.\n\nKey findings:\n- It took four years to build. It carries four lanes.\n"
        "Source list:\n1. Larkspur bridge - history - https://history.example/bridge\n\n"
        "Note: none of the pages state when they were published.\n[About 20 words, fewer than asked.]"
    )
    assert answer_sentences(answer) == ["The bridge opened in 1962.", "It took four years to build.", "It carries four lanes."]


def test_a_sentence_is_matched_to_the_page_that_states_it_with_when_it_was_fetched():
    mapped = map_sentences("The Larkspur bridge opened to traffic in 1962.", BRIDGE)
    assert mapped[0].kind == "stated" and mapped[0].url == "https://history.example/bridge"
    assert mapped[0].retrieved_at == "2026-11-24T08:00:05+00:00"
    assert "opened to traffic in 1962" in mapped[0].passage


def test_a_figure_or_a_name_no_page_has_means_not_stated():
    assert kinds("The Larkspur bridge opened to traffic in 1926.") == [("not found", "")]
    assert map_sentences("The Larkspur bridge opened to traffic in 1926.", BRIDGE)[0].missing == ["1926"]
    assert kinds("The bridge carries six lanes.") == [("not found", "")]
    assert kinds("The Larkspur bridge was designed by Anna Holm.") == [("not found", "")]


def test_a_denial_does_not_count_as_stating_and_without_is_not_a_denial():
    sources = [{"title": "Sync server", "url": "https://q.example/sync", "text": "The sync server needs no database; it stores notes as files. It works without extra drivers."}]
    assert kinds("The sync server needs a database.", sources) == [("not found", "")]
    assert kinds("The sync server works with no extra drivers.", sources)[0][0] == "stated"


def test_a_sentence_joining_a_pages_title_and_text_is_found_on_that_page():
    assert kinds("The repainting of the Larkspur bridge is expected to begin in spring and take five months.") == [("stated", "https://news.example/repaint")]


def test_sentences_about_the_sources_and_advice_are_kept_apart():
    answer = "The web results do not say when the bridge was painted. However, they mention that the Larkspur bridge opened to traffic in 1962. Check the council's site for dates."
    assert [item.kind for item in map_sentences(answer, BRIDGE)] == ["about the sources", "stated", "advice"]


def test_results_and_fetched_pages_are_joined_by_address():
    results = [{"title": "History", "url": "https://history.example/bridge", "snippet": "Opened 1962.", "retrieved_at": "2026-11-24T08:00:00+00:00"}]
    pages = [
        {"url": "https://history.example/bridge", "title": "History", "text": "The bridge opened in 1962.", "retrieved_at": "2026-11-24T08:00:09+00:00"},
        {"url": "https://other.example/page", "title": "Other", "text": "Something else."},
    ]
    joined = sources_from(results, pages)
    assert joined[0]["text"] == "The bridge opened in 1962." and joined[0]["retrieved_at"] == "2026-11-24T08:00:09+00:00"
    assert [item["url"] for item in joined] == ["https://history.example/bridge", "https://other.example/page"]


def test_the_summary_and_the_note():
    mapped = map_sentences("The Larkspur bridge opened to traffic in 1962. The Larkspur bridge cost 9 million euros.", BRIDGE)
    assert summary(mapped) == {"stated": 1, "not found": 1, "about the sources": 0, "advice": 0}
    assert "9 million euros" in not_found_note(mapped) and not_found_note(mapped[:1]) == ""


def test_diagnostics_name_the_pages_but_never_quote_the_answer():
    secret = "The Larkspur bridge opened to traffic in 1962 after four years of construction."
    mapped = [item.to_dict() for item in map_sentences(secret + " The Larkspur bridge cost 9 million euros.", BRIDGE)]
    rows = sentence_rows(mapped)
    text = " ".join(row["Value"] for row in rows)
    assert rows[0] == {"What": "Sentences of the answer", "Value": "1 stated on a page read, 1 on no page read"}
    assert "Larkspur bridge - history" in text and "https://history.example/bridge" in text and "2026-11-24 08:00" in text
    assert secret not in text and "million euros" not in text
    assert sentence_rows([]) == []


def test_the_saved_measurement_is_what_the_rules_give_now():
    """docs/benchmarks/claim_map.json was made by tools/claim_map_benchmark.py; when the rules change,
    run it again for both sets (and say in the report that the held-out set has now been seen)."""

    saved = json.loads((REPO_ROOT / "docs" / "benchmarks" / "claim_map.json").read_text(encoding="utf-8"))
    for name in ("dev", "heldout"):
        now = claim_map_benchmark.evaluate(name)
        for key in ("stated_matched_to_the_right_page", "stated", "unsupported_reported_as_not_found", "unsupported", "unsupported_shown_as_stated"):
            assert now[key] == saved[name][key], f"{name} {key}: saved {saved[name][key]}, now {now[key]}; re-run tools/claim_map_benchmark.py"
