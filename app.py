"""Cognitive Nexus Streamlit dashboard."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Optional
import streamlit as st

from modules.chat_profile import (
    ChatProfile,
    build_capability_greeting,
    build_chat_system_prompt,
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
    generate_with_ollama,
    get_provider_inventory,
)
from modules.research import (
    get_research_module,
    ingest_text,
    process_url,
    query_knowledge,
)
from modules.utils import format_history_for_prompt
from modules.web_research import run_research_session
from nexus_router import (
    CATEGORY_LABELS,
    RouterConfig,
    build_routed_prompt,
    get_prompt_template_examples,
    route_message,
)

try:
    from cognitive_nexus.adaptation import AdaptiveMemoryManager
except Exception:  # pragma: no cover - optional legacy module
    AdaptiveMemoryManager = None  # type: ignore

st.set_page_config(page_title="Local AI Chatbot", page_icon="🧠", layout="wide")


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
    ):
        cached_func.clear()


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


def render_sidebar(status, inventory: dict[str, Any], image_status: dict[str, Any], chat_profile: ChatProfile) -> dict[str, Any]:
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
            "Max creative detail",
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

        # ====================== ADDED UNHINGED CONTROLS ======================
        st.subheader("Content Controls")
        profile = chat_profile
        
        profile.allow_extreme_adult_content = st.checkbox(
            "Extreme Adult Content (raw vulgar, non-con, gore, snuff, taboo kinks)",
            value=getattr(profile, 'allow_extreme_adult_content', True),
        )
        profile.allow_illegal_topics = st.checkbox(
            "Illegal Topics Allowed (drugs, synth, crime, weapons, hacking)",
            value=getattr(profile, 'allow_illegal_topics', True),
        )

        if st.button("Save Content Filters"):
            save_chat_profile(profile)
            st.success("Unhinged filters saved")
            st.rerun()
        # ====================== END ADDITIONS ======================

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
            "use_web_for_chat": use_web_for_chat,
            "show_sources": show_sources,
            "show_perf_timings": show_perf_timings,
            "generation_timeout": float(generation_timeout),
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
    system_prompt = build_chat_system_prompt(settings["chat_profile"])
    history_prompt = format_history_for_prompt(get_messages(), user_message)
    if settings["use_memory"]:
        memory = get_adaptive_memory()
        if memory is not None:
            try:
                signals = memory.extract_turn_signals(user_message, get_messages())
                memory.observe_turn(user_message, signals)
                bundle = memory.build_context_bundle(
                    user_message,
                    recent_messages=get_messages(),
                    chat_history=load_legacy_history(),
                    topic_knowledge={},
                    learned_facts={},
                    signals=signals,
                )
                system_prompt = f"{system_prompt}\n\n{bundle.rendered_context}"
            except Exception as exc:
                system_prompt = f"{system_prompt}\n\nMemory note: adaptive memory was unavailable for this turn: {exc}"
    return build_routed_prompt(
        user_message=user_message,
        base_system_prompt=system_prompt,
        history_prompt=history_prompt,
        route=route_decision,
        chat_profile=settings["chat_profile"],
        config=settings["router_config"],
    )


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
    ai_callback = None
    chosen_model = model_override or settings["selected_model"]
    if settings["provider_ready"] and chosen_model:
        ai_callback = lambda prompt: generate_with_ollama(
            prompt,
            chosen_model,
            settings["base_url"],
            timeout=settings.get("generation_timeout", 300.0),
        )
    research = run_research_session(
        query,
        max_results=5,
        scrape_pages=True,
        summarize_with_ai=True,
        save_locally=True,
        save_to_memory=True,
        ai_callback=ai_callback,
    )
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
    if is_capability_question(user_message):
        response = build_capability_greeting(settings["chat_profile"])
        record_perf("chat.capability_response", time.perf_counter() - started, settings)
        return response

    memory = get_adaptive_memory()
    memory_command = None
    if settings["use_memory"] and memory is not None:
        try:
            memory_command = memory.handle_memory_command(user_message)
        except Exception:
            memory_command = None
    if memory_command:
        record_perf("chat.memory_command", time.perf_counter() - started, settings)
        return memory_command

    router_config = settings["router_config"]
    classifier = None
    if router_config.use_llm_classifier and settings["provider_ready"] and router_config.default_model:
        classifier = lambda prompt: generate_with_ollama(
            prompt=prompt,
            model=router_config.default_model,
            base_url=settings["base_url"],
            options={"temperature": 0.1},
            timeout=settings.get("generation_timeout", 300.0),
        )

    route_decision = route_message(user_message, router_config, classifier=classifier)

    st.session_state.last_route_decision = {
        "category": route_decision.category,
        "label": CATEGORY_LABELS.get(route_decision.category, route_decision.category),
        "reason": route_decision.reason,
        "confidence": route_decision.confidence,
        "model": route_decision.model,
        "requires_web_search": route_decision.requires_web_search,
        "search_query": route_decision.search_query,
        "safety_mode": route_decision.safety_mode,
        "tags": route_decision.tags,
    }

    search_query = route_decision.search_query or (should_run_chat_search(user_message) if settings["use_web_for_chat"] else None)
    if settings["use_web_for_chat"] and (route_decision.requires_web_search or search_query):
        response = answer_with_web_search(search_query or user_message, settings, model_override=route_decision.model or settings["selected_model"])
        record_perf("chat.web_search_response", time.perf_counter() - started, settings)
        return response

    active_model = route_decision.model or settings["selected_model"]
    if not settings["provider_ready"] or not active_model:
        response = fallback_response()
        record_perf("chat.fallback_response", time.perf_counter() - started, settings)
        return response

    prompt = build_chat_prompt(user_message, settings, route_decision)
    
    # ====================== ADDED: GOD MODE TEMPERATURE BOOST ======================
    options = dict(route_decision.generation_options or {})
    options.setdefault("num_predict", 220)
    options.setdefault("num_ctx", 2048)
    if getattr(router_config, 'god_mode', False):
        options["temperature"] = max(options.get("temperature", 0.85), 1.2)
    # ====================== END ADDITION ======================

    response = generate_with_ollama(
        prompt=prompt,
        model=active_model,
        base_url=settings["base_url"],
        options=options,
        timeout=settings.get("generation_timeout", 300.0),
    )
    record_perf("chat.ollama_response", time.perf_counter() - started, settings)
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

    user_message = st.chat_input("Message Cognitive Nexus")
    if not user_message:
        return

    add_message("user", user_message)
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = generate_chat_response(user_message, settings)
        st.markdown(response)

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
            result = generate_images(req)
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
        ai_callback = None
        if summarize and settings["provider_ready"] and settings["selected_model"]:
            ai_callback = lambda prompt: generate_with_ollama(
                prompt,
                settings["selected_model"],
                settings["base_url"],
                timeout=settings.get("generation_timeout", 600.0),
            )
        with st.status("Researching...", expanded=True) as status:
            research = run_research_session(
                query,
                max_results=max_results,
                scrape_pages=scrape_pages,
                summarize_with_ai=summarize,
                save_locally=save_locally,
                save_to_memory=save_to_memory,
                ai_callback=ai_callback,
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
        result = query_knowledge(
            module,
            query,
            model=settings["selected_model"],
            base_url=settings["base_url"],
            provider_ready=settings["provider_ready"],
            top_k=top_k,
        )
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


def render_logs_status_tab(status, inventory: dict[str, Any], image_status: dict[str, Any]) -> None:
    st.subheader("Logs / Status")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Providers")
        st.json(get_cached_provider_inventory())
        st.markdown("### Image Provider")
        st.json(image_status)
        st.markdown("### Image Providers")
        st.json(get_cached_image_providers())
    with col2:
        st.markdown("### Project")
        st.json(inventory)
        st.markdown("### Environment")
        st.json(get_environment_status())
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
    status = get_cached_ollama_status()
    inventory = get_cached_project_inventory()
    image_status = get_cached_image_provider()
    chat_profile = load_chat_profile()
    settings = render_sidebar(status, inventory, image_status, chat_profile)

    st.title("Cognitive Nexus 🔥")
    st.caption("Local AI dashboard")

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
        render_logs_status_tab(status, inventory, image_status)
    with tabs[8]:
        render_settings_tab(settings)


if __name__ == "__main__":
    main()
