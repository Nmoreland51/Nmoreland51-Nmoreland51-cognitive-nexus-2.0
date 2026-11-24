"""The claim check on real web pages: common myths and plain facts (item 030).

    python tools/claim_check_real_pages.py fetch --set heldout              search once per claim, keep the pages
    python tools/claim_check_real_pages.py judge --set heldout              the wording rules, as the code is now
    python tools/claim_check_real_pages.py judge --set heldout --second-opinion --model dolphin3:8b
                                                                            also the model's second reading (what the app does)
    python tools/claim_check_real_pages.py judge --set heldout --save rules_after

The claims and their answers are in tests/fixtures/claim_check_real_claims.json. Pages are fetched
once with the app's own search and kept under data/benchmark_pages/ (not committed: they are other
people's text), so that versions of the rules are compared on the same pages. Saved runs go to
docs/benchmarks/claim_check_real_pages.json with verdicts and counts only.

A myth is right when called LIKELY FALSE or WEAKLY CONTRADICTED and acceptable when called anything
but LIKELY TRUE; a fact is right only when called LIKELY TRUE.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules import reality_research_agent as agent  # noqa: E402

try:
    from modules import retellings  # noqa: E402
except ImportError:  # run from a checkout made before the comparison by meaning existed
    retellings = None  # type: ignore[assignment]

CLAIMS = REPO_ROOT / "tests" / "fixtures" / "claim_check_real_claims.json"
PAGES = REPO_ROOT / "data" / "benchmark_pages"
RESULTS = REPO_ROOT / "docs" / "benchmarks" / "claim_check_real_pages.json"


def fetch(set_name: str) -> Path:
    from search.bloodhound_search import run_bloodhound_search

    saved = []
    for item in json.loads(CLAIMS.read_text(encoding="utf-8"))[set_name]:
        started = time.perf_counter()
        config = agent.default_bloodhound_config({"enabled": True, "depth": "Standard", "max_results": 25, "follow_links": False, "save_history": False})
        payload = run_bloodhound_search(item["claim"], config=config)
        sources = agent.dedupe_sources([agent.score_source_trust(result, item["claim"]) for result in payload.get("ranked_results", [])])[:25]
        saved.append({**item, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": [asdict(source) for source in sources]})
        print(f"{item['claim']}: {len(sources)} sources in {time.perf_counter() - started:.1f} s")
    PAGES.mkdir(parents=True, exist_ok=True)
    path = PAGES / f"claim_check_{set_name}.json"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    return path


def model_reader(model: str, url: str) -> Callable[[str], str]:
    from modules.provider_router import ProviderRequest, ProviderRouter

    router = ProviderRouter({"provider_order": ["ollama"], "ollama_url": url, "allow_cloud_fallback": False})

    def ask(prompt: str) -> str:
        # The same short answer the app asks for (NexusCore.run_reality_research).
        options = {"temperature": 0.0, "num_predict": 6, "num_ctx": 2048}
        request = ProviderRequest(
            prompt=prompt, model=model, provider_order=["ollama"], base_url=url, options=options, max_tokens=6, timeout=300.0, allow_cloud_fallback=False
        )
        return router.generate(request).text

    return ask


def judge(pages: list[dict[str, Any]], ask: Callable[[str], str] | None, ollama_url: str) -> list[dict[str, Any]]:
    fields = set(agent.SourceRecord.__dataclass_fields__)
    extra: dict[str, Any] = {}
    if retellings is not None and "meaning" in inspect.signature(agent.determine_verdict).parameters:
        extra["meaning"] = retellings.meaning_embedder(ollama_url)
    rows = []
    for item in pages:
        sources = [agent.SourceRecord(**{key: value for key, value in source.items() if key in fields}) for source in item["sources"]]
        claims = agent.extract_claim_records(sources)
        result = agent.determine_verdict(
            item["claim"], sources, claims, agent.detect_claim_contradictions(claims), verify=True, second_opinion=ask, **extra
        )
        verdict = result["verdict"]
        right = verdict == "LIKELY TRUE" if item["truth"] == "fact" else verdict in {"LIKELY FALSE", "WEAKLY CONTRADICTED"}
        rows.append(
            {
                "claim": item["claim"],
                "truth": item["truth"],
                "sources": len(sources),
                "verdict": verdict,
                "supporting": sum(entry.stance == "supports" for entry in result["evidence"]),
                "contradicting": sum(entry.stance == "contradicts" for entry in result["evidence"]),
                "retold": sum(repeat["why"].startswith("same story in other words") for repeat in result["repeats"]),
                "second_opinion": result["second_opinion"],
                "right": right,
                "acceptable": right or (item["truth"] == "myth" and verdict != "LIKELY TRUE"),
            }
        )
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "claims": len(rows),
        "right": sum(row["right"] for row in rows),
        "myths_called_likely_true": sum(row["truth"] == "myth" and row["verdict"] == "LIKELY TRUE" for row in rows),
        "facts_not_called_likely_true": sum(row["truth"] == "fact" and row["verdict"] != "LIKELY TRUE" for row in rows),
    }


def commit() -> str:
    try:
        described = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
        return described.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("fetch", "judge"))
    parser.add_argument("--set", choices=("dev", "heldout"), default="heldout")
    parser.add_argument("--second-opinion", action="store_true", help="also ask a model to re-read supporting passages, as the app does")
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--save", default="", help="name of the run to save in docs/benchmarks/claim_check_real_pages.json")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    if args.action == "fetch":
        print(f"saved {fetch(args.set)}")
        return 0
    path = PAGES / f"claim_check_{args.set}.json"
    if not path.exists():
        raise SystemExit(f"No saved pages for '{args.set}': run 'fetch --set {args.set}' first.")
    pages = json.loads(path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    rows = judge(pages, model_reader(args.model, args.ollama_url) if args.second_opinion else None, args.ollama_url)
    for row in rows:
        mark = "right" if row["right"] else "ok" if row["acceptable"] else "WRONG"
        print(f"{row['truth']:<5} {row['verdict']:<20} +{row['supporting']} -{row['contradicting']}  {mark:<5} {row['claim']}")
    totals = summary(rows)
    print(totals, f"{time.perf_counter() - started:.0f} s")
    if args.save:
        saved = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
        saved.setdefault(args.set, {})[args.save] = {
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "code": commit(),
            "pages_fetched_at": pages[0]["fetched_at"] if pages else "",
            "second_opinion_model": args.model if args.second_opinion else "",
            "summary": totals,
            "rows": rows,
        }
        RESULTS.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        print(f"saved {RESULTS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
