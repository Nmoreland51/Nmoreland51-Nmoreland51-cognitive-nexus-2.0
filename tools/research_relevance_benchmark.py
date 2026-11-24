"""Old against new on ambiguous local searches: which results reach the model?

    python tools/research_relevance_benchmark.py --model dolphin3:8b --save docs/benchmarks/research_relevance_dolphin3-8b.json
    python tools/research_relevance_benchmark.py --as-typed     # the old pipeline only, no model needed

For each question in tests/fixtures/research_relevance_benchmark.json:

old  the question's words are searched as typed and the first five results go to the model, which
     is what the app did before modules/research_plan.py.
new  the real model plans the search (what is meant, queries, words of other meanings), the plan's
     queries are searched in turn until enough relevant results are in hand, and off-topic
     results are dropped (modules/research_plan.gather_planned).

The search engine is simulated over a fixed pool of results per question, ranked by how many of
the query's words a result contains, so both pipelines see the same engine and the comparison can
be repeated. Measured: how many results about another meaning reach the model, what share of the
results are about what was asked, whether any is, and how many searches and seconds it took.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.research_plan import SearchPlan, gather_planned, plan_search  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "research_relevance_benchmark.json"
_STOP = {"the", "a", "an", "in", "of", "for", "to", "is", "what", "where", "can", "i", "how", "much", "and", "on", "best", "find", "search", "web", "get", "buy", "sold"}


def load() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _terms(text: str) -> set[str]:
    return {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STOP}


def simulated_search(pool: list[dict[str, Any]]):
    """A keyword search engine over a fixed pool: results ranked by how many query words they contain."""

    def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
        wanted = _terms(query)
        scored = []
        for position, item in enumerate(pool):
            text = _terms(f"{item['title']} {item['snippet']}")
            score = len(wanted & text)
            if score:
                scored.append((-score, position, item))
        return [dict(item) for _score, _position, item in sorted(scored)[:max_results]]

    return search


def score(sources: list[dict[str, Any]]) -> dict[str, Any]:
    asked = sum(item["about"] == "asked" for item in sources)
    other = sum(item["about"] == "other" for item in sources)
    return {"sources": len(sources), "about_what_was_asked": asked, "about_another_meaning": other, "share_relevant": round(asked / len(sources), 2) if sources else 0.0}


def run_case(case: dict[str, Any], planner) -> dict[str, Any]:
    search = simulated_search(case["pool"])
    old_sources = search(case["typed"], max_results=5)
    row: dict[str, Any] = {"id": case["id"], "set": case["set"], "question": case["question"], "old": {**score(old_sources), "titles": [item["title"] for item in old_sources]}}
    if planner is not None:
        started = time.perf_counter()
        plan: SearchPlan = planner(case["question"])
        planned_seconds = round(time.perf_counter() - started, 1)
        if plan.source != "model":
            plan.queries = [case["typed"]]
        started = time.perf_counter()
        outcome = gather_planned(plan, search, max_results=5)
        gathered_seconds = round(time.perf_counter() - started, 1)
        new_sources = outcome["results"]
        row["new"] = {
            **score(new_sources),
            "titles": [item["title"] for item in new_sources],
            "dropped": [f"{item['title']} ({item['relevance']['reason']})" for item in outcome["dropped"]],
            "dropped_wrongly": sum(item["about"] == "asked" for item in outcome["dropped"]),
            "searches": len(outcome["searches"]),
            "judged_by_model": sum(int(step.get("judged", 0)) for step in outcome["searches"]),
            "plan": plan.to_dict(),
            "plan_seconds": planned_seconds,
            "search_and_judge_seconds": gathered_seconds,
        }
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in sorted({row["set"] for row in rows}):
        mine = [row for row in rows if row["set"] == name]
        part: dict[str, Any] = {"questions": len(mine)}
        for side in ("old", "new"):
            have = [row[side] for row in mine if side in row]
            if not have:
                continue
            part[side] = {
                "results_about_another_meaning": sum(item["about_another_meaning"] for item in have),
                "results_about_what_was_asked": sum(item["about_what_was_asked"] for item in have),
                "mean_share_relevant": round(statistics.mean(item["share_relevant"] for item in have), 2),
                "questions_with_no_relevant_result": sum(item["about_what_was_asked"] == 0 for item in have),
            }
            if side == "new":
                part[side]["relevant_results_dropped"] = sum(item["dropped_wrongly"] for item in have)
                part[side]["searches"] = sum(item["searches"] for item in have)
                part[side]["results_judged_by_model"] = sum(item.get("judged_by_model", 0) for item in have)
                part[side]["median_plan_seconds"] = statistics.median(item["plan_seconds"] for item in have)
                part[side]["median_search_and_judge_seconds"] = statistics.median(item.get("search_and_judge_seconds", 0.0) for item in have)
        summary[name] = part
    return summary


def model_planner(model: str, url: str):
    from modules.provider_router import ProviderRequest, ProviderRouter
    from modules.research_plan import PLAN_OPTIONS

    router = ProviderRouter({"provider_order": ["ollama"], "ollama_url": url})

    def ask(prompt: str, schema: dict[str, Any]) -> str:
        request = ProviderRequest(prompt=prompt, model=model, provider_order=["ollama"], base_url=url, options=dict(PLAN_OPTIONS), max_tokens=int(PLAN_OPTIONS["num_predict"]), timeout=600.0, allow_cloud_fallback=False, response_schema=schema)
        return router.generate_or_raise(request).text

    return lambda question: plan_search(question, ask)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--as-typed", action="store_true", help="only the old pipeline (no model)")
    parser.add_argument("--sets", nargs="+", default=None, help="only these sets (dev, heldout, heldout2)")
    parser.add_argument("--save", type=Path, default=None)
    args = parser.parse_args(argv)
    planner = None if args.as_typed else model_planner(args.model, args.ollama_url.rstrip("/"))
    rows = []
    for case in load():
        if args.sets and case["set"] not in args.sets:
            continue
        row = run_case(case, planner)
        rows.append(row)
        line = f"{row['set']:<8} {row['id']:<16} old: {row['old']['about_another_meaning']} off-topic of {row['old']['sources']}"
        if "new" in row:
            line += (
                f"  new: {row['new']['about_another_meaning']} off-topic of {row['new']['sources']}, {row['new']['dropped_wrongly']} relevant dropped, "
                f"{row['new']['searches']} searches, {row['new']['judged_by_model']} judged, plan {row['new']['plan_seconds']}s, search and judge {row['new']['search_and_judge_seconds']}s"
            )
        print(line, flush=True)
    summary = summarize(rows)
    print(json.dumps(summary, indent=1))
    if args.save:
        report = {"measured_at": time.strftime("%Y-%m-%d"), "model": None if args.as_typed else args.model, "summary": summary, "rows": rows}
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(report, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
