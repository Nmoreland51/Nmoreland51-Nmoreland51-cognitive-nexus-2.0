"""Real-answer quality evaluation for Cognitive Nexus Auto Precision Mode."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Any

from modules.chat_profile import ChatProfile
from modules.nexus_core import NexusCore
from modules.response_planner import apply_auto_precision_settings, classify_request, plan_response
from nexus_router import RouterConfig, route_message


PROMPTS = [
    "What is Cognitive Nexus?",
    "Is 65 bpm a lot?",
    "Fix this import error: ModuleNotFoundError: core.model",
    "Why is my Streamlit app slow?",
    "Rate my AI compared to ChatGPT.",
    "Make me a plan to improve this project.",
    "Write a short website headline for Cognitive Nexus.",
    "What broke in my last test run?",
    "Explain Ollama in one paragraph.",
    "What should I do next with this repo?",
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
    "generation_timeout": 120.0,
    "max_context_chars": 12000,
    "recent_message_limit": 4,
    "knowledge_top_k": 3,
    "enable_reality_grounding": False,
    "enable_reality_first_reasoning": False,
    "enable_reality_research_agent": False,
    "enable_bloodhound_search": False,
    "staged_streaming": False,
}

INTERNAL_MARKERS = (
    "adaptive response plan",
    "response plan:",
    "target length:",
    "route:",
    "intent:",
    "mode:",
    "sidebar",
    "planner",
    "internal instruction",
)


@dataclass(frozen=True)
class QualityScore:
    directness: bool
    not_overexplaining: bool
    usefulness: bool
    notes: str


def preview_text(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _has_ordered_steps(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:\d+\.|-)\s+\S+", text)) or "phase" in text.lower()


def _dry_run_quality(prompt: str, request_type: str, mode: str, profile: dict[str, Any]) -> QualityScore:
    lower_prompt = prompt.lower()
    headline = "headline" in lower_prompt
    one_paragraph = "one paragraph" in lower_prompt
    next_repo = "what should i do next" in lower_prompt and "repo" in lower_prompt
    simple_like = request_type in {"simple_fact"} or headline
    directness = bool(profile.get("style")) and mode in {"short", "standard", "deep", "surgeon", "research"}
    not_overexplaining = mode == "short" if simple_like else mode in {"short", "standard", "deep", "surgeon", "research"}
    usefulness = True
    if headline:
        not_overexplaining = mode == "short"
        usefulness = request_type == "creative"
    elif one_paragraph:
        not_overexplaining = mode in {"short", "standard"}
        usefulness = request_type == "explanation"
    elif next_repo:
        usefulness = request_type == "project_planning"
    if request_type in {"debugging", "troubleshooting"}:
        usefulness = mode == "surgeon" and bool(profile.get("use_memory"))
    elif request_type == "project_planning":
        usefulness = mode == "deep" and "Prioritize" in str(profile.get("style", ""))
    elif request_type == "opinion_rating":
        usefulness = "score" in str(profile.get("style", "")).lower()
    elif request_type in {"research", "reality_check"}:
        usefulness = mode == "research" and bool(profile.get("use_web_for_chat"))
    notes = "dry-run planner proxy"
    return QualityScore(directness, not_overexplaining, usefulness, notes)


def score_answer_quality(prompt: str, request_type: str, mode: str, answer: str, *, dry_run: bool = False, profile: dict[str, Any] | None = None) -> QualityScore:
    """Score one answer with lightweight request-specific heuristics."""

    profile = profile or {}
    if dry_run:
        return _dry_run_quality(prompt, request_type, mode, profile)

    text = str(answer or "").strip()
    lower = text.lower()
    words = re.findall(r"\b\w+\b", text)
    word_count = len(words)
    notes: list[str] = []

    directness = bool(text) and not any(marker in lower for marker in INTERNAL_MARKERS)
    if not directness:
        notes.append("internal marker or empty answer")

    simple_or_headline = request_type == "simple_fact" or "headline" in prompt.lower()
    if simple_or_headline:
        limit = 35 if "headline" in prompt.lower() else 95
        not_overexplaining = word_count <= limit
    elif request_type in {"debugging", "troubleshooting"}:
        not_overexplaining = word_count <= 220
    elif request_type == "project_planning":
        not_overexplaining = word_count <= 260
    else:
        not_overexplaining = word_count <= 180
    if not not_overexplaining:
        notes.append(f"long answer: {word_count} words")

    usefulness = True
    if request_type in {"debugging", "troubleshooting"}:
        usefulness = bool(re.search(r"\b(?:cause|likely|fix|next|check|command|run|import|module|cache|rerun)\b", lower))
    elif request_type == "project_planning":
        usefulness = _has_ordered_steps(text)
    elif request_type == "opinion_rating":
        usefulness = bool(re.search(r"\b(?:\d+(?:\.\d+)?\s*/\s*10|score|verdict|rate|rating|strong|weak)\b", lower))
    elif "headline" in prompt.lower():
        usefulness = bool(text) and word_count <= 20 and "\n\n" not in text
    elif request_type == "simple_fact":
        usefulness = word_count >= 3
    if not usefulness:
        notes.append("missing request-specific useful signal")

    return QualityScore(directness, not_overexplaining, usefulness, "; ".join(notes) or "ok")


def _plan_for_prompt(prompt: str) -> tuple[Any, dict[str, Any], str]:
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
    plan, effective, _route_category = _plan_for_prompt(prompt)
    profile = dict(plan.diagnostics.get("auto_precision_profile") or effective.get("auto_precision_profile") or {})
    provider = "dry_run"
    answer = ""
    if dry_run:
        answer = "[dry run] Planner/profile evaluated without model text."
    else:
        assert core is not None
        settings = dict(BASE_SETTINGS)
        answer = core.generate_chat_response(prompt, [], settings)
        provider_meta = dict(core.last_provider_result or {})
        provider = str(provider_meta.get("provider") or "unknown")
        live_plan = dict(core.last_response_plan or {})
        if live_plan:
            plan.intent = str(live_plan.get("intent") or plan.intent)
            plan.mode = str(live_plan.get("mode") or plan.mode)
            profile = dict(live_plan.get("diagnostics", {}).get("auto_precision_profile") or profile)

    score = score_answer_quality(prompt, plan.intent, plan.mode, answer, dry_run=dry_run, profile=profile)
    return {
        "prompt": prompt,
        "request_type": plan.intent,
        "profile": f"{plan.mode}/{profile.get('style', '')[:42]}",
        "provider": provider,
        "preview": preview_text(answer),
        "length": len(answer),
        "directness": "PASS" if score.directness else "FAIL",
        "not_overexplaining": "PASS" if score.not_overexplaining else "FAIL",
        "usefulness": "PASS" if score.usefulness else "FAIL",
        "notes": score.notes,
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = [
        ("Prompt", "prompt", 38),
        ("Type", "request_type", 20),
        ("Profile", "profile", 26),
        ("Provider", "provider", 12),
        ("Preview", "preview", 44),
        ("Len", "length", 6),
        ("Direct", "directness", 7),
        ("Lean", "not_overexplaining", 7),
        ("Useful", "usefulness", 7),
        ("Notes", "notes", 24),
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
    parser = argparse.ArgumentParser(description="Evaluate Cognitive Nexus real answer quality.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate planner/profile output without calling a model.")
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run)
    core: NexusCore | None = None
    if not dry_run:
        core = NexusCore()
        if not ollama_available(core):
            print("Ollama is unavailable; falling back to dry-run planner evaluation.\n")
            dry_run = True
            core = None

    rows = [evaluate_prompt(prompt, dry_run=dry_run, core=core) for prompt in PROMPTS]
    print_table(rows)
    failures = [
        row
        for row in rows
        if row["directness"] != "PASS" or row["not_overexplaining"] != "PASS" or row["usefulness"] != "PASS"
    ]
    if failures:
        print(f"\nAnswer quality eval found {len(failures)} issue(s).")
        return 1
    print("\nAnswer quality eval passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
