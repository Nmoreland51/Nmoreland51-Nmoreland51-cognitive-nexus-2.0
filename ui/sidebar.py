"""The sidebar: model and provider choice, speed, memory and session controls.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from modules.chat_profile import (
    ChatProfile,
)
from modules.nexus_config import save_runtime_config
from modules.response_planner import RESPONSE_MODES
from nexus_router import (
    RouterConfig,
)
from ui.shared import clear_chat_state, clear_runtime_caches, get_nexus_core, reset_session_state, sanitize_demo_text, warm_chat_model


def model_check_caption(record: dict[str, Any] | None) -> str:
    """One line saying whether the chat model has actually produced text."""

    if not record:
        return "Model check: testing now. The model is installed but has not answered yet."
    if record.get("ok"):
        if record.get("source") == "answer":
            return "Model check: working (it wrote the last answer)."
        return f"Model check: working (answered a test prompt in {float(record.get('seconds') or 0):.1f}s)."
    return f"Model check failed: {record.get('error') or 'no text came back'}"


def data_locality_caption(provider_order: list[str], allow_cloud_fallback: bool, cloud_ready: list[str]) -> str:
    """One line saying where chat prompts can go with the current settings."""

    names = {"openai": "OpenAI", "anthropic": "Anthropic"}
    primary = next((name for name in provider_order if name != "fallback"), "")
    if primary in cloud_ready:
        return f"Data: chat prompts are sent to {names[primary]}, because it is first in the provider order."
    usable = [names[name] for name in provider_order if name in cloud_ready]
    if usable and allow_cloud_fallback:
        return (
            "Data: prompts stay on this machine unless the local model fails; "
            f"then they may be sent to {' or '.join(usable)}."
        )
    if usable:
        verb = "is" if len(usable) == 1 else "are"
        return f"Data: prompts stay on this machine. {' and '.join(usable)} {verb} set up but will not be used as a fallback."
    return "Data: prompts stay on this machine. Web searches go to the internet only when you ask for one."


THROUGHPUT_MODES = ["balanced", "fast", "turbo"]


FAST_MODEL_HINTS = (
    "qwen2.5:0.5b",
    "qwen2.5:1.5b",
    "llama3.2:1b",
    "gemma2:2b",
    "phi3:mini",
    "phi3.5:mini",
    "llama3.2:3b",
    "llama3.2",
)


def get_chat_model(models: list[str], throughput_mode: str = "balanced") -> str:
    if throughput_mode in {"fast", "turbo"}:
        non_embedding = [model for model in models if "embed" not in model.lower()]
        for preferred in FAST_MODEL_HINTS:
            preferred_base = preferred.split(":", 1)[0].lower()
            for model in non_embedding:
                model_base = model.split(":", 1)[0].lower()
                if model.lower() == preferred.lower() or model_base == preferred_base:
                    return model
    preferred_models = [
        "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
        "BlackHillsInfoSec/llama-3.1-8b-abliterated",
        "mannix/llama3.1-8b-abliterated:latest",
        "mannix/llama3.1-8b-abliterated",
        "llama3.2:3b",
        "dolphin-llama3:8b",
        "dolphin-llama3:latest",
        "dolphin-llama3:70b",
    ]
    for preferred in preferred_models:
        if preferred in models:
            return preferred
    non_embedding = [model for model in models if "embed" not in model.lower()]
    return non_embedding[0] if non_embedding else (models[0] if models else "")


def normalize_provider_order(selection: list[str], provider_options: list[str]) -> list[str]:
    valid = set(provider_options)
    normalized: list[str] = []
    for provider in selection:
        if provider not in valid or provider == "fallback" or provider in normalized:
            continue
        normalized.append(provider)
    normalized.append("fallback")
    return normalized


def _select_model_option(label: str, models: list[str], default: str) -> str:
    index = models.index(default) if default in models else 0
    return st.selectbox(label, models, index=index)


def render_sidebar(
    status,
    inventory: dict[str, Any],
    image_status: dict[str, Any],
    chat_profile: ChatProfile,
    core_status: dict[str, Any],
) -> dict[str, Any]:
    with st.sidebar:
        st.header("Cognitive Nexus")
        st.subheader("Provider")
        if status.available and status.models:
            st.success("Ollama running")
        elif status.available:
            st.warning("Ollama running, no models")
        else:
            st.error("Ollama offline")
        demo_safe_mode = st.checkbox(
            "Demo Safe Mode",
            value=False,
            help="Hide local paths, raw private memory, environment details, and machine-specific diagnostics.",
        )
        st.caption(sanitize_demo_text(status.message) if demo_safe_mode else status.message)
        if demo_safe_mode:
            st.caption("Endpoint: local provider endpoint hidden")
        else:
            st.caption(f"Endpoint: {status.base_url}")

        throughput_mode = st.selectbox(
            "Throughput profile",
            THROUGHPUT_MODES,
            index=1,
            format_func=lambda value: {
                "balanced": "Balanced quality",
                "fast": "Fast",
                "turbo": "Turbo / shortest path",
            }[value],
            help="Fast and Turbo reduce context overhead and use speed-friendly local generation options. Actual tokens/sec depends on model and hardware.",
        )
        target_tokens_per_second = st.slider(
            "Target tokens/sec",
            10,
            200,
            60 if throughput_mode == "fast" else 120 if throughput_mode == "turbo" else 30,
            step=10,
            help="Planning target only. The Diagnostics tab reports measured throughput after each turn.",
        )

        selected_model = None
        if status.models:
            default_model = get_chat_model(status.models, throughput_mode)
            default_index = status.models.index(default_model) if default_model in status.models else 0
            selected_model = st.selectbox("Chat model", status.models, index=default_index)
            warm_chat_model(selected_model)
            model_check = get_nexus_core().provider_router.verification("ollama", selected_model)
            st.caption(model_check_caption(model_check))
            if model_check and not model_check.get("ok") and st.button("Test the model again", key="retest_chat_model"):
                with st.spinner("Asking the model for a few words..."):
                    get_nexus_core().provider_router.verify_ollama(selected_model)
                st.rerun()
        else:
            st.info("Fallback mode is active.")

        st.subheader("Answer Behavior")
        auto_precision_mode = st.checkbox(
            "Auto Precision Mode",
            value=True,
            help="Automatically chooses answer length, detail, memory, research, and diagnostics from the request.",
        )
        last_plan = st.session_state.get("last_response_plan") or {}
        current_mode = (
            f"{last_plan.get('intent', 'auto')} / {last_plan.get('mode', 'auto')}"
            if last_plan
            else ("Auto Precision ready" if auto_precision_mode else "Manual overrides ready")
        )
        st.caption(f"Current answer mode: {current_mode}")

        provider_options = ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]
        configured_order = normalize_provider_order(
            [
                item
                for item in core_status.get("config", {}).get("provider_order", provider_options)
                if item in provider_options
            ],
            provider_options,
        )
        provider_order = configured_order
        allow_cloud_fallback = bool(core_status.get("config", {}).get("allow_cloud_fallback", False))
        configured_comfyui_url = str(core_status.get("config", {}).get("comfyui_url") or "http://127.0.0.1:8188")
        configured_hf_local_model = str(core_status.get("config", {}).get("hf_local_model") or "")
        comfyui_url = configured_comfyui_url
        hf_local_model = configured_hf_local_model

        use_memory = False
        use_knowledge_for_chat = True
        use_web_for_chat = True
        show_sources = True
        enable_router = True
        show_perf_timings = False
        advanced_mode = False
        demo_mode = False
        generation_timeout = 600
        god_mode = False
        freedom_level = "bold"
        use_llm_classifier = False
        show_route_debug = False
        response_mode = "auto"
        verbosity_level = 2
        staged_streaming = True
        reasoning_depth = 2
        enable_reality_grounding = bool(core_status.get("config", {}).get("enable_reality_grounding", True))
        enable_reality_first_reasoning = bool(core_status.get("config", {}).get("enable_reality_first_reasoning", True))
        epistemic_mode = str(core_status.get("config", {}).get("epistemic_mode") or "auto")
        if epistemic_mode not in ["auto", "strict_fact", "theoretical", "science_fiction", "research"]:
            epistemic_mode = "auto"
        show_grounding_notes = bool(core_status.get("config", {}).get("show_grounding_notes", True))
        max_context_chars = int(core_status.get("config", {}).get("max_context_chars") or 12000)
        recent_message_limit = 8
        knowledge_top_k = 3
        knowledge_use_ai = False
        reality_research_enabled = bool(core_status.get("config", {}).get("enable_reality_research_agent", True))
        reality_research_depth = "Standard"
        bloodhound_enabled = bool(core_status.get("config", {}).get("enable_bloodhound_search", True))
        bloodhound_depth = "Standard"
        bloodhound_max_results = int(core_status.get("config", {}).get("max_search_results") or 50)
        bloodhound_follow_links = bool(core_status.get("config", {}).get("enable_link_following", True))
        bloodhound_enable_cache = bool(core_status.get("config", {}).get("enable_search_cache", True))
        bloodhound_enable_onion = bool(core_status.get("config", {}).get("enable_onion_search", False))

        manual_disabled = bool(auto_precision_mode)
        with st.expander("Advanced Overrides", expanded=not auto_precision_mode):
            if auto_precision_mode:
                st.caption("Turn off Auto Precision Mode to make these manual answer controls active.")
            st.markdown("**Context and routing**")
            use_memory = st.checkbox("Use adaptive memory", value=use_memory, disabled=manual_disabled)
            use_knowledge_for_chat = st.checkbox("Use local knowledge in chat", value=use_knowledge_for_chat, disabled=manual_disabled)
            use_web_for_chat = st.checkbox("Web search from chat commands", value=use_web_for_chat, disabled=manual_disabled)
            show_sources = st.checkbox("Show sources", value=show_sources, disabled=manual_disabled)
            enable_router = st.checkbox("Enable Nexus Router", value=enable_router, disabled=manual_disabled)
            show_perf_timings = st.checkbox("Show performance timings", value=show_perf_timings, disabled=manual_disabled)
            advanced_mode = st.checkbox("Advanced mode", value=advanced_mode, disabled=manual_disabled)
            demo_mode = st.checkbox("Demo mode", value=demo_mode, help="Load sample data for demonstration")
            generation_timeout = st.number_input(
                "Model timeout (seconds)",
                min_value=300,
                max_value=1800,
                value=int(generation_timeout),
                step=60,
                key="ollama_generation_timeout_seconds_v2",
                help="How long the app waits for Ollama to finish loading and generating a reply.",
            )
            god_mode = st.checkbox(
                "Advanced routing",
                value=god_mode,
                disabled=manual_disabled,
                help="Routes prompts with stronger specificity and less filler while keeping the app stable.",
            )
            freedom_level = st.select_slider(
                "Response detail",
                options=["balanced", "bold", "max_capability"],
                value=freedom_level,
                disabled=manual_disabled,
            )
            use_llm_classifier = st.checkbox(
                "Use local model to refine route classification",
                value=use_llm_classifier,
                disabled=manual_disabled or not status.models,
            )
            show_route_debug = st.checkbox("Show routing debug", value=show_route_debug, disabled=manual_disabled)

            st.caption("What the assistant may talk about is not set here. See Settings, Behaviour.")
            st.markdown("**Response controls**")
            response_mode = st.selectbox(
                "Response mode",
                RESPONSE_MODES,
                index=0,
                disabled=manual_disabled,
                format_func=lambda value: {
                    "auto": "Auto",
                    "short": "Short",
                    "standard": "Standard",
                    "deep": "Deep",
                    "surgeon": "Surgeon",
                    "research": "Research",
                }.get(value, value.title()),
                help="Auto lets Cognitive Nexus choose response size and structure from the request.",
            )
            verbosity_level = st.slider("Verbosity", 1, 5, int(verbosity_level), disabled=manual_disabled, help="Higher values allow longer answers when useful.")
            staged_streaming = st.checkbox(
                "Immediate streaming acknowledgement",
                value=staged_streaming,
                disabled=manual_disabled,
                help="Shows a short visible acknowledgement before slower deep/research responses.",
            )
            reasoning_depth = st.slider(
                "Reasoning depth",
                1,
                5,
                int(reasoning_depth),
                disabled=manual_disabled,
                help="Controls how much structured rationale the model is asked to include in the final answer.",
            )
            enable_reality_grounding = st.checkbox(
                "Reality grounding",
                value=enable_reality_grounding,
                disabled=manual_disabled,
                help="Audits generated answers for claims, hallucination risk, speculation, contradiction, and confidence.",
            )
            enable_reality_first_reasoning = st.checkbox(
                "Reality-first reasoning",
                value=enable_reality_first_reasoning,
                disabled=manual_disabled,
                help="Applies feasibility and theory/fiction constraints before the model drafts an answer.",
            )
            epistemic_mode = st.selectbox(
                "Epistemic mode",
                ["auto", "strict_fact", "theoretical", "science_fiction", "research"],
                index=["auto", "strict_fact", "theoretical", "science_fiction", "research"].index(epistemic_mode),
                disabled=manual_disabled,
            )
            show_grounding_notes = st.checkbox(
                "Show grounding notes",
                value=show_grounding_notes,
                disabled=manual_disabled or not enable_reality_grounding,
                help="Adds compact uncertainty notes to risky answers.",
            )
            max_context_chars = st.slider("Max context characters", 4000, 24000, int(max_context_chars), step=1000, disabled=manual_disabled)
            recent_message_limit = st.slider("Recent turns in context", 2, 16, int(recent_message_limit), step=2, disabled=manual_disabled)
            knowledge_top_k = st.slider("Knowledge chunks for chat", 1, 6, int(knowledge_top_k), disabled=manual_disabled)
            knowledge_use_ai = st.checkbox(
                "AI synthesis for knowledge queries",
                value=knowledge_use_ai,
                disabled=manual_disabled,
                help="Off is faster and uses extractive answers from stored sources. Turn on for slower model-written synthesis.",
            )

            st.markdown("**Research controls**")
            reality_research_enabled = st.checkbox(
                "Reality-First Research Agent",
                value=reality_research_enabled,
                disabled=manual_disabled,
                help="Routes deep research, verify, trace sources, and search-style chat commands into the source-grounded research agent.",
            )
            reality_research_depth = st.selectbox("Research agent depth", ["Quick", "Standard", "Deep", "Extreme"], index=1, disabled=manual_disabled)
            bloodhound_enabled = st.checkbox(
                "Bloodhound Search Mode",
                value=bloodhound_enabled,
                disabled=manual_disabled,
                help="Routes search/find/deep search chat commands into the deep public-web search engine.",
            )
            bloodhound_depth = st.selectbox("Search depth", ["Quick", "Standard", "Deep", "Extreme"], index=1, disabled=manual_disabled)
            bloodhound_max_results = st.slider("Bloodhound max results", 5, 150, int(bloodhound_max_results), step=5, disabled=manual_disabled)
            bloodhound_follow_links = st.checkbox("Follow relevant links", value=bloodhound_follow_links, disabled=manual_disabled)
            bloodhound_enable_cache = st.checkbox("Use search cache", value=bloodhound_enable_cache, disabled=manual_disabled)
            onion_allowed = bool(core_status.get("config", {}).get("enable_onion_search", False))
            bloodhound_enable_onion = st.checkbox(
                "Onion search",
                value=bloodhound_enable_onion,
                disabled=manual_disabled or not onion_allowed,
                help="Controlled by ENABLE_ONION_SEARCH/config. Public web search continues if Tor is unavailable.",
            )

            st.markdown("**Provider and local service overrides**")
            selected_provider_order = st.multiselect(
                "Provider fallback order",
                provider_options,
                default=configured_order,
                help="The backend tries providers in this order. Hugging Face stays local and lazy-disabled unless configured.",
            )
            provider_order = normalize_provider_order(selected_provider_order, provider_options)
            st.caption(f"Active order: {' -> '.join(provider_order)}")
            allow_cloud_fallback = st.checkbox(
                "Allow cloud fallback",
                value=allow_cloud_fallback,
                help=(
                    "Off (default): if the local model fails, the app says so and your prompt, with any memory "
                    "or document text in it, stays on this machine. On: a configured OpenAI or Anthropic "
                    "provider lower in the order may answer instead. A cloud provider you put first in the "
                    "order is always used."
                ),
            )
            if demo_safe_mode:
                st.caption("ComfyUI URL: local service hidden")
                st.caption("HF local model: local model path hidden" if hf_local_model else "HF local model: not configured")
            else:
                comfyui_url = st.text_input("ComfyUI URL", value=configured_comfyui_url)
                hf_local_model = st.text_input(
                    "HF local model",
                    value=configured_hf_local_model,
                    help="Optional local Transformers model name/path. Leave blank to keep this provider disabled.",
                )

            if st.button("Save Runtime Settings"):
                runtime_config = dict(get_nexus_core().config)
                runtime_config.update(
                    {
                        "provider_order": provider_order,
                        "allow_cloud_fallback": bool(allow_cloud_fallback),
                        "max_context_chars": int(max_context_chars),
                        "recent_message_limit": int(recent_message_limit),
                        "comfyui_url": comfyui_url.rstrip("/"),
                        "hf_local_model": hf_local_model.strip(),
                        "enable_reality_grounding": enable_reality_grounding,
                        "enable_reality_first_reasoning": enable_reality_first_reasoning,
                        "epistemic_mode": epistemic_mode,
                        "show_grounding_notes": show_grounding_notes,
                        "enable_reality_research_agent": reality_research_enabled,
                        "enable_bloodhound_search": bloodhound_enabled,
                        "max_search_results": int(bloodhound_max_results),
                        "enable_search_cache": bloodhound_enable_cache,
                        "enable_link_following": bloodhound_follow_links,
                    }
                )
                save_runtime_config(runtime_config)
                clear_runtime_caches()
                st.success("Runtime settings saved.")
                st.rerun()

        provider_health = {
            str(provider.get("name")): bool(provider.get("available"))
            for provider in core_status.get("providers", [])
        }
        primary_available = any(
            provider_health.get(provider)
            for provider in provider_order
            if provider != "fallback"
        )
        if not primary_available:
            st.warning("No model provider is ready. Chat will show a fallback notice until a local or cloud provider works.")
        st.caption(
            data_locality_caption(
                provider_order,
                bool(allow_cloud_fallback),
                [name for name in ("openai", "anthropic") if provider_health.get(name)],
            )
        )

        st.subheader("Persona")
        profile = chat_profile
        profile.enabled = st.checkbox("Use saved chat persona", value=profile.enabled)
        st.caption(f"Chat voice: {profile.assistant_name} for {profile.user_name}")

        creative_model = selected_model or ""
        technical_model = selected_model or ""
        sensitive_model = selected_model or ""
        current_info_model = selected_model or ""
        if status.models:
            with st.expander("Model routing", expanded=False):
                creative_model = _select_model_option("Creative / fiction model", status.models, selected_model or status.models[0])
                technical_model = _select_model_option("Technical / coding model", status.models, selected_model or status.models[0])
                sensitive_model = _select_model_option("Sensitive topic model", status.models, selected_model or status.models[0])
                current_info_model = _select_model_option("Current-info synthesis model", status.models, selected_model or status.models[0])

        st.subheader("Diagnostics")
        st.metric("Images", inventory["generated_images"])
        st.metric("Knowledge chunks", inventory["research_chunks"])
        if image_status["available"]:
            st.caption(f"Image provider: {image_status['label']}")
        else:
            st.caption(image_status["message"])

        if st.button("Clear chat", key="sidebar_clear_chat", width="stretch"):
            clear_chat_state()
            st.rerun()
        if st.button("Reset session", key="sidebar_reset_session", width="stretch"):
            reset_session_state()
            clear_runtime_caches()
            st.rerun()
        if st.button("Refresh app", width="stretch"):
            clear_runtime_caches()
            st.rerun()

        return {
            "provider_ready": status.available and bool(status.models),
            "ollama_running": status.available,
            "selected_model": selected_model,
            "base_url": status.base_url,
            "provider_message": status.message,
            "use_memory": use_memory,
            "use_knowledge_for_chat": use_knowledge_for_chat,
            "knowledge_top_k": int(knowledge_top_k),
            "knowledge_use_ai": bool(knowledge_use_ai),
            "use_web_for_chat": use_web_for_chat,
            "show_sources": show_sources,
            "show_perf_timings": show_perf_timings,
            "advanced_mode": advanced_mode,
            "demo_mode": demo_mode,
            "demo_safe_mode": demo_safe_mode,
            "auto_precision_mode": auto_precision_mode,
            "generation_timeout": float(generation_timeout),
            "provider_order": provider_order,
            "allow_cloud_fallback": bool(allow_cloud_fallback),
            "throughput_mode": throughput_mode,
            "target_tokens_per_second": int(target_tokens_per_second),
            "max_context_chars": int(max_context_chars),
            "recent_message_limit": int(recent_message_limit),
            "response_mode": response_mode,
            "verbosity_level": int(verbosity_level),
            "reasoning_depth": int(reasoning_depth),
            "staged_streaming": bool(staged_streaming),
            "enable_response_self_critic": True,
            "enable_reality_grounding": bool(enable_reality_grounding),
            "enable_reality_first_reasoning": bool(enable_reality_first_reasoning),
            "enable_reality_research_agent": bool(reality_research_enabled),
            "epistemic_mode": epistemic_mode,
            "show_grounding_notes": bool(show_grounding_notes),
            "enable_bloodhound_search": bool(bloodhound_enabled),
            "bloodhound_depth": bloodhound_depth,
            "bloodhound_max_results": int(bloodhound_max_results),
            "bloodhound_timeout_seconds": int(core_status.get("config", {}).get("search_timeout_seconds") or 20),
            "bloodhound_follow_links": bool(bloodhound_follow_links),
            "bloodhound_enable_cache": bool(bloodhound_enable_cache),
            "bloodhound_enable_onion": bool(bloodhound_enable_onion),
            "hf_local_model": hf_local_model.strip(),
            "reality_research_depth": reality_research_depth,
            "reality_research_max_sources": int(bloodhound_max_results),
            "reality_research_follow_links": bool(bloodhound_follow_links),
            "reality_research_save_memory": True,
            "reality_research_show_weak": True,
            "reality_research_use_ai": True,
            "comfyui_url": comfyui_url.rstrip("/"),
            "chat_profile": profile,
            "router_config": RouterConfig(
                enabled=enable_router,
                god_mode=god_mode,
                freedom_level=freedom_level,
                use_llm_classifier=use_llm_classifier,
                show_debug=show_route_debug,
                default_model=selected_model or "",
                creative_model=creative_model,
                technical_model=technical_model,
                sensitive_model=sensitive_model,
                current_info_model=current_info_model,
            ),
        }
