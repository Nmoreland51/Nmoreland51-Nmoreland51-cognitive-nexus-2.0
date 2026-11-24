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
        if plan.get("topic") and plan.get("topic") != plan.get("question"):
            rows.append({"What": "Taken to mean", "Value": str(plan["topic"])})
    for search in meta.get("searches") or []:
        label = "Search for law or availability" if search.get("purpose") else "Search"
        if search.get("error"):
            value = f"{search.get('query')}: failed ({search['error']})"
        else:
            value = f"{search.get('query')}: {search.get('returned', 0)} found, {search.get('kept', 0)} kept, {search.get('dropped', 0)} dropped"
            if search.get("judged"):
                value += f", {search['judged']} judged by the model" + (" (no answer usable: kept)" if search.get("judge") else "")
        rows.append({"What": label, "Value": value})
    for item in (meta.get("dropped_results") or [])[:6]:
        rows.append({"What": "Left out", "Value": f"{str(item.get('title') or item.get('url') or '')[:90]}: {item.get('reason', '')}"})
    rows += sentence_rows(meta.get("sentence_sources") or [])
    return rows


SENTENCE_KINDS = {
    "stated": "stated on",
    "not found": "not stated on any page read",
    "about the sources": "about the sources, not about the world",
    "advice": "advice, not a statement",
}


def sentence_rows(mapped: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    """Which page states each sentence of a web answer (modules/claim_map.py). Sentences are named by
    their number, not quoted, so nothing written in the chat is shown here."""

    if not mapped:
        return []
    counts: dict[str, int] = {}
    for item in mapped:
        counts[str(item.get("kind"))] = counts.get(str(item.get("kind")), 0) + 1
    counted_as = {"stated": "stated on a page read", "not found": "on no page read", "about the sources": "about the sources", "advice": "advice"}
    rows = [{"What": "Sentences of the answer", "Value": ", ".join(f"{counts[kind]} {counted_as[kind]}" for kind in counted_as if counts.get(kind))}]
    for number, item in enumerate(mapped[:limit], start=1):
        kind = str(item.get("kind"))
        if kind == "stated":
            fetched = f", fetched {item['retrieved_at'][:16].replace('T', ' ')}" if item.get("retrieved_at") else ""
            value = f"stated on {str(item.get('title') or item.get('url'))[:80]} ({item.get('url')}{fetched})"
        else:
            value = SENTENCE_KINDS.get(kind, kind)
            if item.get("missing"):
                value += f" (no page has {', '.join(item['missing'])})"
        rows.append({"What": f"Sentence {number}", "Value": value})
    if len(mapped) > limit:
        rows.append({"What": "More sentences", "Value": f"{len(mapped) - limit} not shown"})
    return rows


__all__ = ["RULE_STAGES", "SENTENCE_KINDS", "STOP_REASONS", "answer_rows", "sentence_rows"]
