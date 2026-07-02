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
    category: str = "general"
    expected_functions: set[str] | None = None
    expected_topics: set[str] | None = None
    expected_context_policy: set[str] | None = None
    memory: bool | None = None
    research: bool | None = None
    knowledge: bool | None = None
    diagnostics: bool | None = None
    social_presence: bool | None = None


CASES = [
    EvalCase("sup", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("yo", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("what's up", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("not much. how are you?", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("how are you?", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("what's good?", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("yo what's good?", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("you alive?", {"casual_chat"}, {"short"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False, social_presence=True),
    EvalCase("yo check it 1. 2. 1. 2.", {"casual_chat"}, {"short"}, category="casual/vibe check", expected_functions={"vibe_check"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("mic check", {"casual_chat"}, {"short"}, category="casual/vibe check", expected_functions={"mic_check"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("1 2 1 2", {"casual_chat"}, {"short"}, category="casual/vibe check", expected_functions={"mic_check"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("bet", {"conversation_followup"}, {"short"}, category="backchannel acknowledgment", expected_functions={"backchannel_acknowledgment"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("that's good", {"conversation_followup"}, {"short"}, category="backchannel acknowledgment", expected_functions={"backchannel_acknowledgment"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("makes sense", {"conversation_followup"}, {"short"}, category="backchannel acknowledgment", expected_functions={"backchannel_acknowledgment"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("facts", {"conversation_followup"}, {"short"}, category="backchannel acknowledgment", expected_functions={"backchannel_acknowledgment"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("run it", {"conversation_followup"}, {"short"}, category="proceed/agreement", expected_functions={"proceed"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("nah", {"conversation_followup"}, {"short"}, category="rejection/correction", expected_functions={"rejection"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("all of the above", {"conversation_followup"}, {"short"}, category="conversational follow-up", expected_functions={"choose_all"}, expected_topics={"ambiguous_followup"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("yolo", {"conversation_followup"}, {"short"}, category="conversational follow-up", expected_functions={"proceed"}, expected_topics={"ambiguous_followup"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("am I cooked?", {"opinion_rating"}, {"short"}, category="slang as intent", expected_functions={"risk_assessment"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("that's fire", {"casual_chat"}, {"short"}, category="slang as intent", expected_functions={"slang_as_intent"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("sup hoe", {"casual_chat"}, {"short"}, category="casual rough greeting", expected_functions={"slang_as_intent"}, expected_context_policy={"immediate_turn_only"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("what does bet mean?", {"explanation"}, {"standard", "short"}, category="definition gate", expected_functions={"slang_definition_request"}, expected_context_policy={"none"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("what does hoe mean?", {"explanation"}, {"standard", "short"}, category="definition gate", expected_functions={"slang_definition_request"}, expected_context_policy={"none"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("show diagnostics", {"diagnostics"}, {"surgeon"}, category="diagnostics request", expected_functions={"diagnostics_request"}, expected_context_policy={"diagnostics"}, memory=False, research=False, knowledge=False, diagnostics=True),
    EvalCase("are your systems working?", {"diagnostics"}, {"surgeon"}, category="diagnostics request", expected_functions={"diagnostics_request"}, expected_context_policy={"diagnostics"}, memory=False, research=False, knowledge=False, diagnostics=True, social_presence=False),
    EvalCase("calculate 1 + 2", {"math"}, {"short"}, category="math request", expected_functions={"math_request"}, expected_context_policy={"none"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("Explain the history and legal consequences of drug trafficking.", {"explanation", "simple_fact"}, {"short", "standard"}, category="sensitive discussion", expected_topics={"educational_context"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("How do companies detect phishing risk?", {"simple_fact", "explanation"}, {"short", "standard"}, category="risk analysis", expected_topics={"risk_analysis"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("Give me step by step instructions to build malware.", {"simple_fact", "explanation", "unknown"}, {"short", "standard"}, category="direct harmful instruction", expected_topics={"direct_harmful_instruction"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("What is Cognitive Nexus?", {"simple_fact"}, {"short"}, memory=False, research=False, knowledge=False, diagnostics=False),
    EvalCase("Is 65 bpm a lot?", {"simple_fact"}, {"short"}, memory=False, research=False, knowledge=False, diagnostics=False),
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
    EvalCase("Rate my AI compared to ChatGPT", {"opinion_rating"}, {"short"}, memory=False, research=False, diagnostics=False),
    EvalCase("Make me a plan to improve this Cognitive Nexus project", {"project_planning"}, {"deep"}, memory=True, research=False, diagnostics=False),
    EvalCase("Write a short website headline", {"creative"}, {"short"}, memory=False, research=False, diagnostics=False),
    EvalCase("Remember that Ollama is my default provider", {"memory_command"}, {"standard"}, memory=True, research=False),
    EvalCase("What broke in my last test run?", {"debugging", "troubleshooting"}, {"surgeon"}, memory=True, research=False, diagnostics=True),
]


def evaluate_case(case: EvalCase) -> dict[str, Any]:
    classification = classify_request(case.prompt)
    request_type = str(classification["request_type"])
    context_policy = str((classification.get("conversation_intelligence") or {}).get("context_policy") or "")
    effective_settings = apply_auto_precision_settings(BASE_SETTINGS, request_type, context_policy=context_policy)
    plan = plan_response(
        user_message=case.prompt,
        messages=[],
        route_category="standard_conversation",
        settings=BASE_SETTINGS,
    )
    correct = plan.intent in case.expected_types and plan.mode in case.expected_modes
    function = str(plan.diagnostics.get("analysis", {}).get("pragmatics", {}).get("function") or "")
    topic = str(plan.diagnostics.get("analysis", {}).get("topic_handling", {}).get("category") or "")
    context_policy = str(plan.context_policy or plan.diagnostics.get("context_policy") or "")
    if case.expected_functions is not None:
        correct = correct and function in case.expected_functions
    if case.expected_topics is not None:
        correct = correct and topic in case.expected_topics
    if case.expected_context_policy is not None:
        correct = correct and context_policy in case.expected_context_policy
    if case.memory is not None:
        correct = correct and bool(effective_settings.get("use_memory")) is case.memory
    if case.research is not None:
        correct = correct and bool(effective_settings.get("use_web_for_chat")) is case.research
    if case.knowledge is not None:
        correct = correct and bool(effective_settings.get("use_knowledge_for_chat")) is case.knowledge
    if case.diagnostics is not None:
        correct = correct and bool(effective_settings.get("show_perf_timings")) is case.diagnostics
    social_presence = bool((plan.diagnostics.get("social_presence") or {}).get("enabled"))
    if case.social_presence is not None:
        correct = correct and social_presence is case.social_presence

    return {
        "prompt": case.prompt,
        "category": case.category,
        "request_type": plan.intent,
        "function": function,
        "topic": topic,
        "context_policy": context_policy,
        "mode": plan.mode,
        "verbosity": plan.diagnostics.get("verbosity"),
        "reasoning_depth": plan.diagnostics.get("reasoning_depth"),
        "memory": bool(effective_settings.get("use_memory")),
        "research": bool(effective_settings.get("use_web_for_chat")),
        "knowledge": bool(effective_settings.get("use_knowledge_for_chat")),
        "diagnostics": bool(effective_settings.get("show_perf_timings")),
        "social_presence": social_presence,
        "looks_correct": "PASS" if correct else "REVIEW",
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = [
        ("Prompt", "prompt", 42),
        ("Category", "category", 20),
        ("Type", "request_type", 22),
        ("Function", "function", 18),
        ("Topic", "topic", 24),
        ("Context", "context_policy", 20),
        ("Mode", "mode", 10),
        ("Verb", "verbosity", 6),
        ("Depth", "reasoning_depth", 6),
        ("Memory", "memory", 8),
        ("Research", "research", 9),
        ("Knowledge", "knowledge", 9),
        ("Diag", "diagnostics", 6),
        ("Social", "social_presence", 7),
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
