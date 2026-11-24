"""The Diagnostics tab.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from modules.context_manager import load_user_profile_summary
from modules.core_health import run_core_health_check
from modules.event_log import event_counts, recent_events
from modules.memory import (
    get_messages,
)
from modules.project_status import (
    PROJECT_ROOT,
    get_environment_status,
    tail_file,
)
from ui.answer_diagnostics import answer_rows
from ui.images_tab import image_provider_status_rows
from ui.shared import format_bytes, get_cached_core_health, get_cached_image_providers, get_cached_image_summary, get_cached_knowledge_summary, get_cached_log_files, get_nexus_core, is_demo_safe, sanitize_demo_rows, sanitize_demo_text


def context_window_caption(context: dict[str, Any]) -> str:
    """One paragraph on how the last chat prompt was fitted to the model's context window."""

    if not context or not context.get("num_ctx"):
        return ""
    allowed = context.get("prompt_tokens_allowed")
    limit_reason = {
        "speed": "limited by how fast this machine reads a prompt",
        "window": "limited by the window size",
        "model": "limited by the model's own window",
    }.get(str(context.get("limited_by") or ""), "")
    model_window = context.get("model_window")
    parts = [
        f"Last chat turn: the prompt was about {context.get('prompt_tokens_estimated')} tokens"
        + (f" of {allowed} allowed ({limit_reason})" if allowed else ""),
        f"sent with a {context['num_ctx']}-token window that also holds a reply of up to {context.get('reply_tokens')} tokens",
    ]
    if model_window:
        parts.append(f"the model itself can read {model_window} tokens")
    line = "; ".join(parts) + "."
    steps = [str(step) for step in context.get("trim_steps") or []]
    if steps:
        line += " To fit, in this order: " + ", ".join(dict.fromkeys(steps)) + "."
    if context.get("older_messages"):
        line += f" {context['older_messages']} older message(s) were condensed into a summary."
    return line


def render_diagnostics_tab(status, inventory: dict[str, Any], image_status: dict[str, Any], core_status: dict[str, Any], settings: dict[str, Any]) -> None:
    st.subheader("Diagnostics")
    st.caption("Live control-center view of providers, grounding, memory, search, and saved outputs.")
    demo_safe = is_demo_safe(settings)
    if demo_safe:
        st.info("Demo Safe Mode is on. Raw paths, environment details, logs, private memory, and machine-specific diagnostics are hidden.")

    provider_order = tuple(settings.get("provider_order") or core_status.get("config", {}).get("provider_order", []))
    selected_model = str(settings.get("selected_model") or "")
    quick_core_health = get_cached_core_health(provider_order, selected_model)
    core_health = st.session_state.get("last_core_health_check") or quick_core_health
    last_provider = st.session_state.get("last_provider_result") or {}
    last_route = st.session_state.get("last_route_decision") or {}
    last_plan = st.session_state.get("last_response_plan") or {}
    last_audit = st.session_state.get("last_reality_audit") or {}
    last_trust = st.session_state.get("last_trust_audit") or {}
    last_epistemic = st.session_state.get("last_epistemic_assessment") or {}
    last_report = st.session_state.get("last_reality_research_report") or {}
    last_retrieval = st.session_state.get("last_retrieval") or last_provider.get("retrieval") or {}
    last_memory = st.session_state.get("last_memory") or last_provider.get("memory") or {}

    confidence = last_audit.get("confidence", {}) if isinstance(last_audit, dict) else {}
    hallucination = last_audit.get("hallucination", {}) if isinstance(last_audit, dict) else {}
    speculation = last_audit.get("speculation", {}) if isinstance(last_audit, dict) else {}
    source_grounding = last_audit.get("source_grounding", {}) if isinstance(last_audit, dict) else {}
    fallback_reason = str(last_provider.get("fallback_reason") or last_provider.get("error") or "").strip()

    st.markdown("### Engine Snapshot")
    top_cols = st.columns(5)
    top_cols[0].metric("Ollama", "Connected" if status.available else "Offline")
    top_cols[1].metric("Answered by", str(last_provider.get("provider") or "No turn yet"))
    top_cols[2].metric("Knowledge chunks", int(inventory.get("research_chunks", 0) or 0))
    top_cols[3].metric("Grounding", str(confidence.get("level", "No audit yet")))
    top_cols[4].metric("Reports", int(inventory.get("research_reports", 0) or 0))

    if fallback_reason:
        st.warning(f"Fallback reason: {sanitize_demo_text(fallback_reason) if demo_safe else fallback_reason}")
    else:
        st.caption("Fallback reason: none recorded for the latest turn.")

    st.markdown("### How the last answer was made")
    answer_table = answer_rows(last_provider, getattr(get_nexus_core(), "last_content_rule", {}) or {})
    if answer_table:
        st.dataframe(answer_table, hide_index=True, width="stretch")
    else:
        st.caption("No answer yet in this session.")
    for model_note in core_status.get("config", {}).get("model_id_notes") or []:
        st.info(model_note)

    st.markdown("### Problems Since Start")
    problem_counts = event_counts()
    problem_cols = st.columns(5)
    problem_cols[0].metric("Model failures", problem_counts["model_failure"])
    problem_cols[1].metric("Fallback notices", problem_counts["provider_fallback"])
    problem_cols[2].metric("Search source failures", problem_counts["search_source_failure"])
    problem_cols[3].metric("Tool failures", problem_counts["tool_failure"])
    problem_cols[4].metric("Degraded mode", problem_counts["degraded_mode"])
    st.caption(
        "Counted separately so a model that failed, a blocked search source and a broken tool are not confused. "
        f"Cloud providers skipped to keep data local: {problem_counts['provider_skipped']}. "
        f"Other errors: {problem_counts['error']}. Also written to logs/events.jsonl."
    )
    problem_rows = recent_events(25)
    if problem_rows and not demo_safe:
        with st.expander("Recent problems", expanded=False):
            st.dataframe(problem_rows, width="stretch", hide_index=True)

    context_line = context_window_caption(last_provider.get("context") or {})
    if context_line:
        st.markdown("### Context Window")
        st.caption(context_line)

    st.markdown("### Core Stability Self-Check")
    action_cols = st.columns([1, 1, 4])
    if action_cols[0].button("Run live model probe", key="run_core_health_probe"):
        with st.status("Running core stability self-check...", expanded=True) as health_status_box:
            st.write("Checking imports, local storage, provider detection, and one tiny local model response.")
            core_health = run_core_health_check(
                PROJECT_ROOT,
                provider_order=provider_order,
                selected_model=selected_model,
                include_probe=True,
            )
            st.session_state.last_core_health_check = core_health
            health_status_box.update(label="Core stability self-check complete", state="complete")
    if action_cols[1].button("Refresh quick check", key="refresh_core_health"):
        get_cached_core_health.clear()
        st.session_state.last_core_health_check = run_core_health_check(
            PROJECT_ROOT,
            provider_order=provider_order,
            selected_model=selected_model,
            include_probe=False,
        )
        core_health = st.session_state.last_core_health_check
    action_cols[2].caption(f"Last self-check: {core_health.get('generated_at', 'not run')}")

    health_summary = core_health.get("summary", {})
    health_status = str(health_summary.get("status", "unknown"))
    health_cols = st.columns(5)
    health_cols[0].metric("Overall", health_status.title())
    health_cols[1].metric("Import errors", int(health_summary.get("import_errors", 0) or 0))
    health_cols[2].metric("Storage errors", int(health_summary.get("storage_errors", 0) or 0))
    health_cols[3].metric("Real providers", len(health_summary.get("ready_model_providers", []) or []))
    health_cols[4].metric("Probe", str(health_summary.get("probe_status", "not_run")))

    health_message = str(health_summary.get("message") or "No self-check message.")
    if health_status == "ok":
        st.success(health_message)
    elif health_status == "error":
        st.error(health_message)
    else:
        st.warning(health_message)

    probe = core_health.get("probe") or {}
    if probe.get("status") == "ok":
        probe_model = "Local model" if demo_safe else probe.get("model", "unknown")
        st.caption(
            f"Live probe answered through {probe.get('provider', 'unknown')} / "
            f"{probe_model} in {float(probe.get('elapsed_seconds', 0) or 0):.2f}s."
        )
    elif probe.get("status") == "error":
        probe_error = sanitize_demo_text(probe.get("error") or "unknown error") if demo_safe else (probe.get("error") or "unknown error")
        st.warning(f"Live probe failed: {probe_error}")

    if demo_safe:
        st.caption("Core self-check details are hidden in Demo Safe Mode.")
    else:
        with st.expander("Core self-check details", expanded=health_status != "ok"):
            st.markdown("Imports")
            st.dataframe(core_health.get("imports", []), width="stretch", hide_index=True)
            st.markdown("Providers")
            st.dataframe(core_health.get("providers", []), width="stretch", hide_index=True)
            st.markdown("Local storage")
            st.dataframe(core_health.get("storage", []), width="stretch", hide_index=True)
            recent_log_signals = core_health.get("recent_log_signals") or []
            if recent_log_signals:
                st.markdown("Recent log signals")
                st.dataframe(recent_log_signals, width="stretch", hide_index=True)

    providers = core_status.get("providers", [])
    if providers:
        st.markdown("### Provider Health")
        provider_rows = []
        for provider in providers:
            models = provider.get("models") or []
            proof = get_nexus_core().provider_router.latest_verification(str(provider.get("name", "")))
            if not provider.get("available"):
                provider_state = "Offline"
            elif provider.get("name") == "fallback":
                provider_state = "Notice only (not a model)"
            elif proof is None:
                provider_state = "Set up, not tested"
            elif proof.get("ok"):
                provider_state = "Working (produced text)"
            else:
                provider_state = "Failed its last request"
            provider_rows.append(
                {
                    "Provider": str(provider.get("name", "unknown")).title(),
                    "Status": provider_state,
                    "Models": len(models),
                    "Endpoint": "Local service hidden" if demo_safe and provider.get("base_url") else provider.get("base_url", ""),
                    "Message": sanitize_demo_text(provider.get("message", "")) if demo_safe else provider.get("message", ""),
                }
            )
        st.dataframe(provider_rows, width="stretch", hide_index=True)
        st.caption(
            "A provider counts as working only after it has produced text: a test prompt or a real answer. "
            "An installed model or a saved API key alone shows as 'Set up, not tested'."
        )
        testable = [str(item.get("name")) for item in providers if item.get("available") and item.get("name") != "fallback"]
        if testable and not demo_safe:
            test_cols = st.columns([2, 1, 3])
            provider_to_test = test_cols[0].selectbox("Provider to test", testable, key="provider_to_test")
            if test_cols[1].button("Send a test prompt", key="send_provider_test"):
                with st.spinner(f"Asking {provider_to_test} for a few words..."):
                    test_record = get_nexus_core().provider_router.verify_provider(provider_to_test, selected_model if provider_to_test == "ollama" else "")
                if test_record.get("ok"):
                    st.success(f"{provider_to_test} answered in {float(test_record.get('seconds') or 0):.1f}s.")
                else:
                    st.error(f"{provider_to_test} failed: {test_record.get('error') or 'no text came back'}")
            test_cols[2].caption("OpenAI and Anthropic bill a few tokens for a test. Local providers are free.")
    else:
        st.info("No providers configured.")

    st.markdown("### Local Knowledge Retrieval")
    retrieval_cols = st.columns(5)
    retrieval_cols[0].metric("Enabled", "Yes" if last_retrieval.get("enabled") else "No")
    retrieval_cols[1].metric("Matched chunks", int(last_retrieval.get("used_count", 0) or 0))
    retrieval_cols[2].metric("Raw results", int(last_retrieval.get("result_count", 0) or 0))
    retrieval_cols[3].metric("Top K", int(last_retrieval.get("top_k", 0) or 0))
    retrieval_cols[4].metric("Fallback RAG", "Yes" if last_provider.get("provider") == "local_knowledge_fallback" else "No")
    if last_retrieval.get("error"):
        st.warning(f"Knowledge retrieval error: {last_retrieval.get('error')}")
    retrieval_sources = last_retrieval.get("sources") or []
    if retrieval_sources and demo_safe:
        st.caption(f"Retrieved local chunks hidden in Demo Safe Mode ({len(retrieval_sources)} item(s)).")
    elif retrieval_sources:
        with st.expander("Retrieved local chunks", expanded=False):
            st.dataframe(retrieval_sources, width="stretch", hide_index=True)

    st.markdown("### Image Providers And Artifacts")
    image_summary = get_cached_image_summary()
    image_providers = get_cached_image_providers()
    image_cols = st.columns(5)
    image_cols[0].metric(
        "Direct image provider",
        str(image_status.get("label") or "Offline") if image_status.get("available") else "Offline",
    )
    image_cols[1].metric("Saved PNGs", int(image_summary.get("image_files", 0) or 0))
    image_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    image_cols[3].metric("Missing records", int(image_summary.get("missing_image_records", 0) or 0))
    image_cols[4].metric("Storage", format_bytes(image_summary.get("total_bytes", 0)))

    last_image_generation = st.session_state.get("last_image_generation_result") or {}
    if last_image_generation:
        if last_image_generation.get("success"):
            st.success(
                f"Last image generation: {last_image_generation.get('provider', 'unknown')} "
                f"saved {last_image_generation.get('saved_count', 0)} artifact(s)."
            )
        else:
            st.warning(f"Last image generation failed: {last_image_generation.get('error') or 'unknown error'}")
    else:
        st.caption("Last image generation: none recorded this session.")

    with st.expander("Image provider detection", expanded=False):
        st.dataframe(image_provider_status_rows(image_providers), width="stretch", hide_index=True)
    recent_images = image_summary.get("recent_images") or []
    if recent_images:
        with st.expander("Recent image artifacts", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_images, enabled=demo_safe), width="stretch", hide_index=True)

    st.markdown("### Last Turn Trace")
    throughput = dict(last_provider.get("throughput") or {})
    timings = dict(last_provider.get("timings") or {})
    measured_tps = throughput.get("provider_tokens_per_second") or throughput.get("output_tokens_per_second_estimate") or timings.get("provider_tokens_per_second") or timings.get("output_tokens_per_second_estimate")
    trace_cols = st.columns(5)
    trace_cols[0].metric("Route", str(last_route.get("label") or last_route.get("category") or "No turn yet"))
    trace_cols[1].metric("Mode", str(last_plan.get("mode", "No plan yet")))
    trace_cols[2].metric("Model", str(last_provider.get("model") or settings.get("selected_model") or "None"))
    trace_cols[3].metric("Elapsed", f"{float(last_provider.get('elapsed', 0) or 0):.2f}s")
    trace_cols[4].metric("Tok/s", f"{float(measured_tps or 0):.1f}" if measured_tps else "No turn yet")

    if throughput:
        with st.expander("Throughput", expanded=False):
            st.json(throughput)

    attempts = last_provider.get("attempts") or []
    if attempts:
        with st.expander("Provider attempts", expanded=False):
            st.dataframe(attempts, width="stretch")

    st.markdown("### Reality And Trust")
    reality_cols = st.columns(5)
    reality_cols[0].metric("Hallucination risk", hallucination.get("probability", "No audit"))
    reality_cols[1].metric("Speculation", str(speculation.get("category", "No audit")))
    reality_cols[2].metric("Source grounding", str(source_grounding.get("status", "No audit")))
    reality_cols[3].metric("Claims", len(last_audit.get("claims", []) or []) if isinstance(last_audit, dict) else 0)
    reality_cols[4].metric("Epistemic mode", str((last_epistemic.get("constraints") or {}).get("epistemic_mode", settings.get("epistemic_mode", "auto"))))

    if last_trust:
        # Only text you did not write is examined: passages from files and saved pages.
        outside = last_trust.get("retrieved_context", {})
        trust_cols = st.columns(3)
        trust_cols[0].metric("Your message", "not scanned")
        trust_cols[1].metric("File/knowledge text", str(outside.get("instruction_risk", "none in last prompt")))
        trust_cols[2].metric("Signs of orders in it", len(outside.get("signals", []) or []))

    st.markdown("### Search And Reports")
    search_cols = st.columns(5)
    search_cols[0].metric("Reality agent", "On" if settings.get("enable_reality_research_agent") else "Off")
    search_cols[1].metric("Bloodhound", "On" if settings.get("enable_bloodhound_search") else "Off")
    search_cols[2].metric("Web sessions", int(inventory.get("web_research_sessions", 0) or 0))
    search_cols[3].metric("Search history", int(inventory.get("search_history_sessions", 0) or 0))
    search_cols[4].metric("Last sources", int(last_provider.get("sources", 0) or len((last_report or {}).get("sources", []) or [])))

    if last_report:
        saved_paths = last_report.get("saved_paths") or {}
        if saved_paths:
            st.success("Last report saved locally." if demo_safe else f"Last report saved: {saved_paths}")
    recent_reports = inventory.get("recent_research_reports") or []
    if recent_reports:
        with st.expander("Recent saved research reports", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_reports, enabled=demo_safe), width="stretch", hide_index=True)

    st.markdown("### Memory And Local Data")
    memory_paths = [PROJECT_ROOT / path for path in inventory.get("memory_files", [])]
    knowledge_summary = get_cached_knowledge_summary()
    embedding_status = knowledge_summary.get("embedding_status", {})
    profile_summary = load_user_profile_summary()
    memory_cols = st.columns(7)
    memory_cols[0].metric("Chat messages", len(get_messages()))
    memory_cols[1].metric("Memory files", sum(path.exists() for path in memory_paths))
    memory_cols[2].metric("Research sources", int(inventory.get("research_sources", 0) or 0))
    memory_cols[3].metric("Generated images", int(inventory.get("generated_images", 0) or 0))
    memory_cols[4].metric("Markdown notes", int(inventory.get("knowledge_notes", 0) or 0))
    memory_cols[5].metric("Local facts", int(profile_summary.get("fact_count", 0) or 0))
    memory_cols[6].metric("Embedding backend", str(embedding_status.get("runtime_backend", "unknown")))

    comfy = core_status.get("comfyui", {})
    if comfy:
        st.caption(
            f"Image provider: {'Available' if image_status.get('available') else 'Offline'} | "
            f"ComfyUI: {comfy.get('message', '')}"
        )
    if embedding_status:
        st.caption(str(embedding_status.get("message", "")))
    recent_notes = inventory.get("recent_knowledge_notes") or []
    if recent_notes:
        with st.expander("Recent Markdown knowledge notes", expanded=False):
            st.dataframe(sanitize_demo_rows(recent_notes, enabled=demo_safe), width="stretch", hide_index=True)
    if last_memory and demo_safe:
        st.caption("Last local memory action hidden in Demo Safe Mode.")
    elif last_memory:
        with st.expander("Last local memory action", expanded=False):
            st.json(last_memory)
    if profile_summary.get("facts") and demo_safe:
        st.caption("Saved local profile facts hidden in Demo Safe Mode.")
    elif profile_summary.get("facts"):
        with st.expander("Saved local profile facts", expanded=False):
            st.dataframe(profile_summary["facts"], width="stretch", hide_index=True)

    if demo_safe:
        st.caption("Raw diagnostics and log files are hidden in Demo Safe Mode.")
    else:
        with st.expander("Raw diagnostics", expanded=False):
            st.json(
                {
                    "provider_result": last_provider,
                    "route": last_route,
                    "response_plan": last_plan,
                    "reality_audit": last_audit,
                    "trust_audit": last_trust,
                    "epistemic": last_epistemic,
                    "retrieval": last_retrieval,
                    "memory": last_memory,
                    "image_generation": last_image_generation,
                    "image_summary": image_summary,
                    "core_health": core_health,
                    "environment": get_environment_status(),
                }
            )
    log_files = [] if demo_safe else get_cached_log_files()
    if log_files:
        with st.expander("Log files", expanded=False):
            selected = st.selectbox("Log file", log_files, format_func=lambda path: path.name)
            st.text(tail_file(selected))
    if st.session_state.get("perf_timings") and not demo_safe:
        with st.expander("Performance timings", expanded=False):
            st.dataframe(st.session_state.perf_timings, width="stretch")
