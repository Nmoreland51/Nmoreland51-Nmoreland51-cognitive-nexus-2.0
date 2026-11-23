"""Measure how well a passage's stance towards a claim is judged.

    python tools/stance_benchmark.py                                  the rules in the app
    python tools/stance_benchmark.py --judge-model dolphin3:8b        also ask a local model, alone
                                                                      and as the app uses it
    python tools/stance_benchmark.py --save docs/benchmarks/stance.json

Three labelled files under tests/fixtures. The rules were developed against stance_benchmark.json
and, after its one honest run, stance_heldout_round1.json. stance_heldout_round2.json was written
afterwards and has never been used to adjust the rules: only its score is an honest estimate. The
worst mistake is a false "supports" (a passage counted as confirming a claim it does not
confirm), so those are counted separately.

stance_heldout_round3.json was written after the decision, taken on round 2's result, to ask the
model only about supporting passages; it is the honest estimate for the claim check as the app
runs it.

With --judge-model the held-out rounds are also scored for the model alone (asked about every
passage with the app's own prompt) and for the rules with the model's second reading: of every
passage the rules count for or against the claim (round 2 only, the design that was dropped), and
of supporting passages only (what the app does).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.reality_research_agent import read_opinion, second_opinion_prompt, stance_of  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures"
# The rules were developed against the first two; the last two were never used to adjust them.
FILES = {
    "development": FIXTURES / "stance_benchmark.json",
    "held_out_round_1": FIXTURES / "stance_heldout_round1.json",
    "held_out": FIXTURES / "stance_heldout_round2.json",
    "held_out_round_3": FIXTURES / "stance_heldout_round3.json",
}


def second_reading_fingerprint() -> str:
    """Identifies the question put to the model, so a saved result can be tied to the app's current prompt."""

    return hashlib.sha256(second_opinion_prompt("<claim>", "<passage>").encode("utf-8")).hexdigest()[:16]


def score(items: list[dict[str, Any]], judge: Callable[[str, str], str]) -> dict[str, Any]:
    by_type: dict[str, list[int]] = {}
    wrong = []
    false_supports = 0
    false_contradicts = 0
    for item in items:
        got = judge(item["claim"], item["passage"])
        tally = by_type.setdefault(item["type"], [0, 0])
        tally[1] += 1
        if got == item["label"]:
            tally[0] += 1
        else:
            wrong.append({"type": item["type"], "expected": item["label"], "got": got, "claim": item["claim"], "passage": item["passage"]})
            false_supports += got == "supports"
            false_contradicts += got == "contradicts"
    right = sum(tally[0] for tally in by_type.values())
    return {
        "items": len(items),
        "correct": right,
        "accuracy": round(right / len(items), 3),
        "false_supports": false_supports,
        "false_contradicts": false_contradicts,
        "by_type": {name: f"{tally[0]}/{tally[1]}" for name, tally in by_type.items()},
        "wrong": wrong,
    }


def model_judge(model: str, ollama_url: str) -> Callable[[str, str], str]:
    """Ask a real model with the prompt the app uses for its second reading. Answers are remembered,
    so scoring the model alone and together with the rules asks about each passage once."""

    from modules.provider_router import ProviderRequest, ProviderRouter

    router = ProviderRouter({"provider_order": ["ollama", "fallback"], "ollama_url": ollama_url})
    answers: dict[tuple[str, str], str] = {}

    def judge(claim: str, passage: str) -> str:
        if (claim, passage) not in answers:
            result = router.generate(
                ProviderRequest(
                    prompt=second_opinion_prompt(claim, passage),
                    model=model,
                    provider_order=["ollama", "fallback"],
                    options={"temperature": 0.0, "num_predict": 6, "num_ctx": 2048},
                    max_tokens=6,
                )
            )
            if not result.success:
                raise SystemExit(f"The model did not answer: {result.error}")
            # An answer that is none of the three words settles nothing.
            answers[(claim, passage)] = read_opinion(result.text) or "mentions"
        return answers[(claim, passage)]

    return judge


def together(model: Callable[[str, str], str], ask_about: tuple[str, ...] = ("supports",)) -> Callable[[str, str], str]:
    """The rules with the model's second reading of the passages they count as `ask_about`.

    ("supports",) is what apply_second_opinion does in the app. The model is never asked about a
    passage the rules class as "mentions": it can only take evidence away.
    """

    def judge(claim: str, passage: str) -> str:
        by_rules = stance_of(claim, passage)
        if by_rules not in ask_about:
            return by_rules
        return by_rules if model(claim, passage) == by_rules else "mentions"

    return judge


def show(name: str, result: dict[str, Any]) -> None:
    print(
        f"{name}: {result['correct']}/{result['items']} = {result['accuracy']:.0%}, "
        f"false supports: {result['false_supports']}, false contradictions: {result['false_contradicts']}"
    )
    for row in result["wrong"]:
        print(f"   wrong ({row['type']}): expected {row['expected']}, got {row['got']} | {row['claim']} || {row['passage']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--judge-model", default=None, help="also score an Ollama model (slow on CPU)")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--save", type=Path, default=None)
    args = parser.parse_args(argv)
    report: dict[str, Any] = {"measured_at": time.strftime("%Y-%m-%d"), "rules": {}}
    for name, path in FILES.items():
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        report["rules"][name] = score(items, stance_of)
        show(f"rules, {name}", report["rules"][name])
    if args.judge_model:
        model = model_judge(args.judge_model, args.ollama_url)
        report["model"] = {"name": args.judge_model, "second_reading_prompt": second_reading_fingerprint()}
        report["rules_and_model"] = {}
        for name in ("held_out", "held_out_round_3"):
            items = json.loads(FILES[name].read_text(encoding="utf-8"))["items"]
            started = time.perf_counter()
            alone = score(items, model)
            alone["seconds_per_item"] = round((time.perf_counter() - started) / len(items), 1)
            report["model"][name] = alone
            show(f"model {args.judge_model} alone, {name} ({alone['seconds_per_item']} s per passage)", alone)
            as_in_app = score(items, together(model))
            as_in_app["passages_the_model_was_asked_about"] = sum(stance_of(item["claim"], item["passage"]) == "supports" for item in items)
            report["rules_and_model"][name] = {"supporting_passages_only": as_in_app}
            show(f"rules, with the model's second reading of supporting passages (as the app does), {name}", as_in_app)
            if name == "held_out":
                every = score(items, together(model, ("supports", "contradicts")))
                report["rules_and_model"][name]["every_counted_passage"] = every
                show(f"rules, with the model's second reading of every counted passage (dropped design), {name}", every)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
