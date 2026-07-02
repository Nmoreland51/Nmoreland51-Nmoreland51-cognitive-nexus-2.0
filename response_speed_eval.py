"""Speed evaluation for normal Cognitive Nexus chat turns."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any

from modules.chat_profile import ChatProfile
from modules.nexus_core import NexusCore
from modules.response_planner import apply_auto_precision_settings, classify_request, plan_response
from nexus_router import RouterConfig, route_message


PROMPTS = [
    "sup",
    "hello",
    "What is Cognitive Nexus?",
    "Is 65 bpm a lot?",
    "Explain Ollama in one paragraph.",
    "What should I do next with this repo?",
    "Fix this import error: ModuleNotFoundError: core.model",
]

BASE_SETTINGS: dict[str, Any] = {
    "chat_profile": ChatProfile(enabled=False),
    "router_config": RouterConfig(default_model="", enabled=True),
    "auto_precision_mode": True,
    "response_mode": "auto",
    "provider_order": ["ollama"],
    "selected_model": "",
    "base_url": "http://localhost:11434",
    "use_memory": False,
    "use_knowledge_for_chat": False,
    "use_web_for_chat": False,
    "show_sources": False,
    "generation_timeout": 45.0,
    "max_context_chars": 12000,
    "recent_message_limit": 4,
    "knowledge_top_k": 3,
    "enable_reality_grounding": False,
    "enable_reality_first_reasoning": False,
    "enable_reality_research_agent": False,
    "enable_bloodhound_search": False,
    "staged_streaming": False,
}


@dataclass(frozen=True)
class SpeedTarget:
    name: str
    seconds: float


def target_for(request_type: str, mode: str) -> SpeedTarget:
    if request_type in {"casual_chat", "simple_fact"}:
        return SpeedTarget("normal-fast", 9.0)
    if request_type in {"debugging", "troubleshooting", "project_planning"}:
        return SpeedTarget("technical-normal", 15.0)
    if mode in {"research", "deep"}:
        return SpeedTarget("deep-or-research", 45.0)
    return SpeedTarget("standard-normal", 15.0)


def plan_for_prompt(prompt: str) -> tuple[Any, dict[str, Any], str]:
    router_config = RouterConfig(default_model="", enabled=True)
    route = route_message(prompt, router_config)
    classification = classify_request(prompt)
    effective = apply_auto_precision_settings(BASE_SETTINGS, str(classification["request_type"]), route_category=route.category)
    plan = plan_response(
        user_message=prompt,
        messages=[],
        route_category=route.category,
        route_reason=route.reason,
        settings=BASE_SETTINGS,
    )
    return plan, effective, route.category


def evaluate_prompt(prompt: str, *, dry_run: bool, core: NexusCore | None = None) -> dict[str, Any]:
    plan, effective, _route_category = plan_for_prompt(prompt)
    target = target_for(plan.intent, plan.mode)
    provider = "dry_run"
    answer = ""
    elapsed = 0.0
    timing_trace: dict[str, Any] = {}

    if dry_run:
        provider = "dry_run"
        answer = "[dry run] Planner/profile evaluated without model text."
    else:
        assert core is not None
        settings = dict(BASE_SETTINGS)
        started = time.perf_counter()
        answer = core.generate_chat_response(prompt, [], settings)
        elapsed = time.perf_counter() - started
        provider_meta = dict(core.last_provider_result or {})
        provider = str(provider_meta.get("provider") or "unknown")
        timing_trace = dict(provider_meta.get("timings") or {})
        live_plan = dict(core.last_response_plan or {})
        if live_plan:
            plan.intent = str(live_plan.get("intent") or plan.intent)
            plan.mode = str(live_plan.get("mode") or plan.mode)
            target = target_for(plan.intent, plan.mode)
        if timing_trace.get("total_ms"):
            elapsed = float(timing_trace["total_ms"]) / 1000.0

    passed = dry_run or elapsed <= target.seconds
    return {
        "prompt": prompt,
        "request_type": plan.intent,
        "mode": plan.mode,
        "provider": provider,
        "seconds": round(elapsed, 3),
        "length": len(answer),
        "target": f"{target.seconds:.0f}s",
        "check": "PASS" if passed else "FAIL",
        "first_token_ms": timing_trace.get("provider_first_token_ms", "n/a"),
        "provider_ms": timing_trace.get("provider_total_ms", "n/a"),
        "context_ms": timing_trace.get("context_ms", "n/a"),
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = [
        ("Prompt", "prompt", 38),
        ("Type", "request_type", 18),
        ("Mode", "mode", 10),
        ("Provider", "provider", 10),
        ("Seconds", "seconds", 8),
        ("Len", "length", 6),
        ("Target", "target", 8),
        ("FirstTok", "first_token_ms", 10),
        ("ProviderMs", "provider_ms", 10),
        ("ContextMs", "context_ms", 10),
        ("Check", "check", 7),
    ]
    print(" | ".join(label.ljust(width) for label, _, width in columns))
    print("-+-".join("-" * width for _, _, width in columns))
    for row in rows:
        values = []
        for _, key, width in columns:
            value = str(row.get(key, ""))
            if len(value) > width:
                value = value[: width - 3].rstrip() + "..."
            values.append(value.ljust(width))
        print(" | ".join(values))


def ollama_available(core: NexusCore) -> bool:
    info = core.provider_router.detect_provider("ollama", ttl=0)
    return bool(info.available and info.models)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Cognitive Nexus response speed.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate planner/profile targets without calling Ollama.")
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run)
    core: NexusCore | None = None
    if not dry_run:
        core = NexusCore()
        if not ollama_available(core):
            print("Ollama is unavailable; skipped live speed test.\n")
            dry_run = True
            core = None

    rows = [evaluate_prompt(prompt, dry_run=dry_run, core=core) for prompt in PROMPTS]
    print_table(rows)
    failures = [row for row in rows if row["check"] != "PASS"]
    if failures:
        print(f"\nResponse speed eval found {len(failures)} slow case(s).")
        return 1
    if dry_run:
        print("\nResponse speed dry-run passed.")
    else:
        normal_rows = [row for row in rows if row["request_type"] in {"casual_chat", "simple_fact"}]
        if normal_rows:
            average = sum(float(row["seconds"]) for row in normal_rows) / len(normal_rows)
            print(f"\nAverage casual/simple response time: {average:.2f}s.")
        print("Response speed eval passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
