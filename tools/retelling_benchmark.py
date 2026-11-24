"""Measure how well passages retold in other words are told apart from independent reports (item 030).

    python tools/retelling_benchmark.py --set dev            choose the threshold (the rule is in the fixture)
    python tools/retelling_benchmark.py --set heldout        run the held-out pairs once with modules/retellings.py's threshold
    python tools/retelling_benchmark.py --set dev --save     also write docs/benchmarks/retellings.json

Uses the real embedding model in Ollama (all-minilm); nothing is mocked. For comparison it also
shows the word-overlap measure the claim check already used for near-copies.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules import retellings  # noqa: E402
from modules.reality_research_agent import SourceRecord, _words, claim_evidence_breakdown  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "retelling_cases.json"
RESULTS = REPO_ROOT / "docs" / "benchmarks" / "retellings.json"
NEAR_COPY_OVERLAP = 0.8  # the claim check's existing rule for the same passage on another site


def word_overlap(a: str, b: str) -> float:
    left, right = set(_words(a)), set(_words(b))
    return len(left & right) / max(len(left | right), 1)


def measure(set_name: str) -> dict[str, Any]:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))[set_name]
    embed, model = retellings.meaning_embedder()
    if embed is None:
        raise SystemExit(f"Cannot measure: {model}.")
    texts = [text for case in cases for text in (case["a"], case["b"])]
    started = time.perf_counter()
    vectors = embed(texts)
    seconds = time.perf_counter() - started
    rows = []
    for number, case in enumerate(cases):
        rows.append(
            {
                "pair": number,
                "claim": case["claim"],
                "label": case["label"],
                "similarity": round(retellings.cosine(vectors[2 * number], vectors[2 * number + 1]), 4),
                "word_overlap": round(word_overlap(case["a"], case["b"]), 4),
            }
        )
    return {"model": model, "embed_seconds": round(seconds, 3), "texts": len(texts), "rows": rows, "cases": cases, "embed": embed}


def counted(case: dict[str, Any], embed: Any) -> int:
    """How many sources the claim check counts when the two passages come from two medium-trust sites."""

    sources = [
        SourceRecord(title=f"Page {side}", url=f"https://{side}.example/page", source=f"{side}.example", snippet=case[side], excerpt=case[side], trust_label="Medium")
        for side in ("a", "b")
    ]
    evidence = claim_evidence_breakdown(case["claim"], sources, embed=embed)["evidence"]
    return sum(item.stance != "mentions" for item in evidence)


def in_the_claim_check(cases: list[dict[str, Any]], embed: Any) -> dict[str, int]:
    """The pairs run through the claim check itself: where both passages were counted before, how often they still are."""

    result = {"retold_both_counted_before": 0, "retold_both_counted_after": 0, "independent_both_counted_before": 0, "independent_both_counted_after": 0}
    for case in cases:
        if counted(case, None) == 2:
            result[f"{case['label']}_both_counted_before"] += 1
            result[f"{case['label']}_both_counted_after"] += counted(case, embed) == 2
    return result


def outcome(rows: list[dict[str, Any]], threshold: float, key: str = "similarity") -> dict[str, int]:
    folded = [row for row in rows if row[key] >= threshold]
    return {
        "retold_folded": sum(row["label"] == "retold" for row in folded),
        "retold_total": sum(row["label"] == "retold" for row in rows),
        "independent_folded": sum(row["label"] == "independent" for row in folded),
        "independent_total": sum(row["label"] == "independent" for row in rows),
    }


def choose_threshold(rows: list[dict[str, Any]]) -> tuple[float, str]:
    """The rule written into the fixture before measuring."""

    retold = sorted(row["similarity"] for row in rows if row["label"] == "retold")
    independent = sorted(row["similarity"] for row in rows if row["label"] == "independent")
    if retold[0] > independent[-1]:
        return round((retold[0] + independent[-1]) / 2, 4), "separated: midpoint between the lowest retold and the highest independent pair"
    best: tuple[int, int, float] | None = None
    for candidate in sorted({row["similarity"] for row in rows}):
        result = outcome(rows, candidate)
        correct = result["retold_folded"] + (result["independent_total"] - result["independent_folded"])
        key = (correct, -result["independent_folded"], candidate)
        if best is None or key > best:
            best = key
    assert best is not None
    return best[2], "not separated: the threshold with the highest accuracy, ties broken towards fewer independent pairs folded"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)

    measured = measure(args.set)
    rows = measured["rows"]
    if args.set == "dev":
        threshold, how = choose_threshold(rows)
    else:
        threshold, how = retellings.RETELLING_SIMILARITY, "modules/retellings.RETELLING_SIMILARITY, chosen on the dev pairs"
    result = outcome(rows, threshold)
    near_copy = outcome(rows, NEAR_COPY_OVERLAP, key="word_overlap")
    check = in_the_claim_check(measured["cases"], measured["embed"]) if threshold == retellings.RETELLING_SIMILARITY else {}

    for row in sorted(rows, key=lambda row: row["similarity"]):
        mark = "folded" if row["similarity"] >= threshold else ""
        print(f"{row['similarity']:.3f}  overlap {row['word_overlap']:.2f}  {row['label']:<11} {mark:<7} {row['claim']}")
    print(f"\nmodel {measured['model']}; {measured['texts']} passages embedded in {measured['embed_seconds']} s")
    print(f"threshold {threshold} ({how})")
    print(
        f"meaning:      retold pairs folded {result['retold_folded']}/{result['retold_total']}, "
        f"independent pairs folded {result['independent_folded']}/{result['independent_total']}"
    )
    print(
        f"word overlap: retold pairs folded {near_copy['retold_folded']}/{near_copy['retold_total']}, "
        f"independent pairs folded {near_copy['independent_folded']}/{near_copy['independent_total']} (the existing near-copy rule, >= {NEAR_COPY_OVERLAP})"
    )
    if check:
        print(
            "in the claim check (two medium-trust sites): "
            f"retold pairs where both passages counted {check['retold_both_counted_before']} -> still both counted {check['retold_both_counted_after']}; "
            f"independent pairs where both counted {check['independent_both_counted_before']} -> still both counted {check['independent_both_counted_after']}"
        )

    if args.save:
        saved = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
        saved[args.set] = {
            "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}",
            "model": measured["model"],
            "embed_seconds": measured["embed_seconds"],
            "threshold": threshold,
            "how_chosen": how,
            "meaning": result,
            "word_overlap_rule": near_copy,
            "in_the_claim_check": check,
            "rows": rows,
        }
        RESULTS.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        print(f"saved {RESULTS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
