"""Central server-side backend for the Cognitive Nexus Streamlit UI."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Generator, Optional

from modules.chat_profile import build_capability_greeting
from modules.comfyui_client import ComfyUIClient
from modules.context_manager import build_context_bundle, load_user_facts
from modules.image_gen import ImageGenerationRequest, generate_images
from modules.internal_prompts import build_locked_system_prompt
from modules.nexus_config import LOG_DIR, ensure_runtime_dirs, load_runtime_config
from modules.provider_router import ProviderRequest, ProviderResult, ProviderRouter
from modules.research import get_research_module, query_knowledge
from modules.response_planner import ResponsePlan, plan_response, validate_response_against_plan
from modules.response_verifier import VerificationResult, log_verification, verify_response
from modules.web_research import run_research_session
from search.bloodhound_search import (
    BloodhoundConfig,
    default_bloodhound_config,
    detect_bloodhound_query,
    format_bloodhound_markdown,
    run_bloodhound_search,
)
from nexus_router import CATEGORY_LABELS, RouterConfig, build_routed_prompt, route_message


logger = logging.getLogger(__name__)


class NexusCore:
    """One shared backend used by every Streamlit tab."""

    def __init__(self, project_root: Path | None = None) -> None:
        ensure_runtime_dirs()
        logging.basicConfig(
            filename=str(LOG_DIR / "cognitive_nexus.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.config = load_runtime_config()
        self.provider_router = ProviderRouter(self.config)
        self.comfyui = ComfyUIClient(str(self.config.get("comfyui_url", "http://127.0.0.1:8188")))
        self._research_module = None
        self._adaptive_memory = None
        self.last_route_decision: dict[str, Any] = {}
        self.last_provider_result: dict[str, Any] = {}
        self.last_verification: dict[str, Any] = {}
        self.last_response_plan: dict[str, Any] = {}

    def refresh_config(self) -> None:
        """Reload config and provider cache after settings change."""

        self.config = load_runtime_config()
        self.provider_router.config = self.config
        self.provider_router.invalidate_status_cache()
        self.comfyui = ComfyUIClient(str(self.config.get("comfyui_url", "http://127.0.0.1:8188")))

    def status_snapshot(self, provider_order: Optional[list[str]] = None) -> dict[str, Any]:
        """Return provider, ComfyUI, and runtime status for the UI."""

        providers = [item.to_dict() for item in self.provider_router.detect_all(provider_order)]
        comfy = self.comfyui.detect().to_dict()
        return {
            "providers": providers,
            "comfyui": comfy,
            "config": {
                key: self.config.get(key)
                for key in (
                    "ollama_url",
                    "openai_model",
                    "anthropic_model",
                    "hf_local_model",
                    "comfyui_url",
                    "max_context_chars",
                    "recent_message_limit",
                    "provider_order",
                    "enable_bloodhound_search",
                    "enable_onion_search",
                    "max_search_results",
                    "search_timeout_seconds",
                    "enable_search_cache",
                    "search_cache_ttl_hours",
                    "enable_link_following",
                )
            },
        }

    def get_research_module(self):
        """Lazy-load the legacy research module once."""

        if self._research_module is None:
            self._research_module = get_research_module()
        return self._research_module

    def get_adaptive_memory(self):
        """Lazy-load the optional adaptive memory manager."""

        if self._adaptive_memory is not None:
            return self._adaptive_memory
        try:
            from cognitive_nexus.adaptation import AdaptiveMemoryManager

            self._adaptive_memory = AdaptiveMemoryManager(Path("data"))
        except Exception as exc:
            logger.info("Adaptive memory unavailable: %s", exc)
            self._adaptive_memory = None
        return self._adaptive_memory

    def _capability_question(self, message: str) -> bool:
        lowered = " ".join((message or "").lower().strip().split())
        return any(
            phrase in lowered
            for phrase in (
                "what can you do",
                "what are your capabilities",
                "what can cognitive nexus do",
                "show capabilities",
            )
        )

    def _memory_context(self, user_message: str, messages: list[dict[str, str]], enabled: bool) -> tuple[str, str]:
        if not enabled:
            return "", ""
        memory = self.get_adaptive_memory()
        if memory is None:
            return "", ""
        try:
            command = memory.handle_memory_command(user_message)
            if command:
                return "", command
            signals = memory.extract_turn_signals(user_message, messages)
            memory.observe_turn(user_message, signals)
            bundle = memory.build_context_bundle(
                user_message,
                recent_messages=messages,
                chat_history=[],
                topic_knowledge={},
                learned_facts={},
                signals=signals,
            )
            return str(getattr(bundle, "rendered_context", "")), ""
        except Exception as exc:
            return f"Adaptive memory unavailable this turn: {exc}", ""

    def _retrieved_context(self, user_message: str, enabled: bool, top_k: int = 3) -> str:
        if not enabled:
            return ""
        try:
            module = self.get_research_module()
            results = module.semantic_search(user_message, top_k=top_k)
            return "\n\n".join(
                f"Source: {item.get('title') or item.get('url')}\n{str(item.get('text', ''))[:900]}"
                for item in results
            )
        except Exception as exc:
            logger.info("Knowledge retrieval unavailable: %s", exc)
            return ""

    def _provider_request(
        self,
        prompt: str,
        settings: dict[str, Any],
        route_options: dict[str, Any],
        model: str = "",
        system_prompt: str = "",
    ) -> ProviderRequest:
        return ProviderRequest(
            prompt=prompt,
            model=model or settings.get("selected_model") or "",
            provider_order=list(settings.get("provider_order") or self.config.get("provider_order", [])),
            base_url=settings.get("base_url") or str(self.config.get("ollama_url", "")),
            options=dict(route_options or {}),
            timeout=float(settings.get("generation_timeout") or 300.0),
            system_prompt=system_prompt,
            max_tokens=int((route_options or {}).get("num_predict", 512)),
        )

    def _make_classifier(self, settings: dict[str, Any], router_config: RouterConfig):
        if not router_config.use_llm_classifier:
            return None
        if not settings.get("provider_ready") and not settings.get("provider_order"):
            return None

        def classify(prompt: str) -> str:
            result = self.provider_router.generate(
                ProviderRequest(
                    prompt=prompt,
                    model=router_config.default_model or settings.get("selected_model") or "",
                    provider_order=list(settings.get("provider_order") or []),
                    base_url=settings.get("base_url") or "",
                    options={"temperature": 0.1, "num_predict": 120},
                    timeout=min(float(settings.get("generation_timeout", 300.0)), 120.0),
                )
            )
            return result.text

        return classify

    def build_chat_prompt(
        self,
        user_message: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
        route_decision,
    ) -> tuple[str, Any]:
        """Build the final provider prompt through the central context manager."""

        profile = settings.get("chat_profile")
        base_prompt = build_locked_system_prompt(profile)
        routed_system = build_routed_prompt(
            user_message=user_message,
            base_system_prompt=base_prompt,
            history_prompt="",
            route=route_decision,
            chat_profile=profile,
            config=settings["router_config"],
        )
        memory_context = str(settings.get("_memory_context_override") or "")
        if not memory_context:
            memory_context, _ = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        retrieved_context = self._retrieved_context(
            user_message,
            bool(settings.get("use_knowledge_for_chat", True)),
            top_k=int(settings.get("knowledge_top_k", 3)),
        )
        context = build_context_bundle(
            user_message=user_message,
            messages=messages,
            system_prompt=routed_system,
            route_label=CATEGORY_LABELS.get(route_decision.category, route_decision.category),
            route_reason=route_decision.reason,
            memory_context=memory_context,
            retrieved_context=retrieved_context,
            user_facts=load_user_facts(),
            max_context_chars=int(settings.get("max_context_chars") or self.config.get("max_context_chars", 12000)),
            recent_message_limit=int(settings.get("recent_message_limit") or self.config.get("recent_message_limit", 8)),
        )
        return context.prompt, context

    def build_planned_chat_prompt(self, prompt: str, plan: ResponsePlan) -> str:
        """Append response-planning instructions without exposing hidden reasoning."""

        return f"{prompt}\n\n{plan.instructions}"

    def stream_chat_response(
        self,
        user_message: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Route a chat turn, stream provider output, and log verification metadata."""

        started = time.perf_counter()
        profile = settings.get("chat_profile")
        if self._capability_question(user_message):
            text = build_capability_greeting(profile)
            self.last_provider_result = {"provider": "local_capability", "elapsed": time.perf_counter() - started}
            yield text
            return

        memory_context, memory_command = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        if memory_command:
            self.last_provider_result = {"provider": "adaptive_memory", "elapsed": time.perf_counter() - started}
            yield memory_command
            return

        router_config: RouterConfig = settings["router_config"]
        classifier = self._make_classifier(settings, router_config)
        route_decision = route_message(user_message, router_config, classifier=classifier)
        bloodhound_query = detect_bloodhound_query(user_message)
        plan = plan_response(
            user_message=user_message,
            messages=messages,
            route_category="web_research" if bloodhound_query else route_decision.category,
            route_reason="bloodhound_search_detected" if bloodhound_query else route_decision.reason,
            settings=settings,
        )
        self.last_response_plan = plan.to_dict()
        logger.info(
            "Response plan intent=%s mode=%s max_tokens=%s provider_order=%s",
            plan.intent,
            plan.mode,
            plan.max_tokens,
            settings.get("provider_order"),
        )
        self.last_route_decision = {
            "category": route_decision.category,
            "label": CATEGORY_LABELS.get(route_decision.category, route_decision.category),
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "model": route_decision.model,
            "requires_web_search": route_decision.requires_web_search,
            "search_query": route_decision.search_query,
            "safety_mode": route_decision.safety_mode,
            "tags": route_decision.tags,
            "response_mode": plan.mode,
            "response_intent": plan.intent,
            "bloodhound_query": bloodhound_query,
        }

        if settings.get("enable_bloodhound_search", True) and bloodhound_query:
            if plan.acknowledge:
                yield plan.acknowledgement
            yield f'Bloodhound Search Mode engaged for "{bloodhound_query}".\n\n'
            yield "Expanding query...\n\nSearching sources...\n\nFetching pages...\n\nRanking results...\n\n"
            result = self.run_bloodhound_search(bloodhound_query, settings)
            yield "Summarizing findings...\n\n"
            answer = format_bloodhound_markdown(result)
            verification = verify_response(
                answer,
                source_count=len(result.get("ranked_results", [])),
                web_used=True,
                tool_confirmed=True,
            )
            completion = validate_response_against_plan(answer, plan)
            self.last_verification = verification.to_dict()
            log_verification(verification, "bloodhound_search")
            self.last_provider_result = {
                "provider": "bloodhound_search",
                "elapsed": time.perf_counter() - started,
                "response_completion": completion,
                "coverage": result.get("coverage", {}),
                "errors": result.get("errors", []),
            }
            yield answer
            return

        if settings.get("use_web_for_chat") and route_decision.requires_web_search:
            if plan.acknowledge:
                yield plan.acknowledgement
            query = route_decision.search_query or user_message
            result = self.run_web_research(query, settings, max_results=5, save_locally=True)
            answer = result.get("summary") or "No summary was generated."
            if settings.get("show_sources") and result.get("results"):
                sources = "\n".join(
                    f"- [{item.get('title') or item.get('url')}]({item.get('url')}) ({item.get('source')})"
                    for item in result["results"]
                    if item.get("url")
                )
                answer = f"{answer}\n\nSources:\n{sources}" if sources else answer
            verification = verify_response(answer, source_count=len(result.get("results", [])), web_used=True)
            completion = validate_response_against_plan(answer, plan)
            self.last_verification = verification.to_dict()
            log_verification(verification, "chat_web")
            self.last_provider_result = {
                "provider": "web_research",
                "elapsed": time.perf_counter() - started,
                "response_completion": completion,
            }
            yield answer
            return

        prompt_settings = dict(settings)
        prompt_settings["_memory_context_override"] = memory_context
        prompt, context = self.build_chat_prompt(user_message, messages, prompt_settings, route_decision)
        prompt = self.build_planned_chat_prompt(prompt, plan)
        options = dict(route_decision.generation_options or {})
        options["num_predict"] = int(plan.max_tokens)
        options["num_ctx"] = int(plan.num_ctx)
        if plan.mode == "short":
            options["temperature"] = min(float(options.get("temperature", 0.7)), 0.7)
        elif plan.mode in {"deep", "research"}:
            options["temperature"] = max(float(options.get("temperature", 0.75)), 0.8)
        request = self._provider_request(
            prompt,
            settings,
            options,
            model=route_decision.model or settings.get("selected_model") or "",
            system_prompt=build_locked_system_prompt(profile),
        )
        chunks: list[str] = []
        if plan.acknowledge:
            chunks.append(plan.acknowledgement)
            yield plan.acknowledgement
        for chunk in self.provider_router.stream(request):
            chunks.append(chunk)
            yield chunk

        answer = "".join(chunks).strip()
        provider_result = ProviderResult(
            text=answer,
            provider=";".join(request.provider_order or []),
            model=request.model,
            elapsed=time.perf_counter() - started,
            success=bool(answer),
        )
        verification = verify_response(answer, tool_confirmed=False, web_used=False)
        completion = validate_response_against_plan(answer, plan)
        self.last_provider_result = provider_result.to_dict() | {
            "context_tokens_estimate": context.estimated_tokens,
            "context_trimmed": context.trimmed,
            "response_completion": completion,
            "planned_tokens": plan.max_tokens,
        }
        self.last_verification = verification.to_dict()
        log_verification(verification, "chat")

    def generate_chat_response(
        self,
        user_message: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> str:
        """Non-streaming chat helper for tests and fallback UI paths."""

        return "".join(self.stream_chat_response(user_message, messages, settings)).strip()

    def run_web_research(
        self,
        query: str,
        settings: dict[str, Any],
        *,
        max_results: int = 5,
        scrape_pages: bool = True,
        summarize_with_ai: bool = True,
        save_locally: bool = True,
        save_to_memory: bool = True,
    ) -> dict[str, Any]:
        """Run web research through the central provider router for summaries."""

        ai_callback = None
        if summarize_with_ai:
            def ai_callback(prompt: str) -> str:
                result = self.provider_router.generate(
                    self._provider_request(
                        prompt,
                        settings,
                        {"temperature": 0.25, "num_predict": 480, "num_ctx": 4096},
                        model=settings.get("selected_model") or "",
                    )
                )
                return result.text

        return run_research_session(
            query,
            max_results=max_results,
            scrape_pages=scrape_pages,
            summarize_with_ai=summarize_with_ai,
            save_locally=save_locally,
            save_to_memory=save_to_memory,
            ai_callback=ai_callback,
        )

    def run_bloodhound_search(self, query: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Run Bloodhound Search Mode through the shared provider router."""

        config = default_bloodhound_config(
            {
                "enabled": bool(settings.get("enable_bloodhound_search", True)),
                "depth": str(settings.get("bloodhound_depth", "Standard")),
                "max_results": int(settings.get("bloodhound_max_results") or self.config.get("max_search_results", 50)),
                "timeout_seconds": int(settings.get("bloodhound_timeout_seconds") or self.config.get("search_timeout_seconds", 20)),
                "enable_cache": bool(settings.get("bloodhound_enable_cache", self.config.get("enable_search_cache", True))),
                "cache_ttl_hours": int(self.config.get("search_cache_ttl_hours", 24)),
                "follow_links": bool(settings.get("bloodhound_follow_links", self.config.get("enable_link_following", True))),
                "enable_onion": bool(settings.get("bloodhound_enable_onion", self.config.get("enable_onion_search", False))),
                "tor_socks_proxy": str(self.config.get("tor_socks_proxy", "127.0.0.1:9050")),
                "save_history": True,
            }
        )

        def ai_callback(prompt: str) -> str:
            result = self.provider_router.generate(
                self._provider_request(
                    prompt,
                    settings,
                    {"temperature": 0.2, "num_predict": 700, "num_ctx": 4096},
                    model=settings.get("selected_model") or "",
                )
            )
            return result.text

        return run_bloodhound_search(
            query,
            config=config,
            ai_callback=ai_callback if settings.get("provider_order") else None,
        )

    def answer_knowledge(
        self,
        query: str,
        settings: dict[str, Any],
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Query local knowledge and synthesize through provider router when available."""

        module = self.get_research_module()

        def ai_callback(prompt: str) -> str:
            return self.provider_router.generate(
                self._provider_request(
                    prompt,
                    settings,
                    {"temperature": 0.25, "num_predict": 420, "num_ctx": 4096},
                    model=settings.get("selected_model") or "",
                )
            ).text

        return query_knowledge(
            module,
            query,
            model=settings.get("selected_model"),
            base_url=settings.get("base_url", ""),
            provider_ready=True,
            top_k=top_k,
            ai_callback=ai_callback,
        )

    def generate_image(self, request: ImageGenerationRequest) -> dict[str, Any]:
        """Generate images through the existing image provider module."""

        return generate_images(request)

    def run_comfyui_workflow(
        self,
        *,
        workflow: dict[str, Any],
        prompt: str,
        negative_prompt: str = "",
        timeout: float = 240.0,
    ):
        """Run a ComfyUI workflow through the central client."""

        return self.comfyui.run_workflow(
            workflow=workflow,
            prompt=prompt,
            negative_prompt=negative_prompt,
            timeout=timeout,
        )
