"""Diagnostics: how the last answer was made, from what the app recorded while making it.

Shows why an answer came out as it did: who wrote it, the limits it was given, how long it was asked
to be and how long it is, why the model stopped, how long it took, and what the content rule and any
calculation or search plan did. No message text is shown, so it is safe to show in demo-safe mode.
"""

from __future__ import annotations

from typing import Any

STOP_REASONS = {
    "stop": "finished by itself",
    "length": "hit its token limit: the answer is not finished",
    "": "not reported",
}
RULE_STAGES = {
    "not_a_candidate": "not looked at closer (nothing to check)",
    "judge_no": "checked by the model: allowed",
    "judge_yes": "checked by the model: stopped by the rule",
    "judge_unclear": "the check could not decide (not a finding)",
    "judge_unavailable": "no model was available for the check",
    "picture_of_undressed_minor": "picture stopped without a model",
}


def answer_rows(last_provider: dict[str, Any] | None, last_rule: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Label and value rows for the last answer. Empty when there was none."""

    meta = dict(last_provider or {})
    if not meta:
        return []
    generation = dict(meta.get("generation") or {})
    timings = dict(meta.get("timings") or {})
    rows: list[dict[str, str]] = [
        {"What": "Answered by", "Value": f"{meta.get('provider') or 'unknown'}" + (f" / {meta['model']}" if meta.get("model") else "")},
    ]
    if meta.get("provider") in {"calculator", "model_and_calculator"}:
        calculation = dict(meta.get("calculation") or {})
        rows.append({"What": "Calculation", "Value": f"{calculation.get('expression', '')} = {calculation.get('value', '')}"})
    if generation:
        asked = generation.get("requested_words")
        rows += [
            {"What": "Length asked for", "Value": f"{asked[0]} to {asked[1]} words" if asked else "not stated"},
            {"What": "Length written", "Value": f"{generation.get('words_written', '?')} words"},
            {"What": "Token limit given to the model", "Value": str(generation.get("num_predict") or "?")},
            {"What": "Context window", "Value": str(generation.get("num_ctx") or "?")},
            {"What": "Temperature", "Value": str(generation.get("temperature") if generation.get("temperature") is not None else "model default")},
            {"What": "Speed profile", "Value": str(generation.get("throughput_profile") or "balanced")},
        ]
    if "stopped_because" in meta:
        rows.append({"What": "Why the model stopped", "Value": STOP_REASONS.get(str(meta.get("stopped_because") or ""), str(meta.get("stopped_because")))})
    if timings.get("provider_first_token_ms") is not None:
        rows.append({"What": "First word after", "Value": f"{float(timings['provider_first_token_ms']) / 1000:.1f} s"})
    if timings.get("total_ms") is not None:
        rows.append({"What": "Total time", "Value": f"{float(timings['total_ms']) / 1000:.1f} s"})
    elif meta.get("elapsed") is not None:
        rows.append({"What": "Total time", "Value": f"{float(meta['elapsed']):.1f} s"})
    attempts = meta.get("attempts") or []
    if attempts:
        rows.append({"What": "Providers tried", "Value": ", ".join(f"{item.get('provider')} ({'ok' if item.get('success') else 'failed'})" for item in attempts)})
    if meta.get("declined_by_model"):
        rows.append({"What": "Refusal", "Value": "the model declined (its own refusal, not the app's)"})
    rule = dict(last_rule or {})
    if rule.get("stage"):
        rows.append({"What": "Content rule", "Value": RULE_STAGES.get(str(rule["stage"]), str(rule["stage"]))})
    plan = dict(meta.get("search_plan") or {})
    if plan:
        rows.append({"What": "Search plan", "Value": f"{plan.get('source')}: " + "; ".join(plan.get("queries") or [])})
    return rows


__all__ = ["RULE_STAGES", "STOP_REASONS", "answer_rows"]
