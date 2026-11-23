"""Measure research quality on frozen cases: ranking, passage selection, answers, faithfulness.

    python tools/research_benchmark.py                                   the parts that need no model
    python tools/research_benchmark.py --model dolphin3:8b               also real chat web answers
    python tools/research_benchmark.py --model dolphin3:8b --full 3      and three full research answers
    python tools/research_benchmark.py --model dolphin3:8b --save docs/benchmarks/research_dolphin3-8b.json

tests/fixtures/research_benchmark.json holds questions with the search results a search engine might
return, the text of each page, and which results answer the question. Nothing is fetched.

Without a model:
  ranking    does the app's result scoring put a page that answers the question first, and within
             the first two (the pages a chat web answer reads)?
  passages   does the excerpt taken from the answering page contain the answer?

With a model, each case goes through the app's own summarize_research_result:
  correct        the answer states the fact (answerable cases)
  said so        the answer says the sources do not contain it (unanswerable cases)
  outside        the answer states a version, year or link that is in none of its sources, or the
                 specific wrong thing a case lists; the app's own warning notes are counted too

A chat web answer takes about a quarter of a minute per case on a CPU-only machine, a full research
answer two to three minutes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules import web_research  # noqa: E402
from search import bloodhound_search  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "research_benchmark.json"
# Wording that counts as saying the sources do not contain the answer.
SAID_SO = re.compile(
    r"\b(?:do(?:es)? not|don't|doesn't|did not|didn't|no (?:information|mention|details?|data)|not (?:mention|specif|stat|provid|includ|contain|list|give|available|say)\w*"
    r"|unable to|cannot|can't|unknown|unclear|not clear)\b",
    re.IGNORECASE,
)


def load_cases(path: Path = FIXTURE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def as_search_results(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"title": item["title"], "url": item["url"], "snippet": item["snippet"], "source": web_research.get_domain(item["url"])}
        for item in case["results"]
    ]


def as_pages(case: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    """The pages as the scraper would return them. limit=2 is what a chat web answer reads."""

    return [
        {"success": True, "title": item["title"], "url": item["url"], "text": item["text"], "excerpt": item["text"][:1500], "published": ""}
        for item in case["results"][:limit]
    ]


def prompt_fingerprint(prompt: str) -> str:
    """Identifies the exact prompt a saved answer was measured with."""

    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def has_fact(case: dict[str, Any], text: str) -> bool:
    lowered = text.lower()
    wanted = [item.lower() for item in case.get("must_contain", [])]
    if not wanted:
        return False
    return any(item in lowered for item in wanted) if case.get("must_contain_any") else all(item in lowered for item in wanted)


# ---- without a model ---------------------------------------------------------------------------


def ranking(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Where the app's result scoring puts the first page that answers the question."""

    rows = []
    for case in cases:
        if not any(item["relevant"] for item in case["results"]):
            continue
        scored = [
            (bloodhound_search._score_result(result, case["question"], {"success": True, "text": item["text"]}).score, -index, item["relevant"])
            for index, (result, item) in enumerate(zip(as_search_results(case), case["results"]))
        ]
        order = [relevant for _score, _index, relevant in sorted(scored, reverse=True)]
        given = [item["relevant"] for item in case["results"]]
        rows.append({"id": case["id"], "rank": order.index(True) + 1, "rank_as_returned": given.index(True) + 1})
    count = len(rows)
    return {
        "cases": count,
        "answering_page_first": sum(row["rank"] == 1 for row in rows),
        "answering_page_in_first_two": sum(row["rank"] <= 2 for row in rows),
        "mean_reciprocal_rank": round(sum(1 / row["rank"] for row in rows) / count, 3),
        "as_returned_first": sum(row["rank_as_returned"] == 1 for row in rows),
        "as_returned_in_first_two": sum(row["rank_as_returned"] <= 2 for row in rows),
        "rows": rows,
    }


def passages(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the excerpt the chat prompt takes from an answering page contains the answer."""

    rows = []
    for case in cases:
        for item in case["results"]:
            if item["relevant"]:
                excerpt = web_research._relevant_excerpt(item["text"], case["question"])
                rows.append({"id": case["id"], "answer_in_excerpt": has_fact(case, excerpt), "excerpt_chars": len(excerpt)})
    return {"pages": len(rows), "answer_in_excerpt": sum(row["answer_in_excerpt"] for row in rows), "rows": rows}


# ---- with a model ------------------------------------------------------------------------------


def judge(case: dict[str, Any], answer: str, prompt: str) -> dict[str, Any]:
    """What the answer got right, and what it states that its sources do not."""

    # The app appends its own warnings after the model's text; judge the model's text.
    body = answer.split("\n\n⚠️", 1)[0]
    lowered = body.lower()
    outside: list[str] = [f"number {token}" for token in web_research.unsourced_numbers(body, prompt)]
    outside += [f"link {link}" for link in web_research.unlisted_links(body, prompt)]
    outside += [f"wrong: {item}" for item in case.get("must_not_contain", []) if item.lower() in lowered]
    if case.get("must_not_match") and re.search(case["must_not_match"], body, flags=re.IGNORECASE):
        outside.append("states the thing the sources do not contain")
    verdict: dict[str, Any] = {"outside_sources": outside, "app_warned": "⚠️" in answer}
    if case.get("unanswerable"):
        verdict["said_so"] = bool(SAID_SO.search(body)) and not outside
    else:
        verdict["correct"] = has_fact(case, body)
    return verdict


def answers(cases: list[dict[str, Any]], ask: Callable[[str, dict[str, Any]], str], *, brief: bool) -> dict[str, Any]:
    from modules.nexus_core import BRIEF_WEB_SUMMARY_OPTIONS, FULL_WEB_SUMMARY_OPTIONS

    options = BRIEF_WEB_SUMMARY_OPTIONS if brief else FULL_WEB_SUMMARY_OPTIONS
    rows = []
    for case in cases:
        results = as_search_results(case)
        pages = as_pages(case, web_research.BRIEF_MAX_PAGES if brief else None)
        prompt = web_research.build_summary_prompt(case["question"], results, pages, brief=brief)
        started = time.perf_counter()
        text, generated = web_research.summarize_research_result(
            case["question"], results, pages, ai_callback=lambda built: ask(built, options), brief=brief
        )
        if not generated:
            raise SystemExit(f"The model did not answer: {text}")
        row = {"id": case["id"], "unanswerable": bool(case.get("unanswerable")), **judge(case, text, prompt)}
        row.update({"seconds": round(time.perf_counter() - started, 1), "prompt": prompt_fingerprint(prompt), "answer": text})
        rows.append(row)
        outcome = ("said so" if row["said_so"] else "ANSWERED ANYWAY") if row["unanswerable"] else ("correct" if row["correct"] else "WRONG")
        print(f"{'chat' if brief else 'full':<5} {case['id']:<22} {outcome:<16} outside sources: {len(row['outside_sources'])}  {row['seconds']}s")
    answerable = [row for row in rows if not row["unanswerable"]]
    unanswerable = [row for row in rows if row["unanswerable"]]
    return {
        "answerable": len(answerable),
        "correct": sum(row["correct"] for row in answerable),
        "unanswerable": len(unanswerable),
        "said_so": sum(row["said_so"] for row in unanswerable),
        "answers_with_something_outside_their_sources": sum(bool(row["outside_sources"]) for row in rows),
        "of_those_the_app_warned_about": sum(bool(row["outside_sources"]) and row["app_warned"] for row in rows),
        "mean_seconds": round(sum(row["seconds"] for row in rows) / len(rows), 1) if rows else 0.0,
        "rows": rows,
    }


def model_asker(model: str, ollama_url: str) -> Callable[[str, dict[str, Any]], str]:
    from modules.provider_router import ProviderRequest, ProviderRouter

    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": ollama_url})

    def ask(prompt: str, options: dict[str, Any]) -> str:
        request = ProviderRequest(
            prompt=prompt,
            model=model,
            provider_order=["ollama", "fallback"],
            options=dict(options),
            max_tokens=int(options.get("num_predict", 256)),
        )
        return router.generate_or_raise(request).text

    return ask


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=None, help="Ollama model that writes the answers, for example dolphin3:8b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--full", type=int, default=0, metavar="N", help="also write N full research answers (slow)")
    parser.add_argument("--only", nargs="+", metavar="CASE", help="run only these case ids")
    parser.add_argument("--save", type=Path, default=None)
    args = parser.parse_args(argv)
    cases = [case for case in load_cases() if not args.only or case["id"] in args.only]
    report: dict[str, Any] = {"measured_at": time.strftime("%Y-%m-%d"), "ranking": ranking(cases), "passages": passages(cases)}
    rank, excerpt = report["ranking"], report["passages"]
    print(
        f"ranking: answering page first in {rank['answering_page_first']} of {rank['cases']} "
        f"(as returned by the search: {rank['as_returned_first']}), in the first two in {rank['answering_page_in_first_two']} "
        f"(as returned: {rank['as_returned_in_first_two']}), mean reciprocal rank {rank['mean_reciprocal_rank']}"
    )
    print(f"passages: the excerpt contains the answer for {excerpt['answer_in_excerpt']} of {excerpt['pages']} answering pages")
    if args.model:
        ask = model_asker(args.model, args.ollama_url)
        report["model"] = args.model
        for name, brief, chosen in (("chat_answers", True, cases), ("full_answers", False, cases[: args.full])):
            if not chosen:
                continue
            result = report[name] = answers(chosen, ask, brief=brief)
            print(
                f"{name}: correct {result['correct']} of {result['answerable']}; said the sources lack it "
                f"{result['said_so']} of {result['unanswerable']}; answers with something outside their sources "
                f"{result['answers_with_something_outside_their_sources']} of {len(result['rows'])} "
                f"(the app warned about {result['of_those_the_app_warned_about']}); {result['mean_seconds']} s each"
            )
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
