"""Measure knowledge search on a fixed set of documents and questions.

    python tools/retrieval_benchmark.py                    use the backend the app would use
    python tools/retrieval_benchmark.py --backend hash     word-hash vectors (no model)
    python tools/retrieval_benchmark.py --backend ollama --model all-minilm
    python tools/retrieval_benchmark.py --save docs/benchmarks/retrieval.json

For each search mode (keyword only, vectors only, both combined) it reports, per kind of
question, how often the right document was first (hit@1) or in the first three (hit@3), and for
questions that have no answer in the set, how often nothing was returned. It also prints the
similarity scores that separate right answers from wrong ones, which is how the cut-off in
modules/knowledge_store.py (SEMANTIC_FLOOR) is chosen.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.embeddings import Embedder, choose_embedder  # noqa: E402
from modules.knowledge_store import KnowledgeStore  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "retrieval_benchmark.json"
MODES = ("keyword", "vector", "hybrid")


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_benchmark(
    embedder: Embedder, fixture: dict[str, Any] | None = None, *, top_k: int = 3, min_confidence: str = "low"
) -> dict[str, Any]:
    """Index the fixture's documents in a temporary store and score every search mode.

    min_confidence "low" is an explicit search; "medium" is what the chat puts into a prompt unasked.
    """

    fixture = fixture or load_fixture()
    with tempfile.TemporaryDirectory() as folder:
        store = KnowledgeStore(Path(folder) / "kb", embedder=embedder)
        started = time.perf_counter()
        for document in fixture["documents"]:
            store.add_document(f"bench:{document['id']}", document["title"], document["text"], kind=document.get("kind", "file"))
        index_seconds = time.perf_counter() - started
        by_source = {f"bench:{document['id']}": document["id"] for document in fixture["documents"]}
        results: dict[str, Any] = {
            "backend": embedder.name,
            "semantic": embedder.semantic,
            "min_confidence": min_confidence,
            "documents": len(fixture["documents"]),
            "index_seconds": round(index_seconds, 2),
            "modes": {},
        }
        right_scores: list[float] = []
        wrong_scores: list[float] = []
        for mode in MODES:
            groups: dict[str, dict[str, float]] = {}
            search_seconds = 0.0
            for query in fixture["queries"]:
                started = time.perf_counter()
                found = store.search(query["q"], top_k=top_k, mode=mode, min_confidence=min_confidence)
                search_seconds += time.perf_counter() - started
                ids = [by_source[item["url"]] for item in found]
                group = groups.setdefault(query["type"], {"count": 0, "hit1": 0, "hit3": 0, "reciprocal": 0.0, "empty": 0})
                group["count"] += 1
                if query["doc"] is None:
                    group["empty"] += 1 if not ids else 0
                    if mode == "vector" and found:
                        wrong_scores.append(found[0]["vector_score"])
                    continue
                if ids[:1] == [query["doc"]]:
                    group["hit1"] += 1
                if query["doc"] in ids:
                    group["hit3"] += 1
                    group["reciprocal"] += 1.0 / (ids.index(query["doc"]) + 1)
                if mode == "vector":
                    for item in found:
                        (right_scores if by_source[item["url"]] == query["doc"] else wrong_scores).append(item["vector_score"])
            summary: dict[str, Any] = {}
            answerable = {"count": 0, "hit1": 0.0, "hit3": 0.0, "reciprocal": 0.0}
            for name, group in groups.items():
                count = group["count"]
                if name == "unanswerable":
                    summary[name] = {"count": count, "returned_nothing": round(group["empty"] / count, 3)}
                    continue
                summary[name] = {
                    "count": count,
                    "hit@1": round(group["hit1"] / count, 3),
                    "hit@3": round(group["hit3"] / count, 3),
                    "mrr": round(group["reciprocal"] / count, 3),
                }
                for key in ("count", "hit1", "hit3", "reciprocal"):
                    answerable[key] += group[key]
            total = answerable["count"] or 1
            summary["all_answerable"] = {
                "count": int(answerable["count"]),
                "hit@1": round(answerable["hit1"] / total, 3),
                "hit@3": round(answerable["hit3"] / total, 3),
                "mrr": round(answerable["reciprocal"] / total, 3),
            }
            summary["search_ms_per_query"] = round(1000 * search_seconds / len(fixture["queries"]), 1)
            results["modes"][mode] = summary
        results["vector_scores"] = {
            "right_min": round(min(right_scores), 3) if right_scores else None,
            "right_median": round(sorted(right_scores)[len(right_scores) // 2], 3) if right_scores else None,
            "wrong_max": round(max(wrong_scores), 3) if wrong_scores else None,
            "wrong_median": round(sorted(wrong_scores)[len(wrong_scores) // 2], 3) if wrong_scores else None,
            "floor_in_use": store.semantic_floor() if embedder.semantic else None,
        }
        store.close()
    return results


def format_results(results: dict[str, Any]) -> str:
    lines = [
        f"backend: {results['backend']}  ({results['documents']} documents indexed in {results['index_seconds']} s), "
        f"minimum confidence: {results.get('min_confidence', 'low')}"
    ]
    lines.append(f"{'mode':<9}{'question type':<16}{'n':>4}{'hit@1':>8}{'hit@3':>8}{'mrr':>8}")
    for mode, summary in results["modes"].items():
        for name, row in summary.items():
            if name == "search_ms_per_query":
                continue
            if "returned_nothing" in row:
                lines.append(f"{mode:<9}{name:<16}{row['count']:>4}   returned nothing for {row['returned_nothing']:.0%}")
            else:
                lines.append(f"{mode:<9}{name:<16}{row['count']:>4}{row['hit@1']:>8.0%}{row['hit@3']:>8.0%}{row['mrr']:>8.2f}")
        lines.append(f"{mode:<9}{'':<16}      {summary['search_ms_per_query']} ms per question")
    scores = results["vector_scores"]
    if scores["right_min"] is not None:
        lines.append(
            f"similarity of right answers: lowest {scores['right_min']}, median {scores['right_median']}; "
            f"of wrong ones: highest {scores['wrong_max']}, median {scores['wrong_median']}; cut-off in use: {scores['floor_in_use']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", default=None, help="auto (default), hash, ollama or sentence_transformers")
    parser.add_argument("--model", default=None, help="embedding model name for the chosen backend")
    parser.add_argument("--ollama-url", default=None)
    parser.add_argument("--save", type=Path, default=None, help="write the results as JSON to this file")
    args = parser.parse_args(argv)
    embedder, status = choose_embedder(args.backend, args.model, ollama_url=args.ollama_url)
    print(status["message"])
    runs: list[dict[str, Any]] = []
    saved: dict[str, Any] = {"measured_at": time.strftime("%Y-%m-%d"), "runs": runs}
    for confidence in ("low", "medium"):
        results = run_benchmark(embedder, min_confidence=confidence)
        print(format_results(results))
        print()
        runs.append(results)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(saved, indent=2) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
