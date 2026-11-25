"""The Chat tab: the conversation, streaming the answer, and saving it.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

import time
from typing import Any
import streamlit as st

from modules.answer_meta import answer_meta, describe_answer
from modules.answer_resolution import is_ungrounded, other_models, resolution_label, resolution_settings
from modules.behavior_policy import policy_from
from modules.memory import (
    add_message,
    get_messages,
    save_session_history,
)
from ui.shared import clear_chat_state, clear_runtime_caches, get_nexus_core, is_demo_safe, record_perf, reset_session_state, sync_core_diagnostics


# An ungrounded answer that can be answered again, and the choice the owner made under it.
RESOLVABLE_KEY = "chat_resolvable_answer"
RESOLVE_KEY = "chat_resolve_choice"


def normalize_assistant_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response.strip()
    if isinstance(response, (list, tuple)):
        return "".join(str(item) for item in response if isinstance(item, str)).strip()
    return str(response).strip()


def empty_assistant_response_message(provider_result: dict[str, Any] | None = None) -> str:
    provider_result = provider_result or {}
    reason = str(provider_result.get("fallback_reason") or provider_result.get("error") or "").strip()
    if reason:
        return f"Fallback: provider returned no visible assistant response. Reason: {reason}"
    return "Fallback: provider returned no visible assistant response. Check Diagnostics for provider attempts."


def persist_assistant_response(response: Any, provider_result: dict[str, Any] | None = None) -> str:
    response_text = normalize_assistant_response(response)
    if not response_text:
        response_text = empty_assistant_response_message(provider_result)
    meta = answer_meta(provider_result)
    add_message("assistant", response_text, meta=meta if meta.get("provider") else None)
    save_session_history()
    return response_text


def merge_chat_timing_trace(
    provider_result: dict[str, Any] | None,
    *,
    turn_started: float,
    render_ms: float,
    save_ms: float,
) -> dict[str, Any]:
    result = dict(provider_result or {})
    timings = dict(result.get("timings") or {})
    timings["render_ms"] = round(float(render_ms), 1)
    timings["save_chat_history_ms"] = round(float(save_ms), 1)
    timings["total_ms"] = round((time.perf_counter() - turn_started) * 1000, 1)
    result["timings"] = timings
    result["elapsed"] = round(float(timings["total_ms"]) / 1000.0, 3)
    return result


def should_show_plan_caption(settings: dict[str, Any], plan: dict[str, Any]) -> bool:
    if not plan:
        return False
    router_config = settings.get("router_config")
    router_debug = bool(getattr(router_config, "show_debug", False))
    return bool(settings.get("advanced_mode") or router_debug)


def build_chat_prompt(user_message: str, settings: dict[str, Any], route_decision) -> str:
    prompt, _context = get_nexus_core().build_chat_prompt(user_message, get_messages(), settings, route_decision)
    return prompt


def is_capability_question(message: str) -> bool:
    lowered = " ".join((message or "").lower().strip().split())
    capability_phrases = [
        "what can you do",
        "what are your capabilities",
        "what can cognitive nexus do",
        "what can eni do",
        "show capabilities",
    ]
    return any(phrase in lowered for phrase in capability_phrases)


def generate_chat_response(user_message: str, settings: dict[str, Any]) -> str:
    started = time.perf_counter()
    core = get_nexus_core()
    response = core.generate_chat_response(user_message, get_messages(), settings)
    sync_core_diagnostics(core)
    record_perf("chat.central_response", time.perf_counter() - started, settings)
    return response


def render_chat_tab(settings: dict[str, Any]) -> None:
    demo_safe = is_demo_safe(settings)
    header_col, clear_col, reset_col = st.columns([5, 1, 1])
    with header_col:
        st.subheader("Chat")
    with clear_col:
        if st.button("Clear Chat", key="chat_tab_clear_button", width="stretch"):
            clear_chat_state()
            st.rerun()
    with reset_col:
        if st.button("Reset", key="chat_tab_reset_button", width="stretch"):
            reset_session_state()
            clear_runtime_caches()
            st.rerun()

    if not settings.get("advanced_mode") and not get_messages():
        with st.expander("Welcome to Cognitive Nexus!", expanded=True):
            st.markdown("""
            **Cognitive Nexus** is a reality-first AI research platform that prioritizes factual accuracy and source verification.

            **Key Features:**
            - **Reality-First Research**: Grounded research with verdict quality assessment
            - **Web Search**: Bloodhound deep search with source trust scoring
            - **Local Knowledge**: Store and query your own documents
            - **Image Generation**: Create images with ComfyUI integration
            - **Adaptive Memory**: Learns from conversations for personalized responses

            **Getting Started:**
            1. Enable "Advanced mode" in the sidebar for full developer controls
            2. Try asking questions that require research or verification
            3. Use commands like "search web for..." or "research..."
            4. Upload documents in the Files/Knowledge tab

            **Tips:**
            - For casual chat, keep it simple - the system optimizes for speed
            - For research, use specific queries with sources
            - Check the Diagnostics tab for system health
            """)

    # Inside a tab, st.chat_input is drawn where it is called. New messages go into this container
    # (above the input) so the live exchange doesn't appear below the message box.
    messages_box = st.container()
    for message in get_messages():
        with messages_box.chat_message(message.get("role", "assistant")):
            st.markdown(message.get("content", ""))
            answer_line = "" if demo_safe else describe_answer(message.get("meta"))
            if answer_line:
                st.caption(answer_line)

    show_advanced_debug = settings.get("advanced_mode") or settings["router_config"].show_debug
    if show_advanced_debug and demo_safe:
        st.info("Advanced raw chat diagnostics are hidden in Demo Safe Mode.")
        show_advanced_debug = False
    if show_advanced_debug and "last_route_decision" in st.session_state:
        with st.expander("Last route decision", expanded=False):
            st.json(st.session_state.last_route_decision)
    if show_advanced_debug and "last_response_plan" in st.session_state:
        plan = st.session_state.last_response_plan or {}
        with st.expander("Response planner", expanded=False):
            metric_cols = st.columns(4)
            metric_cols[0].metric("Mode", str(plan.get("mode", "auto")))
            metric_cols[1].metric("Intent", str(plan.get("intent", "unknown")))
            metric_cols[2].metric("Max tokens", int(plan.get("max_tokens", 0) or 0))
            metric_cols[3].metric("Context", int(plan.get("num_ctx", 0) or 0))
            st.json(plan)
    if show_advanced_debug and "last_retrieval" in st.session_state:
        retrieval = st.session_state.last_retrieval or {}
        if retrieval:
            with st.expander("Local knowledge retrieval", expanded=False):
                cols = st.columns(3)
                cols[0].metric("Enabled", "Yes" if retrieval.get("enabled") else "No")
                cols[1].metric("Matched chunks", int(retrieval.get("used_count", 0) or 0))
                cols[2].metric("Top K", int(retrieval.get("top_k", 0) or 0))
                if retrieval.get("error"):
                    st.warning(str(retrieval.get("error")))
                st.json(retrieval)
    if show_advanced_debug and "last_reality_audit" in st.session_state:
        audit = st.session_state.last_reality_audit or {}
        if audit.get("confidence"):
            with st.expander("Reality grounding", expanded=False):
                confidence = audit.get("confidence", {})
                hallucination = audit.get("hallucination", {})
                speculation = audit.get("speculation", {})
                source = audit.get("source_grounding", {})
                cols = st.columns(4)
                cols[0].metric("Confidence", str(confidence.get("level", "UNKNOWN")))
                cols[1].metric("Hallucination risk", float(hallucination.get("probability", 0) or 0))
                cols[2].metric("Speculation", str(speculation.get("category", "unknown")))
                cols[3].metric("Grounding", str(source.get("status", "unknown")))
                st.json(audit)
    if show_advanced_debug and "last_trust_audit" in st.session_state:
        trust = st.session_state.last_trust_audit or {}
        if trust:
            with st.expander("Outside text in this prompt", expanded=False):
                # Only text you did not write is examined: passages from files and saved pages.
                outside = trust.get("retrieved_context", {})
                cols = st.columns(3)
                cols[0].metric("Your message", "not scanned")
                cols[1].metric("File/knowledge text", str(outside.get("instruction_risk", "none in this prompt")))
                cols[2].metric("Signs of orders in it", len(outside.get("signals", []) or []))
                st.json(trust)
    if show_advanced_debug and "last_epistemic_assessment" in st.session_state:
        epistemic = st.session_state.last_epistemic_assessment or {}
        if epistemic and epistemic.get("reality"):
            with st.expander("Reality-first reasoning", expanded=False):
                reality = epistemic.get("reality", {})
                feasibility = epistemic.get("feasibility", {})
                constraints = epistemic.get("constraints", {})
                cols = st.columns(4)
                cols[0].metric("Reality", str(reality.get("reality_status", "unknown")))
                cols[1].metric("Feasibility", str(feasibility.get("level", "unknown")))
                cols[2].metric("Score", float(feasibility.get("score", 0) or 0))
                cols[3].metric("Mode", str(constraints.get("epistemic_mode", "auto")))
                st.json(epistemic)

    # Asked for under the last answer: the same question again, looked up on the web or by another model.
    resolve = st.session_state.pop(RESOLVE_KEY, None)
    user_message = st.chat_input("Message Cognitive Nexus")
    if resolve and not user_message:
        research, model = bool(resolve.get("research")), str(resolve.get("model") or "")
        _answer(
            messages_box,
            str(resolve["question"]),
            resolution_settings(settings, research=research, model=model),
            demo_safe,
            history=list(resolve.get("history") or []),
            resolution=resolution_label(research, model),
        )
        return
    if not user_message:
        with messages_box:
            _offer_resolution(settings, demo_safe)
        return

    st.session_state.pop(RESOLVABLE_KEY, None)
    add_message("user", user_message)
    with messages_box.chat_message("user"):
        st.markdown(user_message)
    history = list(get_messages())
    ungrounded = _answer(messages_box, user_message, settings, demo_safe)
    if not ungrounded or demo_safe:
        return
    mode = policy_from({**get_nexus_core().config, **settings}).ungrounded_answers
    if mode == "research":
        _answer(messages_box, user_message, resolution_settings(settings, research=True), demo_safe, history=history, resolution=resolution_label(True, ""))
    elif mode == "offer":
        st.session_state[RESOLVABLE_KEY] = {"question": user_message, "model": str(settings.get("selected_model") or ""), "history": history}
        with messages_box:
            _offer_resolution(settings, demo_safe)


def _choose_resolution(choice: dict[str, Any]) -> None:
    st.session_state.pop(RESOLVABLE_KEY, None)
    st.session_state[RESOLVE_KEY] = choice


def _offer_resolution(settings: dict[str, Any], demo_safe: bool) -> None:
    """Under an answer that used no sources and was rated low: look it up on the web, or ask another installed model."""

    offer = st.session_state.get(RESOLVABLE_KEY)
    if not offer or demo_safe:
        return
    models = other_models(settings.get("chat_models"), str(offer.get("model") or ""))
    st.caption("This answer used no sources and is rated low. The same question can be answered again:")
    columns = st.columns(1 + len(models))
    base = {"question": offer["question"], "history": offer.get("history") or []}
    columns[0].button(
        "Look it up on the web",
        key="chat_resolve_web",
        on_click=_choose_resolution,
        args=({**base, "research": True},),
        help="Sends the question to the search engines and answers it again from what they return.",
    )
    for index, model in enumerate(models, start=1):
        columns[index].button(f"Ask {model}", key=f"chat_resolve_model_{index}", on_click=_choose_resolution, args=({**base, "model": model},))


def _answer(
    messages_box: Any,
    question: str,
    settings: dict[str, Any],
    demo_safe: bool,
    *,
    history: list[dict[str, Any]] | None = None,
    resolution: str = "",
) -> bool:
    """Stream one answer into the chat and save it. True when it used no sources and was rated low."""

    with messages_box.chat_message("assistant"):
        started = time.perf_counter()
        provider_order = list(settings.get("provider_order") or [])
        primary_provider = next((provider for provider in provider_order if provider != "fallback"), "fallback")
        selected_model = str(settings.get("selected_model") or "").strip()
        if resolution:
            status_label = f"{resolution}..."
        elif primary_provider == "ollama" and selected_model:
            status_label = f"Generating with Ollama / {selected_model}..."
        elif primary_provider == "fallback":
            status_label = "Checking provider fallback path..."
        else:
            status_label = f"Generating with {primary_provider}..."
        response_status = st.empty()
        try:
            response_status.info(status_label)
            response = st.write_stream(get_nexus_core().stream_chat_response(question, history if history is not None else get_messages(), settings))
        except Exception as exc:
            response_status.error(f"Response failed: {exc}")
            raise
        response_status.empty()
        sync_core_diagnostics()
        show_advanced_debug = settings.get("advanced_mode") or settings["router_config"].show_debug
        if show_advanced_debug:
            audit = st.session_state.last_reality_audit or {}
            if audit.get("confidence"):
                confidence = audit["confidence"]
                hallucination = audit.get("hallucination", {})
                speculation = audit.get("speculation", {})
                st.caption(
                    f"Grounding: {confidence.get('level', 'UNKNOWN')} | "
                    f"hallucination risk {hallucination.get('probability', 0)} | "
                    f"{speculation.get('category', 'unclassified')}"
                )
            epistemic = st.session_state.last_epistemic_assessment or {}
            if epistemic.get("reality"):
                st.caption(
                    f"Reality-first: {epistemic['reality'].get('reality_status', 'unknown')} | "
                    f"feasibility {epistemic.get('feasibility', {}).get('level', 'unknown')}"
                )
        response = normalize_assistant_response(response)
        if not response:
            response = empty_assistant_response_message(st.session_state.last_provider_result)
            st.warning(response)
        result = dict(st.session_state.get("last_provider_result") or {})
        if resolution:
            result["resolution"] = resolution
            st.session_state.last_provider_result = result
        answer_line = "" if demo_safe else describe_answer(answer_meta(result))
        if answer_line:
            st.caption(answer_line)
        record_perf("chat.stream_response", time.perf_counter() - started, settings)

    if settings.get("show_perf_timings") and "last_provider_result" in st.session_state and not demo_safe:
        timings = st.session_state.last_provider_result.get("timings", {})
        if timings:
            with messages_box.expander("Performance Timings", expanded=False):
                st.json(timings)
    persist_assistant_response(response, st.session_state.get("last_provider_result"))
    return is_ungrounded(st.session_state.get("last_provider_result"), st.session_state.get("last_reality_audit"))
