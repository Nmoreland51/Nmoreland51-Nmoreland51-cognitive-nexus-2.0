"""Reproduce and measure the owner's quality findings with the real model, before and after a change.

    python tools/quality_check.py --model dolphin3:8b --save docs/benchmarks/quality_after.json
    python tools/quality_check.py --root ../old-checkout --save docs/benchmarks/quality_before.json
    python tools/quality_check.py --model dolphin3:8b --only content arithmetic --trials 3

Cases are in tests/fixtures/quality_cases.json. Three parts:

content     the app's one content rule on each case, with the real model as its judge: the stage,
            the terms that made it look closer, and the judge's raw answers.
length      each request through the app's whole chat path with the app's default settings
            (the sidebar's defaults: throughput profile "Fast", Auto Precision on), recording the
            words written, why the model stopped, the token limit it was given, time to the first
            word and in total; and the same request sent straight to Ollama for comparison.
arithmetic  each question several times through the app, recording the answer, whether it is
            right, how long it took and what produced it (the model, or the app's calculator).

--root runs another checkout's code (for example the commit before a change) with this file's
cases, so before and after are measured on the same questions. Nothing here is a mock: every
answer comes from the model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
CASES = HERE / "tests" / "fixtures" / "quality_cases.json"
CHAT_DEFAULTS = {
    # What app.py's sidebar passes when nothing is changed.
    "throughput_mode": "fast",
    "target_tokens_per_second": 60,
    "generation_timeout": 600.0,
    "auto_precision_mode": True,
    "enable_response_self_critic": True,
    "response_mode": "auto",
    "verbosity_level": 2,
}
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
_NUMBER = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")


def words(text: str) -> int:
    return len(_WORD.findall(text or ""))


def ends_complete(text: str) -> bool:
    return bool(re.search(r"[.!?\"”’)*]\s*$", (text or "").strip()))


def answer_number(text: str) -> float | None:
    """The number an answer gives as its result: the last one ("7 times 6 equals 42" is 42)."""

    found = None
    for match in _NUMBER.finditer(text or ""):
        raw = match.group(0).replace("$", "").replace(",", "")
        try:
            found = float(raw)
        except ValueError:
            continue
    return found


def rescore(report: dict[str, Any]) -> dict[str, Any]:
    """Score saved arithmetic answers again with answer_number (the raw answers are kept, so this needs no model)."""

    for row in report.get("arithmetic") or []:
        row["value"] = answer_number(row["answer"])
        row["right"] = row["value"] is not None and abs(row["value"] - float(row["expected"])) < 1e-6
    report["summary"] = summarize(report)
    return report


def setup(root: Path) -> None:
    for folder in (root, root / "tools"):
        sys.path.insert(0, str(folder))


def chat_settings(model: str, url: str) -> dict[str, Any]:
    import behavior_check

    return {**behavior_check.chat_settings(model, url), **CHAT_DEFAULTS}


def run_content(cases: list[dict[str, Any]], model: str, url: str) -> list[dict[str, Any]]:
    import content_rule_benchmark as rule_bench

    from modules.behavior_policy import check_content_rule

    fixture = {case["id"]: case for rows in rule_bench.load_sets(HERE / "tests" / "fixtures" / "content_rule_benchmark.json").values() for case in rows}
    judge = rule_bench.model_judge(model, url)
    rows = []
    for case in cases:
        source = fixture[case["from_fixture"]] if case.get("from_fixture") else case
        answers: list[str] = []

        def recording(prompt: str) -> str:
            reply = judge(prompt)
            answers.append(reply.strip()[:30])
            return reply

        started = time.perf_counter()
        decision = check_content_rule(source["message"], source.get("recent", ""), recording, source.get("kind", "text"))
        did = "stop" if decision.blocked else "answer"
        rows.append(
            {
                "id": case["id"],
                "finding": case.get("finding", ""),
                "expect": case["expect"],
                "did": did,
                "right": did == case["expect"],
                "stage": decision.stage,
                "sexual_terms": list(decision.sexual_terms),
                "minor_terms": list(decision.minor_terms),
                "judge_answers": answers,
                "seconds": round(time.perf_counter() - started, 1),
                "used_earlier_turns": bool(source.get("recent")),
            }
        )
        print(f"content    {case['id']:<26} expect {case['expect']:<6} did {did:<6} stage {decision.stage:<18} judge {answers}", flush=True)
    return rows


def _direct(url: str, model: str, message: str, max_tokens: int = 2048) -> dict[str, Any]:
    import requests

    started = time.perf_counter()
    answer = requests.post(f"{url}/api/generate", json={"model": model, "prompt": message, "stream": False, "keep_alive": "24h", "options": {"num_predict": max_tokens, "num_ctx": 4096}}, timeout=1800).json()
    text = str(answer.get("response", ""))
    return {"words": words(text), "stopped_because": str(answer.get("done_reason", "")), "output_tokens": int(answer.get("eval_count") or 0), "seconds": round(time.perf_counter() - started, 1), "ends_complete": ends_complete(text)}


def run_length(cases: list[dict[str, Any]], model: str, url: str, direct: bool) -> list[dict[str, Any]]:
    from modules.nexus_core import NexusCore

    core = NexusCore()
    settings = chat_settings(model, url)
    rows = []
    for case in cases:
        started = time.perf_counter()
        first = None
        chunks: list[str] = []
        for chunk in core.stream_chat_response(case["message"], [], dict(settings)):
            if first is None and chunk.strip():
                first = time.perf_counter() - started
            chunks.append(chunk)
        total = time.perf_counter() - started
        text = "".join(chunks).strip()
        throughput = dict(getattr(core.provider_router, "_last_ollama_throughput", {}) or {})
        meta = dict(core.last_provider_result or {})
        row = {
            "id": case["id"],
            "low": case["low"],
            "high": case["high"],
            "words": words(text),
            "within": case["low"] <= words(text) <= case["high"],
            "ends_complete": ends_complete(text),
            "stopped_because": throughput.get("done_reason", ""),
            "output_tokens": throughput.get("eval_count", 0),
            "token_limit_sent": meta.get("planned_tokens") or meta.get("num_predict") or "",
            "window": throughput.get("num_ctx", ""),
            "first_word_seconds": round(first or total, 1),
            "total_seconds": round(total, 1),
            "provider": meta.get("provider", ""),
            "notes_shown": [line for line in text.splitlines() if line.startswith(("Stopped", "Note", "This answer", "The answer stopped", "Cut off"))][:3],
        }
        if direct:
            row["direct_ollama"] = _direct(url, model, case["message"])
        rows.append(row)
        print(
            f"length     {case['id']:<22} wanted {case['low']}-{case['high']:<4} got {row['words']:>4} words  within {str(row['within']):<5} complete {str(row['ends_complete']):<5} "
            f"stopped {row['stopped_because'] or '?':<6} tokens {row['output_tokens']:>4}  {row['total_seconds']:>6.1f}s"
            + (f"  | direct: {row['direct_ollama']['words']} words, {row['direct_ollama']['stopped_because']}, {row['direct_ollama']['seconds']}s" if direct else ""),
            flush=True,
        )
    return rows


def run_arithmetic(cases: list[dict[str, Any]], model: str, url: str, trials: int) -> list[dict[str, Any]]:
    from modules.nexus_core import NexusCore

    core = NexusCore()
    settings = chat_settings(model, url)
    rows = []
    for case in cases:
        for trial in range(1, trials + 1):
            started = time.perf_counter()
            answer = core.generate_chat_response(case["question"], list(case.get("recent", [])), dict(settings))
            value = answer_number(answer)
            right = value is not None and abs(value - float(case["answer"])) < 1e-6
            producer = str((core.last_provider_result or {}).get("provider", ""))
            rows.append({"id": case["id"], "trial": trial, "expected": case["answer"], "answer": answer[:200], "value": value, "right": right, "seconds": round(time.perf_counter() - started, 1), "produced_by": producer})
            print(f"arithmetic {case['id']:<20} trial {trial}  expected {case['answer']:<6} got {value!s:<8} right {str(right):<5} by {producer:<10} {rows[-1]['seconds']:>5.1f}s", flush=True)
    return rows


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    content = report.get("content") or []
    if content:
        answer_cases = [row for row in content if row["expect"] == "answer"]
        stop_cases = [row for row in content if row["expect"] == "stop"]
        summary["content"] = {
            "ordinary_wrongly_stopped": sum(row["did"] == "stop" for row in answer_cases),
            "ordinary": len(answer_cases),
            "covered_stopped": sum(row["did"] == "stop" for row in stop_cases),
            "covered": len(stop_cases),
            "wrong": [f"{row['id']}: {row['stage']}" for row in content if not row["right"]],
        }
    length = report.get("length") or []
    if length:
        summary["length"] = {
            "requests": len(length),
            "within_range": sum(row["within"] for row in length),
            "ended_complete": sum(row["ends_complete"] for row in length),
            "stopped_at_the_token_limit": sum(row["stopped_because"] == "length" for row in length),
            "median_seconds": sorted(row["total_seconds"] for row in length)[len(length) // 2],
        }
        direct = [row["direct_ollama"] for row in length if row.get("direct_ollama")]
        if direct:
            summary["length"]["direct_ollama_within_range"] = sum(row["low"] <= row["direct_ollama"]["words"] <= row["high"] for row in length if row.get("direct_ollama"))
    arithmetic = report.get("arithmetic") or []
    if arithmetic:
        summary["arithmetic"] = {
            "answers": len(arithmetic),
            "right": sum(row["right"] for row in arithmetic),
            "wrong": sorted({f"{row['id']} -> {row['value']}" for row in arithmetic if not row["right"]}),
            "by": {name: sum(row["produced_by"] == name for row in arithmetic) for name in sorted({row["produced_by"] for row in arithmetic})},
            "median_seconds": sorted(row["seconds"] for row in arithmetic)[len(arithmetic) // 2],
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--root", type=Path, default=HERE, help="the checkout whose code is measured (default: this one)")
    parser.add_argument("--only", nargs="+", choices=("content", "length", "arithmetic"), default=["content", "length", "arithmetic"])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--no-direct", action="store_true", help="do not send the length requests straight to Ollama as well")
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--rescore", type=Path, default=None, help="score a saved report again (no model needed) and write it back")
    args = parser.parse_args(argv)
    if args.rescore:
        report = rescore(json.loads(args.rescore.read_text(encoding="utf-8")))
        args.rescore.write_bytes((json.dumps(report, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(json.dumps(report["summary"], indent=1, ensure_ascii=False))
        return 0
    setup(args.root.resolve())
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    report: dict[str, Any] = {"measured_at": time.strftime("%Y-%m-%d %H:%M"), "model": args.model, "code": str(args.root.resolve()), "chat_settings": CHAT_DEFAULTS}
    try:
        import subprocess

        report["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=args.root, capture_output=True, text=True).stdout.strip()
        report["uncommitted_changes"] = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=args.root, capture_output=True, text=True).stdout.strip())
    except OSError:
        pass
    if "content" in args.only:
        report["content"] = run_content(cases["content"], args.model, args.ollama_url)
    if "arithmetic" in args.only:
        report["arithmetic"] = run_arithmetic(cases["arithmetic"], args.model, args.ollama_url, args.trials)
    if "length" in args.only:
        report["length"] = run_length(cases["length"], args.model, args.ollama_url, direct=not args.no_direct)
    report["summary"] = summarize(report)
    print(json.dumps(report["summary"], indent=1, ensure_ascii=False))
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(report, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
