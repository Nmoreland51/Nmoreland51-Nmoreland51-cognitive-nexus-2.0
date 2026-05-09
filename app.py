"""Cognitive Nexus Streamlit dashboard."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Optional
import streamlit as st

from modules.chat_profile import (
    ChatProfile,
    load_chat_profile,
    save_chat_profile,
)
from modules.image_gen import (
    ImageGenerationRequest,
    detect_image_provider,
    detect_image_providers,
    generate_images,
    list_generated_images,
)
from modules.memory import (
    add_message,
    clear_messages,
    clear_session_history_file,
    get_messages,
    initialize_chat_state,
    load_legacy_history,
    load_session_history_file,
    save_session_history,
)
from modules.project_status import (
    PROJECT_ROOT,
    get_environment_status,
    get_project_inventory,
    list_project_tools,
    tail_file,
)
from modules.providers import (
    check_ollama_status,
    fallback_response,
    get_provider_inventory,
)
from modules.research import (
    get_research_module,
    ingest_text,
    process_url,
)
from modules.nexus_config import save_runtime_config
from modules.nexus_core import NexusCore
from modules.response_planner import RESPONSE_MODES
from nexus_router import (
    CATEGORY_LABELS,
    RouterConfig,
    get_prompt_template_examples,
)

try:
    from cognitive_nexus.adaptation import AdaptiveMemoryManager
except Exception:  # pragma: no cover - optional legacy module
    AdaptiveMemoryManager = None  # type: ignore

st.set_page_config(page_title="Local AI Chatbot", page_icon="🧠", layout="wide")


@st.cache_resource
def get_nexus_core() -> NexusCore:
    return NexusCore(PROJECT_ROOT)


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_core_status(provider_order: tuple[str, ...]) -> dict[str, Any]:
    return get_nexus_core().status_snapshot(list(provider_order))


@st.cache_resource
def get_adaptive_memory():
    if AdaptiveMemoryManager is None:
        return None
    return AdaptiveMemoryManager(Path("data"))


@st.cache_resource
def get_cached_research_module():
    return get_research_module()


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_ollama_status():
    return check_ollama_status()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_project_inventory() -> dict[str, Any]:
    return get_project_inventory()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_image_provider() -> dict[str, Any]:
    return detect_image_provider()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_image_providers() -> list[dict[str, Any]]:
    return detect_image_providers()


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_gallery(limit: int) -> list[dict[str, Any]]:
    return list_generated_images(limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_provider_inventory() -> list[dict[str, Any]]:
    return get_provider_inventory()


@st.cache_data(ttl=60, show_spinner=False)
def get_cached_project_tools() -> list[dict[str, str]]:
    return list_project_tools()


@st.cache_data(ttl=10, show_spinner=False)
def get_cached_log_files() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("*.log"))


def clear_runtime_caches() -> None:
    for cached_func in (
        get_cached_ollama_status,
        get_cached_project_inventory,
        get_cached_image_provider,
        get_cached_image_providers,
        get_cached_gallery,
        get_cached_provider_inventory,
        get_cached_project_tools,
        get_cached_log_files,
        get_cached_core_status,
    ):
        cached_func.clear()
    get_nexus_core().refresh_config()


def record_perf(label: str, elapsed: float, settings: Optional[dict[str, Any]] = None) -> None:
    if settings is not None and not settings.get("show_perf_timings"):
        return
    timings = st.session_state.setdefault("perf_timings", [])
    timings.append({"label": label, "seconds": round(elapsed, 3)})
    del timings[:-30]


def get_chat_model(models: list[str]) -> str:
    preferred_models = [
        "BlackHillsInfoSec/llama-3.1-8b-abliterated:latest",
        "mannix/llama3.1-8b-abliterated:latest",
        "BlackHillsInfoSec/llama-3.1-8b-abliterated",
        "mannix/llama3.1-8b-abliterated",
        "dolphin-llama3:8b",
        "dolphin-llama3:latest",
        "dolphin-llama3:70b",
    ]
    for preferred in preferred_models:
        if preferred in models:
            return preferred
    non_embedding = [model for model in models if "embed" not in model.lower()]
    return non_embedding[0] if non_embedding else (models[0] if models else "")


def clear_chat_state() -> None:
    clear_messages()
    clear_session_history_file()


def restore_persisted_chat() -> None:
    initialize_chat_state()
    if get_messages():
        return
    for message in load_session_history_file():
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
            add_message(str(message["role"]), str(message.get("content", "")))


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
            st.success("Ollama available")
        elif status.available:
            st.warning("Ollama running, no models")
        else:
            st.error("Ollama offline")
        st.caption(status.message)
        st.caption(f"Endpoint: {status.base_url}")

        selected_model = None
        if status.models:
            default_model = get_chat_model(status.models)
            default_index = status.models.index(default_model) if default_model in status.models else 0
            selected_model = st.selectbox("Chat model", status.models, index=default_index)
        else:
            st.info("Fallback mode is active.")

        st.subheader("Settings")
        use_memory = st.checkbox("Use adaptive memory", value=False)
        use_knowledge_for_chat = st.checkbox("Use local knowledge in chat", value=True)
        use_web_for_chat = st.checkbox("Web search from chat commands", value=True)
        show_sources = st.checkbox("Show sources", value=True)
        enable_router = st.checkbox("Enable Nexus Router", value=True)
        show_perf_timings = st.checkbox("Show performance timings", value=False)
        generation_timeout = st.number_input(
            "Model timeout (seconds)",
            min_value=300,
            max_value=1800,
            value=600,
            step=60,
            key="ollama_generation_timeout_seconds_v2",
            help="How long the app waits for Ollama to finish loading and generating a reply.",
        )
        god_mode = st.checkbox(
            "Godmode",
            value=False,
            help="Routes prompts with stronger specificity and less filler while keeping the app stable.",
        )
        freedom_level = st.select_slider(
            "Response detail",
            options=["balanced", "bold", "max_capability"],
            value="bold",
        )
        use_llm_classifier = st.checkbox(
            "Use local model to refine route classification",
            value=False,
            disabled=not status.models,
        )
        show_route_debug = st.checkbox("Show routing debug", value=False)

        st.subheader("Response Controls")
        profile = chat_profile
        response_mode = st.selectbox(
            "Response mode",
            RESPONSE_MODES,
            index=0,
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
        verbosity_level = st.slider("Verbosity", 1, 5, 2, help="Higher values allow longer answers when useful.")
        reasoning_depth = st.slider(
            "Reasoning depth",
            1,
            5,
            2,
            help="Controls how much structured rationale the model is asked to include in the final answer.",
        )
        staged_streaming = st.checkbox(
            "Immediate streaming acknowledgement",
            value=True,
            help="Shows a short visible acknowledgement before slower deep/research responses.",
        )
        max_context_chars = st.slider(
            "Max context characters",
            min_value=4000,
            max_value=24000,
            value=int(core_status.get("config", {}).get("max_context_chars") or 12000),
            step=1000,
        )
        recent_message_limit = st.slider("Recent turns in context", 2, 16, 8, step=2)
        knowledge_top_k = st.slider("Knowledge chunks for chat", 1, 6, 3)

        st.subheader("Bloodhound Search")
        bloodhound_enabled = st.checkbox(
            "Bloodhound Search Mode",
            value=bool(core_status.get("config", {}).get("enable_bloodhound_search", True)),
            help="Routes search/find/deep search chat commands into the deep public-web search engine.",
        )
        bloodhound_depth = st.selectbox("Search depth", ["Quick", "Standard", "Deep", "Extreme"], index=1)
        bloodhound_max_results = st.slider(
            "Bloodhound max results",
            min_value=5,
            max_value=150,
            value=int(core_status.get("config", {}).get("max_search_results") or 50),
            step=5,
        )
        bloodhound_follow_links = st.checkbox(
            "Follow relevant links",
            value=bool(core_status.get("config", {}).get("enable_link_following", True)),
        )
        bloodhound_enable_cache = st.checkbox(
            "Use search cache",
            value=bool(core_status.get("config", {}).get("enable_search_cache", True)),
        )
        onion_allowed = bool(core_status.get("config", {}).get("enable_onion_search", False))
        bloodhound_enable_onion = st.checkbox(
            "Onion search",
            value=onion_allowed,
            disabled=not onion_allowed,
            help="Controlled by ENABLE_ONION_SEARCH/config. Public web search continues if Tor is unavailable.",
        )

        provider_options = ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]
        configured_order = [
            item
            for item in core_status.get("config", {}).get("provider_order", provider_options)
            if item in provider_options
        ] or ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]
        provider_order = st.multiselect(
            "Provider fallback order",
            provider_options,
            default=configured_order,
            help="The backend tries providers in this order and falls back instead of leaving a dead tab.",
        )
        if "fallback" not in provider_order:
            provider_order.append("fallback")
        comfyui_url = st.text_input(
            "ComfyUI URL",
            value=str(core_status.get("config", {}).get("comfyui_url") or "http://127.0.0.1:8188"),
        )

        if st.button("Save Runtime Settings"):
            runtime_config = dict(get_nexus_core().config)
            runtime_config.update(
                {
                    "provider_order": provider_order,
                    "max_context_chars": int(max_context_chars),
                    "recent_message_limit": int(recent_message_limit),
                    "comfyui_url": comfyui_url.rstrip("/"),
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

        st.subheader("Persona")
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

        if st.button("Clear chat", width="stretch"):
            clear_chat_state()
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
            "use_web_for_chat": use_web_for_chat,
            "show_sources": show_sources,
            "show_perf_timings": show_perf_timings,
            "generation_timeout": float(generation_timeout),
            "provider_order": provider_order,
            "max_context_chars": int(max_context_chars),
            "recent_message_limit": int(recent_message_limit),
            "response_mode": response_mode,
            "verbosity_level": int(verbosity_level),
            "reasoning_depth": int(reasoning_depth),
            "staged_streaming": bool(staged_streaming),
            "enable_bloodhound_search": bool(bloodhound_enabled),
            "bloodhound_depth": bloodhound_depth,
            "bloodhound_max_results": int(bloodhound_max_results),
            "bloodhound_timeout_seconds": int(core_status.get("config", {}).get("search_timeout_seconds") or 20),
            "bloodhound_follow_links": bool(bloodhound_follow_links),
            "bloodhound_enable_cache": bool(bloodhound_enable_cache),
            "bloodhound_enable_onion": bool(bloodhound_enable_onion),
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


def build_chat_prompt(user_message: str, settings: dict[str, Any], route_decision) -> str:
    prompt, _context = get_nexus_core().build_chat_prompt(user_message, get_messages(), settings, route_decision)
    return prompt


def should_run_chat_search(message: str) -> Optional[str]:
    lowered = message.lower().strip()
    prefixes = [
        "search the web for",
        "search web for",
        "web search for",
        "look up",
        "find online",
        "find current info about",
        "research",
        "latest",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return message[len(prefix) :].strip() or message
    if any(token in lowered for token in ["latest ", "current ", "recent ", "today ", "breaking "]):
        return message.strip()
    return None


def answer_with_web_search(query: str, settings: dict[str, Any], model_override: Optional[str] = None) -> str:
    routed_settings = dict(settings)
    if model_override:
        routed_settings["selected_model"] = model_override
    research = get_nexus_core().run_web_research(query, routed_settings, max_results=5, save_locally=True)
    if not research["results"]:
        errors = "\n".join(f"- {error}" for error in research["errors"])
        return f"I could not find web results for that query.\n\n{errors}".strip()
    answer = research["summary"]
    if settings["show_sources"]:
        sources = "\n".join(
            f"- [{item.get('title') or item.get('url')}]({item.get('url')}) ({item.get('source')})"
            for item in research["results"]
            if item.get("url")
        )
        if sources and "source" not in answer.lower():
            answer = f"{answer}\n\nSources:\n{sources}"
    saved_paths = research.get("saved_paths") or {}
    if saved_paths:
        answer = f"{answer}\n\nSaved research:\n- JSON: `{saved_paths.get('json')}`\n- Markdown: `{saved_paths.get('markdown')}`"
    return answer


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
    response = get_nexus_core().generate_chat_response(user_message, get_messages(), settings)
    st.session_state.last_route_decision = get_nexus_core().last_route_decision
    st.session_state.last_provider_result = get_nexus_core().last_provider_result
    st.session_state.last_verification = get_nexus_core().last_verification
    st.session_state.last_response_plan = get_nexus_core().last_response_plan
    record_perf("chat.central_response", time.perf_counter() - started, settings)
    return response


def render_chat_tab(settings: dict[str, Any]) -> None:
    header_col, action_col = st.columns([6, 1])
    with header_col:
        st.subheader("Chat")
    with action_col:
        if st.button("Clear Chat", key="chat_tab_clear_button", width="stretch"):
            clear_chat_state()
            st.rerun()

    for message in get_messages():
        with st.chat_message(message.get("role", "assistant")):
            st.markdown(message.get("content", ""))

    if settings["router_config"].show_debug and "last_route_decision" in st.session_state:
        with st.expander("Last route decision", expanded=False):
            st.json(st.session_state.last_route_decision)
    if "last_response_plan" in st.session_state:
        plan = st.session_state.last_response_plan or {}
        with st.expander("Response planner", expanded=False):
            metric_cols = st.columns(4)
            metric_cols[0].metric("Mode", str(plan.get("mode", "auto")))
            metric_cols[1].metric("Intent", str(plan.get("intent", "unknown")))
            metric_cols[2].metric("Max tokens", int(plan.get("max_tokens", 0) or 0))
            metric_cols[3].metric("Context", int(plan.get("num_ctx", 0) or 0))
            st.json(plan)

    user_message = st.chat_input("Message Cognitive Nexus")
    if not user_message:
        return

    add_message("user", user_message)
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        started = time.perf_counter()
        response = st.write_stream(get_nexus_core().stream_chat_response(user_message, get_messages(), settings))
        st.session_state.last_route_decision = get_nexus_core().last_route_decision
        st.session_state.last_provider_result = get_nexus_core().last_provider_result
        st.session_state.last_verification = get_nexus_core().last_verification
        st.session_state.last_response_plan = get_nexus_core().last_response_plan
        plan = st.session_state.last_response_plan or {}
        if plan:
            st.caption(
                f"Planner: {plan.get('mode', 'auto')} / {plan.get('intent', 'unknown')} "
                f"/ max {plan.get('max_tokens', '?')} tokens"
            )
        record_perf("chat.stream_response", time.perf_counter() - started, settings)

    add_message("assistant", response)
    save_session_history()


def render_image_tab() -> None:
    st.subheader("Image Generation")
    providers = get_cached_image_providers()
    provider_names = ["auto"] + [provider["name"] for provider in providers]
    provider_labels = {"auto": "Auto"}
    provider_labels.update({provider["name"]: provider.get("label", provider["name"]) for provider in providers})
    prompt = st.text_area("Prompt", height=120, placeholder="Describe the image you want to generate.")
    negative_prompt = st.text_area("Negative prompt", height=80, placeholder="Optional things to avoid.")
    col1, col2, col3 = st.columns(3)
    with col1:
        provider = st.selectbox("Provider", provider_names, format_func=lambda value: provider_labels.get(value, value))
        width = st.slider("Width", 256, 1536, 512, step=64)
        steps = st.slider("Steps", 1, 80, 25)
    with col2:
        model = st.text_input("Model name", value="")
        height = st.slider("Height", 256, 1536, 512, step=64)
        cfg_scale = st.slider("CFG scale", 1.0, 20.0, 7.0, step=0.5)
    with col3:
        style = st.selectbox("Style", ["realistic", "cinematic", "anime", "digital_art", "fantasy", "none"])
        seed_text = st.text_input("Seed", value="", placeholder="Blank = random")
        num_images = st.number_input("Number of images", min_value=1, max_value=4, value=1, step=1)
    save_outputs = st.checkbox("Save outputs", value=True)

    if st.button("Generate Images", type="primary"):
        if not prompt.strip():
            st.warning("Enter an image prompt first.")
            return
        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            st.warning("Seed must be a whole number or blank.")
            return
        req = ImageGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            num_images=int(num_images),
            provider=provider,
            model=model,
            style=style,
            save_outputs=save_outputs,
        )
        with st.spinner("Generating image..."):
            started = time.perf_counter()
            result = get_nexus_core().generate_image(req)
            record_perf("image.generate", time.perf_counter() - started)
            get_cached_gallery.clear()
        if not result.get("success"):
            st.error(result.get("error") or "Image generation failed.")
        else:
            st.success("Image generation complete.")
            for item in result.get("saved", []):
                image_path = item.get("file_path")
                if image_path:
                    st.image(image_path, caption=item.get("prompt", prompt), width="stretch")
                with st.expander("Metadata", expanded=False):
                    st.json(item)
            st.divider()
            render_gallery(limit=24)

    st.divider()
    render_comfyui_workflow_section()


def render_comfyui_workflow_section() -> None:
    st.subheader("ComfyUI Workflows")
    core = get_nexus_core()
    status = core.comfyui.detect()
    if status.available:
        st.success(status.message)
    else:
        st.info(f"{status.message} Start ComfyUI and confirm the URL in Settings.")

    uploaded = st.file_uploader("Upload ComfyUI API workflow JSON", type=["json"], key="comfyui_workflow_upload")
    if uploaded and st.button("Save uploaded workflow", key="save_comfy_workflow"):
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            path = core.comfyui.save_workflow(payload, uploaded.name)
            st.success(f"Saved workflow: {path}")
        except Exception as exc:
            st.error(f"Could not save workflow: {exc}")

    workflows = core.comfyui.list_workflows()
    selected_workflow = None
    if workflows:
        selected_workflow = st.selectbox("Saved workflow", workflows, format_func=lambda path: path.name)
    else:
        st.caption("No saved workflows yet. Export an API-format workflow from ComfyUI and upload it here.")

    prompt = st.text_area("Workflow prompt", height=90, key="comfy_prompt")
    negative_prompt = st.text_area("Workflow negative prompt", height=60, key="comfy_negative_prompt")
    timeout = st.slider("Workflow timeout seconds", 30, 600, 240, step=30)

    disabled = not status.available or selected_workflow is None
    if st.button("Run ComfyUI Workflow", type="primary", disabled=disabled):
        try:
            workflow = core.comfyui.load_workflow(Path(selected_workflow))
            with st.status("Running ComfyUI workflow...", expanded=True) as run_status:
                result = core.run_comfyui_workflow(
                    workflow=workflow,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    timeout=float(timeout),
                )
                run_status.update(label="ComfyUI workflow complete", state="complete" if result.success else "error")
            if not result.success:
                st.error(result.error or "ComfyUI workflow failed.")
                return
            st.success(f"ComfyUI prompt id: {result.prompt_id}")
            for image in result.images:
                path = image.get("path")
                if path and Path(path).exists():
                    st.image(path, caption=Path(path).name, width="stretch")
            if result.metadata_path:
                st.caption(f"Metadata saved: {result.metadata_path}")
        except Exception as exc:
            st.error(f"ComfyUI workflow failed: {exc}")


def render_gallery(limit: int = 50) -> None:
    st.subheader("Gallery")
    items = get_cached_gallery(limit)
    if not items:
        st.info("No generated images found yet.")
        return
    cols = st.columns(3)
    for index, item in enumerate(items):
        with cols[index % 3]:
            path = item.get("file_path") or item.get("path")
            if path and Path(path).exists():
                st.image(path, caption=item.get("prompt", Path(path).name), width="stretch")
            st.caption(item.get("timestamp") or item.get("created_at") or "")
            st.caption(item.get("provider", "unknown"))


def render_web_research_tab(settings: dict[str, Any]) -> None:
    st.subheader("Web Research")
    query = st.text_input("Search query", placeholder="What should Cognitive Nexus research?")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        max_results = st.slider("Results", 1, 10, 5)
    with col2:
        scrape_pages = st.checkbox("Scrape pages", value=True)
    with col3:
        summarize = st.checkbox("Summarize with AI", value=True)
    with col4:
        save_locally = st.checkbox("Save locally", value=True)
    save_to_memory = st.checkbox("Add cleaned research to local knowledge memory", value=True)

    if st.button("Run Web Research", type="primary"):
        if not query.strip():
            st.warning("Enter a search query first.")
            return
        with st.status("Researching...", expanded=True) as status:
            research = get_nexus_core().run_web_research(
                query,
                max_results=max_results,
                scrape_pages=scrape_pages,
                summarize_with_ai=summarize,
                save_locally=save_locally,
                save_to_memory=save_to_memory,
                settings=settings,
            )
            status.update(label="Research complete", state="complete")
        if research["errors"]:
            st.warning("\n".join(research["errors"]))
        st.markdown("### Summary")
        st.markdown(research["summary"])
        if research.get("saved_paths"):
            st.success(f"Saved JSON: {research['saved_paths'].get('json')}")
            st.success(f"Saved Markdown: {research['saved_paths'].get('markdown')}")
        st.markdown("### Sources")
        for result in research["results"]:
            st.markdown(f"**[{result.get('title') or result.get('url')}]({result.get('url')})**")
            st.caption(result.get("source", ""))
            st.write(result.get("snippet", ""))
        with st.expander("Scraped page previews", expanded=False):
            for page in research["scraped_pages"]:
                st.markdown(f"**[{page.get('title') or page.get('url')}]({page.get('url')})**")
                if page.get("success"):
                    st.write(page.get("excerpt", ""))
                else:
                    st.warning(page.get("error", "Scrape failed."))


def render_files_knowledge_tab(settings: dict[str, Any]) -> None:
    st.subheader("Files / Knowledge")
    module = get_cached_research_module()
    url = st.text_input("Ingest URL")
    if st.button("Process URL"):
        try:
            result = process_url(module, url)
            if result.get("status") == "success":
                st.success(f"Stored {result.get('chunks_count', 0)} chunks from {result.get('title', url)}")
            else:
                st.error(result.get("error", "URL processing failed."))
        except Exception as exc:
            st.error(str(exc))

    uploaded = st.file_uploader("Upload text, markdown, JSON, or CSV", type=["txt", "md", "json", "csv"])
    if uploaded and st.button("Ingest uploaded file"):
        text = uploaded.getvalue().decode("utf-8", errors="ignore")
        result = ingest_text(module, name=uploaded.name, text=text, source_type="upload")
        if result.get("status") == "success":
            st.success(f"Stored {result.get('chunks_count', 0)} chunks from {uploaded.name}")
        else:
            st.error(result.get("error", "File ingestion failed."))

    st.divider()
    query = st.text_input("Ask local knowledge")
    top_k = st.slider("Knowledge results", 1, 10, 5)
    if st.button("Query Knowledge"):
        if not query.strip():
            st.warning("Enter a knowledge query first.")
            return
        result = get_nexus_core().answer_knowledge(query, settings, top_k=top_k)
        st.markdown(result["answer"])
        with st.expander("Retrieved chunks", expanded=False):
            st.json(result["results"])


def render_memory_tab(settings: dict[str, Any]) -> None:
    st.subheader("Memory")
    st.markdown("### Session chat")
    st.json(get_messages())
    st.markdown("### Chat persona")
    st.json(settings["chat_profile"].to_dict())
    memory = get_adaptive_memory()
    if memory is None:
        st.info("Adaptive memory module is unavailable.")
        return
    for attr in ("user_profile", "memory_candidates", "feedback_log"):
        if hasattr(memory, attr):
            with st.expander(attr, expanded=False):
                st.write(getattr(memory, attr))


def render_tools_tab() -> None:
    st.subheader("Tools / Utilities")
    tools = get_cached_project_tools()
    if not tools:
        st.info("No project tools detected.")
        return
    st.dataframe(tools, width="stretch")


def render_logs_status_tab(status, inventory: dict[str, Any], image_status: dict[str, Any], core_status: dict[str, Any]) -> None:
    st.subheader("Logs / Status")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Providers")
        st.json(get_cached_provider_inventory())
        st.markdown("### Image Provider")
        st.json(image_status)
        st.markdown("### Image Providers")
        st.json(get_cached_image_providers())
        st.markdown("### Central Provider Router")
        st.json(core_status.get("providers", []))
    with col2:
        st.markdown("### Project")
        st.json(inventory)
        st.markdown("### Environment")
        st.json(get_environment_status())
        st.markdown("### ComfyUI")
        st.json(core_status.get("comfyui", {}))
        if st.session_state.get("last_provider_result"):
            st.markdown("### Last Provider Result")
            st.json(st.session_state.last_provider_result)
        if st.session_state.get("last_verification"):
            st.markdown("### Last Verification")
            st.json(st.session_state.last_verification)
        if st.session_state.get("last_response_plan"):
            st.markdown("### Last Response Plan")
            st.json(st.session_state.last_response_plan)
    log_files = get_cached_log_files()
    if log_files:
        selected = st.selectbox("Log file", log_files, format_func=lambda path: path.name)
        st.text(tail_file(selected))
    if st.session_state.get("perf_timings"):
        st.markdown("### Performance Timings")
        st.dataframe(st.session_state.perf_timings, width="stretch")


def render_settings_tab(settings: dict[str, Any]) -> None:
    st.subheader("Settings")
    profile = settings["chat_profile"]
    with st.form("chat_profile_form"):
        enabled = st.checkbox("Enable persona", value=profile.enabled)
        user_name = st.text_input("User name", value=profile.user_name)
        assistant_name = st.text_input("Assistant name", value=profile.assistant_name)
        persona_summary = st.text_area("Persona summary", value=profile.persona_summary, height=100)
        tone_notes = st.text_area("Tone notes", value=profile.tone_notes, height=80)
        style_notes = st.text_area("Style notes", value=profile.style_notes, height=120)
        creative_min_words = st.number_input("Creative writing minimum words", min_value=0, max_value=2000, value=profile.creative_min_words)
        additional_instructions = st.text_area("Additional instructions", value=profile.additional_instructions, height=100)

        # Added fields in form
        direct_language_for_adult_fiction = st.checkbox("Allow direct language for adult fiction", value=getattr(profile, 'direct_language_for_adult_fiction', True))
        show_capability_greeting = st.checkbox("Show greeting on fresh chat", value=getattr(profile, 'show_capability_greeting', True))

        saved = st.form_submit_button("Save Persona")
        if saved:
            updated = ChatProfile(
                enabled=enabled,
                user_name=user_name,
                assistant_name=assistant_name,
                persona_summary=persona_summary,
                tone_notes=tone_notes,
                style_notes=style_notes,
                creative_min_words=int(creative_min_words),
                direct_language_for_adult_fiction=direct_language_for_adult_fiction,
                show_capability_greeting=show_capability_greeting,
                additional_instructions=additional_instructions,
                allow_extreme_adult_content=getattr(profile, "allow_extreme_adult_content", True),
                allow_illegal_topics=getattr(profile, "allow_illegal_topics", True),
            )
            save_chat_profile(updated)
            st.success("Persona saved.")
            st.rerun()

    with st.expander("Router prompt templates", expanded=False):
        st.json(get_prompt_template_examples())


def main() -> None:
    restore_persisted_chat()
    core = get_nexus_core()
    status = get_cached_ollama_status()
    inventory = get_cached_project_inventory()
    image_status = get_cached_image_provider()
    chat_profile = load_chat_profile()
    default_order = tuple(core.config.get("provider_order", ["ollama", "openai", "anthropic", "huggingface_local", "fallback"]))
    core_status = get_cached_core_status(default_order)
    settings = render_sidebar(status, inventory, image_status, chat_profile, core_status)

    st.title("Cognitive Nexus 🔥")
    st.caption("Centralized local AI control center")

    tabs = st.tabs(
        [
            "Chat",
            "Image Generation",
            "Web Research",
            "Files / Knowledge",
            "Memory",
            "Gallery",
            "Tools / Utilities",
            "Logs / Status",
            "Settings",
        ]
    )
    with tabs[0]:
        render_chat_tab(settings)
    with tabs[1]:
        render_image_tab()
    with tabs[2]:
        render_web_research_tab(settings)
    with tabs[3]:
        render_files_knowledge_tab(settings)
    with tabs[4]:
        render_memory_tab(settings)
    with tabs[5]:
        render_gallery()
    with tabs[6]:
        render_tools_tab()
    with tabs[7]:
        render_logs_status_tab(status, inventory, image_status, core_status)
    with tabs[8]:
        render_settings_tab(settings)


if __name__ == "__main__":
    main()
