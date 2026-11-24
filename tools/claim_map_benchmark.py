"""How well modules/claim_map.py finds the page that states each sentence of an answer (item 028).

    python tools/claim_map_benchmark.py                       # the dev set
    python tools/claim_map_benchmark.py --set heldout --save docs/benchmarks/claim_map.json

The sentences and their labels are in tests/fixtures/claim_map_cases.json, the pages in
tests/fixtures/research_benchmark.json. No model is involved, so the result is the same every run.

Counted per set: sentences a page states that were matched to that page; sentences no page states
that were reported as not found; and, separately, the worst mistake: a sentence no page states that
was matched to a page anyway, because that is a claim shown as backed when it is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.claim_map import COVERAGE, map_sentences  # noqa: E402

CASES = REPO_ROOT / "tests" / "fixtures" / "claim_map_cases.json"
PAGES = REPO_ROOT / "tests" / "fixtures" / "research_benchmark.json"


def evaluate(set_name: str) -> dict[str, Any]:
    labelled = json.loads(CASES.read_text(encoding="utf-8"))[set_name]
    pages = {case["id"]: case["results"] for case in json.loads(PAGES.read_text(encoding="utf-8"))["cases"]}
    rows = []
    for item in labelled:
        results = pages[item["case"]]
        mapped = map_sentences(item["text"], results)
        got = mapped[0] if mapped else None
        kind = got.kind if got else "nothing"
        label = item["source"]
        if label == "meta":
            right = kind in {"about the sources", "advice"}
            expected = "about the sources"
        elif label is None:
            right = kind == "not found"
            expected = "not found"
        else:
            right = kind == "stated" and got is not None and got.url == results[label]["url"]
            expected = results[label]["url"]
        rows.append(
            {
                "case": item["case"], "text": item["text"], "from": item["from"], "expected": expected, "right": right,
                "got": kind if kind != "stated" or got is None else got.url, "coverage": got.coverage if got else 0.0,
                "missing": got.missing if got else [],
            }
        )  # fmt: skip
    stated = [row for row, item in zip(rows, labelled) if isinstance(item["source"], int)]
    unsupported = [row for row, item in zip(rows, labelled) if item["source"] is None]
    meta = [row for row, item in zip(rows, labelled) if item["source"] == "meta"]
    return {
        "set": set_name,
        "coverage_threshold": COVERAGE,
        "stated_matched_to_the_right_page": sum(row["right"] for row in stated),
        "stated": len(stated),
        "unsupported_reported_as_not_found": sum(row["right"] for row in unsupported),
        "unsupported": len(unsupported),
        "unsupported_shown_as_stated": sum(row["got"] not in {"not found", "about the sources", "advice"} for row in unsupported),
        "about_the_sources_recognised": sum(row["right"] for row in meta),
        "about_the_sources": len(meta),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="dev", choices=("dev", "heldout"))
    parser.add_argument("--save", type=Path)
    parser.add_argument("--show", action="store_true", help="print every sentence that came out wrong")
    args = parser.parse_args(argv)
    result = evaluate(args.set)
    print(
        f"{args.set}: stated sentences matched to the right page {result['stated_matched_to_the_right_page']} of {result['stated']}; "
        f"unsupported reported as not found {result['unsupported_reported_as_not_found']} of {result['unsupported']} "
        f"(shown as stated: {result['unsupported_shown_as_stated']}); about the sources {result['about_the_sources_recognised']} of {result['about_the_sources']}"
    )
    if args.show:
        for row in result["rows"]:
            if not row["right"]:
                print(f"  WRONG [{row['case']}] {row['text']}\n        expected {row['expected']}; got {row['got']} (coverage {row['coverage']}, missing {row['missing']})")
    if args.save:
        saved = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else {}
        saved[args.set] = result
        args.save.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
