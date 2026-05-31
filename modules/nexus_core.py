"""Central server-side backend for the Cognitive Nexus Streamlit UI."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Generator, Optional

from core.reasoning import analyze_epistemic_request
from core.reality_grounding import audit_answer
from modules.chat_profile import build_capability_greeting
from modules.comfyui_client import ComfyUIClient
from modules.context_manager import build_context_bundle, handle_local_memory_command, load_user_facts
from modules.image_gen import ImageGenerationRequest, generate_images
from modules.internal_prompts import build_locked_system_prompt
from modules.nexus_config import LOG_DIR, ensure_runtime_dirs, load_runtime_config
from modules.provider_router import ProviderRequest, ProviderResult, ProviderRouter
from modules.reality_research_agent import (
    ResearchReport,
    ResearchRequest,
    detect_reality_research_query,
    run_reality_research,
)
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
        self.last_reality_audit: dict[str, Any] = {}
        self.last_trust_audit: dict[str, Any] = {}
        self.last_epistemic_assessment: dict[str, Any] = {}
        self.last_reality_research_report: dict[str, Any] = {}
        self.last_retrieval: dict[str, Any] = {}
        self.last_memory: dict[str, Any] = {}

    def refresh_config(self) -> None:
        """Reload config and provider cache after settings change."""

        self.config = load_runtime_config()
        self.provider_router.config = self.config
        self.provider_router.invalidate_status_cache()
        self.comfyui = ComfyUIClient(str(self.config.get("comfyui_url", "http://127.0.0.1:8188")))

    def _direct_response_instruction(self, user_message: str) -> str | None:
        """Return deterministic text for exact-output prompts that do not need a model."""

        text = str(user_message or "").strip()
        if not text:
            return None
        patterns = (
            r'^\s*(?:reply|respond|say|output|print|return)\s+(?:with\s+)?exactly\s*:?\s*(?P<answer>.+?)\s*$',
            r'^\s*(?:reply|respond|say|output|print|return)\s+(?P<answer>["\'].+?["\'])\s*$',
            r'^\s*write\s+(?:with\s+)?exactly\s*:?\s*(?P<answer>.+?)\s*$',
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            answer = match.group("answer").strip()
            if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in {"'", '"'}:
                answer = answer[1:-1].strip()
            return answer or None
        return None

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
                    "enable_reality_grounding",
                    "enable_reality_first_reasoning",
                    "enable_reality_research_agent",
                    "epistemic_mode",
                    "show_grounding_notes",
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

    def _retrieve_context(self, user_message: str, enabled: bool, top_k: int = 3) -> tuple[str, dict[str, Any]]:
        metadata: dict[str, Any] = {
            "enabled": enabled,
            "query": user_message,
            "top_k": top_k,
            "result_count": 0,
            "used_count": 0,
            "sources": [],
            "error": "",
        }
        if not enabled:
            return "", metadata
        try:
            module = self.get_research_module()
            results = module.semantic_search(user_message, top_k=top_k)
            chunks: list[str] = []
            sources: list[dict[str, Any]] = []
            for index, item in enumerate(results, start=1):
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                title = str(item.get("title") or item.get("url") or f"Local source {index}")
                url = str(item.get("url") or "")
                excerpt = text[:900]
                chunks.append(f"Source {index}: {title}\n{excerpt}")
                sources.append(
                    {
                        "rank": index,
                        "title": title,
                        "url": url,
                        "score": item.get("score", item.get("similarity", item.get("distance", ""))),
                        "excerpt": excerpt[:500],
                    }
                )
            metadata["result_count"] = len(results)
            metadata["used_count"] = len(chunks)
            metadata["sources"] = sources
            return "\n\n".join(chunks), metadata
        except Exception as exc:
            logger.info("Knowledge retrieval unavailable: %s", exc)
            metadata["error"] = str(exc)
            return "", metadata

    def _retrieved_context(self, user_message: str, enabled: bool, top_k: int = 3) -> str:
        """Compatibility wrapper for older tests and callers."""

        context, metadata = self._retrieve_context(user_message, enabled, top_k=top_k)
        self.last_retrieval = metadata
        return context

    def _has_ready_model_provider(self, provider_order: list[str]) -> bool:
        for provider in provider_order:
            if provider == "fallback":
                continue
            try:
                if self.provider_router.detect_provider(provider).available:
                    return True
            except Exception:
                continue
        return False

    def _extractive_knowledge_answer(self, retrieval: dict[str, Any]) -> str:
        sources = retrieval.get("sources") or []
        if not sources:
            return "Fallback: I found no usable local knowledge chunks and no model provider is available."

        lines = [
            "I found relevant local knowledge. No model provider is available right now, so this is an extractive answer from saved material rather than a generated synthesis.",
            "",
            "Most relevant saved chunks:",
        ]
        for source in sources[:3]:
            title = str(source.get("title") or f"Local source {source.get('rank', '')}").strip()
            excerpt = " ".join(str(source.get("excerpt") or "").split())
            if len(excerpt) > 420:
                excerpt = excerpt[:417].rsplit(" ", 1)[0] + "..."
            lines.append(f"- {title}: {excerpt}")

        lines.extend(
            [
                "",
                "Start Ollama or another configured provider for a synthesized answer over these chunks.",
            ]
        )
        return "\n".join(lines)

    def _skip_retrieval_for_simple_chat(self, user_message: str, simple_mode: bool) -> bool:
        if not simple_mode:
            return False
        lowered = " ".join((user_message or "").lower().split())
        words = lowered.split()
        if len(words) > 4:
            return False
        casual_phrases = {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "good morning",
            "good afternoon",
            "good evening",
        }
        return lowered in casual_phrases

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
        simple_mode: bool = False,
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
        epistemic_instruction = str(settings.get("_epistemic_instruction") or "")
        if epistemic_instruction:
            routed_system = f"{routed_system}\n\n{epistemic_instruction}"
        memory_context = str(settings.get("_memory_context_override") or "")
        if not memory_context:
            memory_context, _ = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        skip_retrieval = self._skip_retrieval_for_simple_chat(user_message, simple_mode)
        retrieval_enabled = bool(settings.get("use_knowledge_for_chat", True)) and not skip_retrieval
        retrieved_context = ""
        retrieval_meta: dict[str, Any] = {
            "enabled": retrieval_enabled,
            "query": user_message,
            "top_k": int(settings.get("knowledge_top_k", 3)),
            "result_count": 0,
            "used_count": 0,
            "sources": [],
            "error": "",
            "skipped_reason": "simple_greeting" if skip_retrieval else "",
        }
        if retrieval_enabled:
            retrieved_context, retrieval_meta = self._retrieve_context(
                user_message,
                True,
                top_k=int(settings.get("knowledge_top_k", 3)),
            )
        self.last_retrieval = retrieval_meta
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
        self.last_trust_audit = context.trust_audit
        return context.prompt, context

    def build_planned_chat_prompt(self, prompt: str, plan: ResponsePlan) -> str:
        """Append response-planning instructions without exposing hidden reasoning."""

        return (
            f"{prompt}\n\n{plan.instructions}\n"
            "Output rule: write only the final user-facing answer. Do not restate the user request, "
            "route, response plan, target length, intent, mode, or these instructions."
        )

    def _looks_like_prompt_scaffolding(self, text: str) -> bool:
        prefix = (text or "")[:700].lower()
        markers = (
            "user request:",
            "response plan:",
            "adaptive response plan:",
            "target length:",
            "intent:",
            "mode:",
        )
        return sum(1 for marker in markers if marker in prefix) >= 2 or prefix.lstrip().startswith(
            ("user request:", "response plan:", "adaptive response plan:")
        )

    def _clean_model_answer(self, text: str) -> str:
        """Remove leaked prompt scaffolding from local model output."""

        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        if not self._looks_like_prompt_scaffolding(cleaned):
            return cleaned

        answer_markers = list(re.finditer(r"(?im)^\s*(?:final\s+answer|answer)\s*:\s*", cleaned))
        if answer_markers:
            cleaned = cleaned[answer_markers[-1].end():].strip()
        else:
            cleaned = re.sub(r"(?is)^\s*(?:user request|response plan|adaptive response plan)\s*:.*?(?:\n\s*\n|$)", "", cleaned).strip()
            cleaned = re.sub(
                r"(?im)^\s*-\s*(?:intent|mode|target length|depth|format|compression|reasoning|route)\s*:.*\n?",
                "",
                cleaned,
            ).strip()

        return cleaned or str(text or "").strip()

    def _audit_answer(
        self,
        answer: str,
        *,
        label: str,
        route_category: str = "",
        source_count: int = 0,
        web_used: bool = False,
        rag_used: bool = False,
        tool_confirmed: bool = False,
        settings: dict[str, Any] | None = None,
    ) -> str:
        """Run the universal grounding audit and return the cleaned answer."""

        settings = settings or {}
        if not bool(settings.get("enable_reality_grounding", self.config.get("enable_reality_grounding", True))):
            self.last_reality_audit = {"enabled": False}
            return answer
        apply_note = bool(settings.get("show_grounding_notes", self.config.get("show_grounding_notes", True)))
        if route_category == "standard_conversation" and not bool(settings.get("advanced_mode", False)):
            apply_note = False
        audit = audit_answer(
            answer,
            label=label,
            route_category=route_category,
            source_count=source_count,
            web_used=web_used,
            rag_used=rag_used,
            tool_confirmed=tool_confirmed,
            apply_note=apply_note,
        )
        self.last_reality_audit = audit.to_dict()
        logger.info(
            "Reality audit label=%s confidence=%s hallucination=%s speculation=%s claims=%s",
            label,
            audit.confidence.level,
            audit.hallucination.probability,
            audit.speculation.category,
            len(audit.claims),
        )
        cleaned_answer = audit.cleaned_answer
        
        # Apply response compression for research simulation
        if route_category == "research_simulation" and settings:
            profile = settings.get("chat_profile")
            if profile:
                synthesis_confidence = getattr(profile, 'synthesis_confidence', 0.7)
                corporate_penalty = getattr(profile, 'corporate_hedging_penalty', -0.5)
                
                # Compress based on personality - higher synthesis confidence = cleaner output
                if synthesis_confidence > 0.8:
                    cleaned_answer = self._compress_response(cleaned_answer, intensity="high")
                elif synthesis_confidence > 0.6:
                    cleaned_answer = self._compress_response(cleaned_answer, intensity="medium")
                
                # Reduce corporate hedging based on penalty
                if corporate_penalty < -0.3:
                    cleaned_answer = self._reduce_hedging(cleaned_answer)
        
        return cleaned_answer

    def _compress_response(self, text: str, intensity: str = "medium") -> str:
        """Compress response to prioritize synthesis over padding."""
        if intensity == "high":
            # Remove filler phrases and compress to core insights
            fillers = [
                r"\bI think\b", r"\bIn my opinion\b", r"\bIt seems\b", r"\bPerhaps\b",
                r"\bMaybe\b", r"\bCould be\b", r"\bI'm not sure but\b", r"\bLet me clarify\b"
            ]
            for filler in fillers:
                text = re.sub(filler, "", text, flags=re.I)
            
            # Compress multiple sentences into tighter chains
            text = re.sub(r'(\w+)\.\s+(\w+)', r'\1. \2', text)  # Remove extra spaces
            text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
            
        elif intensity == "medium":
            # Moderate compression - remove obvious padding
            text = re.sub(r'\bI need to clarify\b.*?\.', '.', text, flags=re.I)
            text = re.sub(r'\bBefore proceeding\b.*?\.', '.', text, flags=re.I)
        
        return text.strip()

    def _reduce_hedging(self, text: str) -> str:
        """Reduce corporate-style hedging language."""
        hedging_phrases = [
            r"\bI should note that\b",
            r"\bIt's important to mention\b", 
            r"\bPlease be aware that\b",
            r"\bKeep in mind that\b",
            r"\bNote that\b",
            r"\bHowever,\b",
            r"\bThat said,\b"
        ]
        
        for phrase in hedging_phrases:
            text = re.sub(phrase, "", text, flags=re.I)
        
        return text.strip()

    def stream_chat_response(
        self,
        user_message: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Route a chat turn, stream provider output, and log verification metadata."""

        started = time.perf_counter()
        timings = {}
        profile = settings.get("chat_profile")
        self.last_memory = {}
        direct_response = self._direct_response_instruction(user_message)
        if direct_response is not None:
            verification = verify_response(direct_response, tool_confirmed=True)
            self.last_verification = verification.to_dict()
            log_verification(verification, "direct_response")
            self.last_reality_audit = {"enabled": False, "reason": "direct_response_instruction"}
            self.last_provider_result = {
                "provider": "direct_response",
                "model": "",
                "elapsed": time.perf_counter() - started,
                "success": True,
                "attempts": [{"provider": "direct_response", "success": True}],
            }
            yield direct_response
            return
        if self._capability_question(user_message):
            text = build_capability_greeting(profile)
            text = self._audit_answer(text, label="capability", route_category="standard_conversation", settings=settings)
            self.last_provider_result = {"provider": "local_capability", "elapsed": time.perf_counter() - started}
            yield text
            return

        local_memory_command = handle_local_memory_command(user_message)
        if local_memory_command:
            self.last_memory = local_memory_command
            answer = self._audit_answer(
                str(local_memory_command.get("message") or ""),
                label="local_memory",
                route_category="standard_conversation",
                tool_confirmed=True,
                settings=settings,
            )
            verification = verify_response(answer, tool_confirmed=True)
            self.last_verification = verification.to_dict()
            log_verification(verification, "local_memory")
            self.last_provider_result = {
                "provider": "local_memory",
                "elapsed": time.perf_counter() - started,
                "success": bool(local_memory_command.get("success", True)),
                "memory": local_memory_command,
            }
            yield answer
            return

        memory_start = time.perf_counter()
        memory_context, memory_command = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        timings["memory_context"] = time.perf_counter() - memory_start
        if memory_command:
            memory_command = self._audit_answer(memory_command, label="adaptive_memory", tool_confirmed=True, settings=settings)
            self.last_provider_result = {"provider": "adaptive_memory", "elapsed": time.perf_counter() - started}
            yield memory_command
            return

        route_start = time.perf_counter()
        router_config: RouterConfig = settings["router_config"]
        classifier = self._make_classifier(settings, router_config)
        route_decision = route_message(user_message, router_config, classifier=classifier)
        bloodhound_query = detect_bloodhound_query(user_message)
        reality_research_query = detect_reality_research_query(user_message)
        timings["routing"] = time.perf_counter() - route_start

        epistemic_start = time.perf_counter()
        if bool(settings.get("enable_reality_first_reasoning", self.config.get("enable_reality_first_reasoning", True))):
            epistemic = analyze_epistemic_request(
                user_message,
                route_category="web_research" if bloodhound_query else route_decision.category,
                rag_used=bool(settings.get("use_knowledge_for_chat", True)),
                manual_mode=str(settings.get("epistemic_mode") or self.config.get("epistemic_mode", "auto")),
            )
            self.last_epistemic_assessment = epistemic.to_dict()
        else:
            epistemic = None
            self.last_epistemic_assessment = {"enabled": False}
        timings["epistemic_analysis"] = time.perf_counter() - epistemic_start

        plan_start = time.perf_counter()
        plan = plan_response(
            user_message=user_message,
            messages=messages,
            route_category="web_research" if bloodhound_query else route_decision.category,
            route_reason="bloodhound_search_detected" if bloodhound_query else route_decision.reason,
            settings=settings,
        )
        timings["response_planning"] = time.perf_counter() - plan_start
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
            "reality_research_query": reality_research_query,
        }

        if settings.get("enable_reality_research_agent", True) and reality_research_query:
            if plan.acknowledge:
                yield plan.acknowledgement
            yield f'Reality-First Research Agent engaged for "{reality_research_query}".\n\n'
            yield "Planning research...\n\nSearching sources...\n\nExtracting claims...\n\nChecking contradictions...\n\n"
            request = ResearchRequest(
                query=reality_research_query,
                depth=str(settings.get("reality_research_depth") or settings.get("bloodhound_depth") or "Standard"),
                max_sources=int(settings.get("reality_research_max_sources") or settings.get("bloodhound_max_results") or 25),
                follow_links=bool(settings.get("reality_research_follow_links", settings.get("bloodhound_follow_links", True))),
                save_to_memory=bool(settings.get("reality_research_save_memory", True)),
                show_weak_matches=bool(settings.get("reality_research_show_weak", True)),
                use_ai_summary=bool(settings.get("reality_research_use_ai", True)),
                save_report=True,
            )
            report = self.run_reality_research(request, settings)
            self.last_reality_research_report = report.to_dict()
            yield "Composing grounded report...\n\n"
            answer = report.to_markdown()
            answer = self._audit_answer(
                answer,
                label="reality_research",
                route_category="web_research",
                source_count=len(report.sources),
                web_used=True,
                rag_used=bool(report.memory_saved),
                tool_confirmed=True,
                settings=settings,
            )
            verification = verify_response(
                answer,
                source_count=len(report.sources),
                web_used=True,
                tool_confirmed=True,
            )
            completion = validate_response_against_plan(answer, plan)
            self.last_verification = verification.to_dict()
            log_verification(verification, "reality_research")
            self.last_provider_result = {
                "provider": "reality_research_agent",
                "elapsed": time.perf_counter() - started,
                "response_completion": completion,
                "sources": len(report.sources),
                "claims": len(report.claims),
                "contradictions": len(report.contradictions),
                "saved_paths": report.saved_paths,
                "memory_saved": report.memory_saved,
                "errors": report.errors,
            }
            yield answer
            return

        if settings.get("enable_bloodhound_search", True) and bloodhound_query:
            if plan.acknowledge:
                yield plan.acknowledgement
            yield f'Bloodhound Search Mode engaged for "{bloodhound_query}".\n\n'
            yield "Expanding query...\n\nSearching sources...\n\nFetching pages...\n\nRanking results...\n\n"
            result = self.run_bloodhound_search(bloodhound_query, settings)
            yield "Summarizing findings...\n\n"
            answer = format_bloodhound_markdown(result)
            answer = self._audit_answer(
                answer,
                label="bloodhound_search",
                route_category="web_research",
                source_count=len(result.get("ranked_results", [])),
                web_used=True,
                tool_confirmed=True,
                settings=settings,
            )
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
            answer = self._audit_answer(
                answer,
                label="chat_web",
                route_category="web_research",
                source_count=len(result.get("results", [])),
                web_used=True,
                tool_confirmed=True,
                settings=settings,
            )
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
        if epistemic is not None:
            prompt_settings["_epistemic_instruction"] = epistemic.constraints.instruction
        prompt_start = time.perf_counter()
        prompt, context = self.build_chat_prompt(user_message, messages, prompt_settings, route_decision, simple_mode=plan.intent == "casual_chat")
        prompt = self.build_planned_chat_prompt(prompt, plan)
        timings["prompt_build"] = time.perf_counter() - prompt_start
        retrieval_meta = dict(self.last_retrieval or {})
        source_count = int(retrieval_meta.get("used_count", 0) or 0)
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
        if context.retrieved_context and not self._has_ready_model_provider(request.provider_order):
            if plan.acknowledge:
                yield plan.acknowledgement
            answer = self._extractive_knowledge_answer(retrieval_meta)
            answer = self._audit_answer(
                answer,
                label="local_knowledge_fallback",
                route_category=route_decision.category,
                source_count=source_count,
                rag_used=True,
                tool_confirmed=True,
                settings=settings,
            )
            verification = verify_response(answer, source_count=source_count, tool_confirmed=True)
            completion = validate_response_against_plan(answer, plan)
            self.last_provider_result = {
                "provider": "local_knowledge_fallback",
                "model": "",
                "elapsed": time.perf_counter() - started,
                "success": True,
                "context_tokens_estimate": context.estimated_tokens,
                "context_trimmed": context.trimmed,
                "response_completion": completion,
                "planned_tokens": plan.max_tokens,
                "timings": timings,
                "provider_order": request.provider_order,
                "attempts": [{"provider": "local_knowledge_fallback", "success": True}],
                "fallback_reason": "No configured model provider was available; answered from retrieved local knowledge.",
                "retrieval": retrieval_meta,
                "sources": source_count,
            }
            self.last_verification = verification.to_dict()
            log_verification(verification, "local_knowledge_fallback")
            yield answer
            return
        # For simple chat, use shorter timeout
        if plan.intent == "casual_chat":
            request.timeout = min(request.timeout, 60.0)
        chunks: list[str] = []
        if plan.acknowledge:
            chunks.append(plan.acknowledgement)
            yield plan.acknowledgement
        provider_start = time.perf_counter()
        provider_raw_chunks: list[str] = []
        provider_visible_chunks: list[str] = []
        guard_buffer = ""
        visible_stream_started = False
        suppress_provider_stream = False
        for chunk in self.provider_router.stream(request):
            provider_raw_chunks.append(chunk)
            if suppress_provider_stream:
                continue
            if not visible_stream_started:
                guard_buffer += chunk
                if self._looks_like_prompt_scaffolding(guard_buffer):
                    suppress_provider_stream = True
                    guard_buffer = ""
                    continue
                if len(guard_buffer) >= 160 or "\n" in guard_buffer:
                    visible_stream_started = True
                    provider_visible_chunks.append(guard_buffer)
                    chunks.append(guard_buffer)
                    yield guard_buffer
                    guard_buffer = ""
                continue
            provider_visible_chunks.append(chunk)
            chunks.append(chunk)
            yield chunk
        timings["provider_call"] = time.perf_counter() - provider_start
        provider_meta = dict(getattr(self.provider_router, "last_stream_metadata", {}) or {})
        provider_raw_answer = "".join(provider_raw_chunks).strip()
        if suppress_provider_stream or not provider_visible_chunks:
            provider_answer = self._clean_model_answer(provider_raw_answer)
            if provider_answer:
                chunks.append(provider_answer)
                yield provider_answer
        elif guard_buffer:
            provider_visible_chunks.append(guard_buffer)
            chunks.append(guard_buffer)
            yield guard_buffer

        answer = "".join(chunks).strip()
        answer = self._clean_model_answer(answer)
        audited_answer = self._audit_answer(
            answer,
            label="chat",
            route_category=route_decision.category,
            source_count=source_count,
            web_used=False,
            rag_used=bool(context.retrieved_context),
            tool_confirmed=False,
            settings=settings,
        )
        if audited_answer != answer:
            note = audited_answer[len(answer):]
            if note:
                yield note
            answer = audited_answer
        provider_result = ProviderResult(
            text=answer,
            provider=str(provider_meta.get("provider") or ";".join(request.provider_order or [])),
            model=str(provider_meta.get("model") or request.model),
            elapsed=time.perf_counter() - started,
            success=bool(answer),
        )
        verification = verify_response(answer, source_count=source_count, tool_confirmed=False, web_used=False)
        completion = validate_response_against_plan(answer, plan)
        self.last_provider_result = provider_result.to_dict() | {
            "context_tokens_estimate": context.estimated_tokens,
            "context_trimmed": context.trimmed,
            "response_completion": completion,
            "planned_tokens": plan.max_tokens,
            "timings": timings,
            "provider_order": request.provider_order,
            "attempts": provider_meta.get("attempts", []),
            "fallback_reason": provider_meta.get("fallback_reason", ""),
            "retrieval": retrieval_meta,
            "sources": source_count,
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

    def run_reality_research(
        self,
        request: ResearchRequest,
        settings: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> ResearchReport:
        """Run the signature source-grounded research workflow."""

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

        return run_reality_research(
            request,
            settings=settings | {
                "enable_onion_search": self.config.get("enable_onion_search", False),
                "tor_socks_proxy": self.config.get("tor_socks_proxy", "127.0.0.1:9050"),
                "search_cache_ttl_hours": self.config.get("search_cache_ttl_hours", 24),
                "search_timeout_seconds": self.config.get("search_timeout_seconds", 20),
            },
            progress_callback=progress_callback,
            ai_callback=ai_callback if settings.get("provider_order") else None,
            research_module=self.get_research_module() if request.save_to_memory else None,
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
        use_ai_synthesis = bool(settings.get("knowledge_use_ai", False))

        def ai_callback(prompt: str) -> str:
            return self.provider_router.generate(
                self._provider_request(
                    prompt,
                    settings,
                    {"temperature": 0.25, "num_predict": 420, "num_ctx": 4096},
                    model=settings.get("selected_model") or "",
                )
            ).text

        result = query_knowledge(
            module,
            query,
            model=settings.get("selected_model"),
            base_url=settings.get("base_url", ""),
            provider_ready=use_ai_synthesis,
            top_k=top_k,
            ai_callback=ai_callback if use_ai_synthesis else None,
        )
        result["answer"] = self._audit_answer(
            str(result.get("answer", "")),
            label="knowledge_query",
            route_category="web_research",
            source_count=len(result.get("results", [])),
            rag_used=True,
            tool_confirmed=True,
            settings=settings,
        )
        return result

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
