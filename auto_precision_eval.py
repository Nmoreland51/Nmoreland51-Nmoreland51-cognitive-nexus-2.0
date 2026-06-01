"""Planner-only evaluation for Cognitive Nexus Auto Precision Mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.response_planner import apply_auto_precision_settings, classify_request, plan_response


BASE_SETTINGS: dict[str, Any] = {
    "auto_precision_mode": True,
    "response_mode": "auto",
    "verbosity_level": 2,
    "reasoning_depth": 2,
    "provider_order": ["ollama", "fallback"],
    "selected_model": "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
    "max_context_chars": 12000,
    "staged_streaming": True,
}


@dataclass(frozen=True)
class EvalCase:
    prompt: str
    expected_types: set[str]
    expected_modes: set[str]
    memory: bool | None = None
    research: bool | None = None
    diagnostics: bool | None = None


CASES = [
    EvalCase("What is Cognitive Nexus?", {"simple_fact"}, {"short"}, memory=False, research=False, diagnostics=False),
    EvalCase("Is 65 bpm a lot?", {"simple_fact"}, {"short"}, memory=False, research=False, diagnostics=False),
    EvalCase(
        "Fix this import error: ModuleNotFoundError: core.model",
        {"debugging", "coding_help"},
        {"surgeon"},
        memory=True,
        research=False,
        diagnostics=True,
    ),
    EvalCase("Why is my Streamlit app slow?", {"troubleshooting", "debugging"}, {"surgeon"}, memory=True, research=False, diagnostics=True),
    EvalCase("Research whether this claim is true", {"research", "reality_check"}, {"research"}, memory=True, research=True),
    EvalCase("Rate my AI compared to ChatGPT", {"opinion_rating"}, {"standard"}, memory=False, research=False, diagnostics=False),
    EvalCase("Make me a plan to improve this project", {"project_planning"}, {"deep"}, memory=True, research=False, diagnostics=False),
    EvalCase("Write a short website headline", {"creative"}, {"deep"}, memory=False, research=False, diagnostics=False),
    EvalCase("Remember that Ollama is my default provider", {"file_or_memory_lookup"}, {"standard"}, memory=True, research=False),
    EvalCase("What broke in my last test run?", {"debugging", "troubleshooting"}, {"surgeon"}, memory=True, research=False, diagnostics=True),
]


def evaluate_case(case: EvalCase) -> dict[str, Any]:
    classification = classify_request(case.prompt)
    request_type = str(classification["request_type"])
    effective_settings = apply_auto_precision_settings(BASE_SETTINGS, request_type)
    plan = plan_response(
        user_message=case.prompt,
        messages=[],
        route_category="standard_conversation",
        settings=BASE_SETTINGS,
    )
    correct = plan.intent in case.expected_types and plan.mode in case.expected_modes
    if case.memory is not None:
        correct = correct and bool(effective_settings.get("use_memory")) is case.memory
    if case.research is not None:
        correct = correct and bool(effective_settings.get("use_web_for_chat")) is case.research
    if case.diagnostics is not None:
        correct = correct and bool(effective_settings.get("show_perf_timings")) is case.diagnostics

    return {
        "prompt": case.prompt,
        "request_type": plan.intent,
        "mode": plan.mode,
        "verbosity": plan.diagnostics.get("verbosity"),
        "reasoning_depth": plan.diagnostics.get("reasoning_depth"),
        "memory": bool(effective_settings.get("use_memory")),
        "research": bool(effective_settings.get("use_web_for_chat")),
        "diagnostics": bool(effective_settings.get("show_perf_timings")),
        "looks_correct": "PASS" if correct else "REVIEW",
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = [
        ("Prompt", "prompt", 42),
        ("Type", "request_type", 22),
        ("Mode", "mode", 10),
        ("Verb", "verbosity", 6),
        ("Depth", "reasoning_depth", 6),
        ("Memory", "memory", 8),
        ("Research", "research", 9),
        ("Diag", "diagnostics", 6),
        ("Check", "looks_correct", 7),
    ]
    header = " | ".join(label.ljust(width) for label, _, width in columns)
    separator = "-+-".join("-" * width for _, _, width in columns)
    print(header)
    print(separator)
    for row in rows:
        values = []
        for _, key, width in columns:
            value = str(row[key])
            if len(value) > width:
                value = value[: width - 3] + "..."
            values.append(value.ljust(width))
        print(" | ".join(values))


def main() -> int:
    rows = [evaluate_case(case) for case in CASES]
    print_table(rows)
    failed = [row for row in rows if row["looks_correct"] != "PASS"]
    if failed:
        print(f"\nAuto Precision eval needs review: {len(failed)} case(s).")
        return 1
    print("\nAuto Precision eval passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
