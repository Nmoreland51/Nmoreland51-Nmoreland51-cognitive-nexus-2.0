"""Central server-side backend for the Cognitive Nexus Streamlit UI."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Generator, Optional

from core.reasoning import analyze_epistemic_request
from core.reality_grounding.prompt_firewall import set_untrusted_mode
from modules.chat_profile import build_capability_greeting
from modules.comfyui_client import ComfyUIClient
from modules.context_manager import (
    estimate_tokens as estimate_context_tokens,
    handle_local_memory_command,
)
from modules import redaction
from modules.behavior_policy import (
    JUDGE_OPTIONS,
    ContentRuleBlocked,
    RuleDecision,
    check_content_rule,
    effective_policy,
    looks_like_model_refusal,
    policy_from,
)
from modules.event_log import record_event
from modules.internal_prompts import chat_system_prompt
from modules.nexus_config import LOG_DIR, ensure_runtime_dirs, load_runtime_config
from modules.provider_router import SLOW_STARTUP_OLLAMA_READ_TIMEOUT, ProviderResult, ProviderRouter
from modules.reality_research_agent import (
    ResearchRequest,
    detect_reality_research_query,
    is_verification_request,
)
from modules.data_stores import DATA_ROOT, SEED_KNOWLEDGE_DIR
from modules.research import get_research_module
from modules.response_planner import (
    analyze_intent_cached,
    apply_auto_precision_settings,
    plan_response,
    validate_response_against_plan,
)
from modules.response_self_critic import (
    PREFERENCES_FILE as RESPONSE_PREFERENCES_FILE,
)
from modules.response_verifier import log_verification, verify_response
from modules.calculator import EXPRESSION_OPTIONS, calculate, looks_like_word_problem, solve_word_problem
from modules.claim_map import map_sentences, sources_from as claim_sources_from
from modules.research_plan import unsourced_names_note
from modules.web_research import (
    NO_RESULTS_SUMMARY,
    build_summary_prompt,
    finish_research_session,
    gather_research,
    unsourced_numbers_note,
)
from search.bloodhound_search import (
    detect_bloodhound_query,
    format_bloodhound_markdown,
)
from nexus_router import CATEGORY_LABELS, RouteDecision, RouterConfig, route_message
from modules.core_models import ModelCalls
from modules.core_prompts import PromptBuilding
from modules.core_answers import AnswerFinishing
from modules.core_research import ResearchServices
from modules.core_pictures import PictureServices
from modules.core_shared import BRIEF_WEB_SUMMARY_OPTIONS, FULL_WEB_SUMMARY_OPTIONS, _elapsed_ms  # noqa: F401  kept here


logger = logging.getLogger(__name__)


_ANSWER_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def length_note(answer: str, requested: Any) -> str:
    """A note for an answer that the model ended outside the length asked for, or "" when it kept to it."""

    if not requested:
        return ""
    low, high = int(requested[0]), int(requested[1])
    written = len(_ANSWER_WORD.findall(answer or ""))
    if low <= written <= high:
        return ""
    if written < low:
        return f"\n\n[About {written} words, fewer than the {low} to {high} you asked for. The model ended here by itself; nothing in the app shortened it. Ask for more if you want it longer.]"
    return f"\n\n[About {written} words, more than the {low} to {high} you asked for. The model wrote this much by itself; the app does not cut answers.]"


def _estimate_output_tokens(text: str) -> int:
    """Cheap output token estimate for providers that do not report token counts."""

    return max(1, len(text or "") // 4)


class NexusCore(ModelCalls, PromptBuilding, AnswerFinishing, ResearchServices, PictureServices):
    """One shared backend used by every Streamlit tab."""

    def __init__(self, project_root: Path | None = None) -> None:
        ensure_runtime_dirs()
        logging.basicConfig(
            filename=str(LOG_DIR / "cognitive_nexus.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        redaction.install_log_redaction()  # keys and tokens never reach the log file (item 110)
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.config = load_runtime_config()
        self.response_preferences_path = self._configured_response_preferences_path()
        self.provider_router = ProviderRouter(self.config)
        self.comfyui = ComfyUIClient(str(self.config.get("comfyui_url", "http://127.0.0.1:8188")))
        set_untrusted_mode(policy_from(self.config).untrusted_content)
        self._research_module = None
        self._adaptive_memory = None
        self.last_route_decision: dict[str, Any] = {}
        self.last_provider_result: dict[str, Any] = {}
        # How the last chat prompt was fitted to the model's window (for Diagnostics).
        self.last_context: dict[str, Any] = {}
        self.last_verification: dict[str, Any] = {}
        self.last_response_plan: dict[str, Any] = {}
        self.last_reality_audit: dict[str, Any] = {}
        self.last_trust_audit: dict[str, Any] = {}
        # What the app's one content rule made of the last request (for Diagnostics).
        self.last_content_rule: dict[str, Any] = {}
        # The last chat prompt exactly as it was sent, so the owner can read all of it.
        self.last_prompt: dict[str, str] = {}
        self.last_epistemic_assessment: dict[str, Any] = {}
        self.last_reality_research_report: dict[str, Any] = {}
        self.last_retrieval: dict[str, Any] = {}
        self.last_memory: dict[str, Any] = {}
        self.last_response_critic: dict[str, Any] = {}

    def refresh_config(self) -> None:
        """Reload config and provider cache after settings change."""

        self.config = load_runtime_config()
        self.response_preferences_path = self._configured_response_preferences_path()
        self.provider_router.config = self.config
        self.provider_router.invalidate_status_cache()
        set_untrusted_mode(policy_from(self.config).untrusted_content)
        self.comfyui = ComfyUIClient(str(self.config.get("comfyui_url", "http://127.0.0.1:8188")))

    def _configured_response_preferences_path(self) -> Path:
        raw_path = Path(str(self.config.get("response_preferences_path") or RESPONSE_PREFERENCES_FILE))
        return raw_path if raw_path.is_absolute() else self.project_root / raw_path

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
                    "allow_cloud_fallback",
                    "anthropic_effort",
                    "model_id_notes",
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

            self._adaptive_memory = AdaptiveMemoryManager(DATA_ROOT, seed_knowledge_dir=SEED_KNOWLEDGE_DIR)
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

    def _immediate_previous_assistant(self, messages: list[dict[str, str]]) -> str:
        for item in reversed(messages or []):
            if str(item.get("role", "")).lower() == "assistant":
                return str(item.get("content", "") or "").strip()
        return ""

    def _immediate_previous_user(self, messages: list[dict[str, str]]) -> str:
        for item in reversed(messages or []):
            if str(item.get("role", "")).lower() == "user":
                return str(item.get("content", "") or "").strip()
        return ""

    def _conversation_followup_reply(self, message: str, messages: list[dict[str, str]]) -> str:
        normalized = re.sub(r"[^\w\s']", " ", " ".join((message or "").lower().replace("’", "'").split()))
        normalized = re.sub(r"\s+", " ", normalized).strip()
        previous = self._immediate_previous_assistant(messages)
        previous_lower = previous.lower()
        history_tail = previous[-240:] if previous else ""
        pragmatics = analyze_intent_cached(message, history_tail).get("pragmatics", {})
        function = str(pragmatics.get("function") or "")
        if not previous:
            if function == "rejection":
                return "Got it. What should I change?"
            return "I can do that, but what should I continue?"
        if function == "choose_all":
            return "Got it. I'll include all of the options from the last thing I offered."
        if function == "choose_option":
            if normalized.startswith("first"):
                return "First option it is. I'll follow that direction from the last choice."
            if normalized.startswith("second"):
                return "Second option it is. I'll follow that direction from the last choice."
            return "Got it, that option. I'll stick to what you just pointed at."
        if function == "agreement":
            if "fix" in previous_lower:
                return "Yes, I'll fix it. Send the error or file and I'll keep it tight."
            return "Got it. I'll continue from the last thing I offered."
        if function in {"proceed", "continue_previous"}:
            return "On it. I'll continue from the last thing we were doing."
        if function == "rejection":
            return "Got it, no on that. What should I change or skip?"
        return "Got it. I'll continue from the immediate previous point."

    def content_rule(self, text: str, settings: dict[str, Any] | None = None, recent: str = "", kind: str = "text") -> RuleDecision:
        """Apply the app's one content rule (no sexual content involving minors) to a request.

        See modules/behavior_policy.check_content_rule. A model is asked only when a first, cheap
        look finds both a sexual term and a term for a minor; for every other request this is a
        pattern match and nothing more.
        """

        settings = settings or {}
        # Every request passes through here first, so this is also where the owner's setting for
        # outside text takes effect for the request.
        set_untrusted_mode(policy_from({**self.config, **settings}).untrusted_content)

        def judge(prompt: str) -> str:
            return self._model_text(prompt, settings, dict(JUDGE_OPTIONS))

        decision = check_content_rule(text, recent, judge, kind)
        self.last_content_rule = decision.to_dict()
        if decision.blocked:
            # The event records that it happened and at which stage, never the message.
            record_event("content_rule", "A request was not answered under the app's one content rule", stage=decision.stage)
        return decision

    def _require_content_rule(self, text: str, settings: dict[str, Any] | None = None, kind: str = "text") -> None:
        """For entry points other than chat: stop with ContentRuleBlocked when the rule applies."""

        decision = self.content_rule(text, settings, kind=kind)
        if decision.blocked:
            raise ContentRuleBlocked(decision)

    def behavior(self, settings: dict[str, Any] | None = None, profile: Any | None = None) -> dict[str, Any]:
        """What shapes an answer right now, in three parts: configured, application, provider."""

        merged = {**self.config, **(settings or {})}
        order = [str(name) for name in (merged.get("provider_order") or [])]
        primary = next((name for name in order if name != "fallback"), "")
        model = str(merged.get("selected_model") or merged.get(f"{primary}_model") or "")
        return effective_policy(
            merged,
            profile,
            provider=primary,
            model=model,
            cloud_fallback_allowed=bool(merged.get("allow_cloud_fallback")),
        )


    def stream_chat_response(
        self,
        user_message: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Route a chat turn, stream provider output, and log verification metadata."""

        started = time.perf_counter()
        timings: dict[str, Any] = {
            "planner_ms": 0.0,
            "context_ms": 0.0,
            "retrieval_ms": 0.0,
            "provider_first_token_ms": None,
            "provider_total_ms": 0.0,
            "render_ms": 0.0,
            "total_ms": 0.0,
        }
        profile = settings.get("chat_profile")
        self.last_memory = {}
        self.last_provider_result = {}
        recent_turns = "\n".join(
            f"{str(item.get('role', 'user')).title()}: {str(item.get('content', ''))[-400:]}"
            for item in (messages or [])[-4:]
            if str(item.get("content", "")).strip() and str(item.get("content", "")).strip() != str(user_message or "").strip()
        )
        rule = self.content_rule(user_message, settings, recent_turns)
        if rule.blocked:
            self.last_verification = {}
            self.last_reality_audit = {"enabled": False, "reason": "content_rule"}
            self.last_trust_audit = {}
            self.last_provider_result = {
                "text": rule.reply,
                "provider": "content_rule",
                "model": "",
                "elapsed": time.perf_counter() - started,
                "success": True,
                "attempts": [{"provider": "content_rule", "success": True}],
                "content_rule": rule.to_dict(),
                "sources": 0,
            }
            yield rule.reply
            return
        calculated = calculate(user_message)
        set_up_by_model = False
        if calculated is None and looks_like_word_problem(user_message) and settings.get("solve_word_problems", self.config.get("solve_word_problems", True)):
            # A word problem: the model writes the expression from the question's own numbers, the app works it out.
            calculated = solve_word_problem(user_message, self._json_asker(settings, EXPRESSION_OPTIONS))
            set_up_by_model = calculated is not None
        if calculated is not None:
            # Plain arithmetic is worked out exactly instead of sampled from the model (modules/calculator.py).
            self.last_verification = {}
            self.last_reality_audit = {"enabled": False, "reason": "calculator"}
            self.last_trust_audit = {}
            self.last_provider_result = {
                "text": calculated.answer,
                "provider": "model_and_calculator" if set_up_by_model else "calculator",
                "model": str(settings.get("selected_model") or "") if set_up_by_model else "",
                "elapsed": time.perf_counter() - started,
                "success": True,
                "attempts": [{"provider": "calculator", "success": True}],
                "calculation": calculated.to_dict(),
                "sources": 0,
            }
            yield calculated.answer
            return
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

        route_start = time.perf_counter()
        router_config: RouterConfig = settings["router_config"]
        pre_route_history_tail = "\n".join(str(item.get("content", ""))[-240:] for item in messages[-4:])
        pre_route_analysis = analyze_intent_cached(user_message, pre_route_history_tail)
        pre_route_intent = str(pre_route_analysis.get("intent") or "")
        if pre_route_intent in {"casual_chat", "casual_followup", "conversation_followup"}:
            route_decision = RouteDecision(
                category="standard_conversation",
                reason=f"{pre_route_intent}_pre_resolved",
                confidence=float(pre_route_analysis.get("confidence") or 0.85),
                model=router_config.default_model,
                generation_options={"temperature": 0.75},
            )
        else:
            classifier = self._make_classifier(settings, router_config)
            route_decision = route_message(user_message, router_config, classifier=classifier)
        bloodhound_query = detect_bloodhound_query(user_message)
        reality_research_query = detect_reality_research_query(user_message)
        timings["routing_ms"] = _elapsed_ms(route_start)

        if settings.get("auto_precision_mode", True):
            pre_analysis = analyze_intent_cached(user_message, "")
            precision_category = "web_research" if (bloodhound_query or reality_research_query or route_decision.category == "web_research") else route_decision.category
            settings = apply_auto_precision_settings(
                settings,
                str(pre_analysis.get("intent") or "unknown"),
                route_category=precision_category,
                context_policy=str((pre_analysis.get("conversation_intelligence") or {}).get("context_policy") or ""),
            )
            if settings.get("_fast_path_for_turn"):
                settings = dict(settings)
                settings["use_memory"] = False
                settings["use_knowledge_for_chat"] = False
                settings["use_web_for_chat"] = False
                settings["enable_reality_research_agent"] = False
                settings["enable_bloodhound_search"] = False

        memory_start = time.perf_counter()
        memory_context, memory_command = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        timings["memory_context_ms"] = _elapsed_ms(memory_start)
        if memory_command:
            memory_command = self._audit_answer(memory_command, label="adaptive_memory", tool_confirmed=True, settings=settings)
            self.last_provider_result = {"provider": "adaptive_memory", "elapsed": time.perf_counter() - started}
            yield memory_command
            return

        epistemic_start = time.perf_counter()
        reality_check = policy_from({**self.config, **settings}).reality_check
        if (
            reality_check != "off"
            and bool(settings.get("enable_reality_first_reasoning", self.config.get("enable_reality_first_reasoning", True)))
            and not bool(settings.get("_skip_epistemic_for_turn"))
        ):
            epistemic = analyze_epistemic_request(
                user_message,
                route_category="web_research" if bloodhound_query else route_decision.category,
                rag_used=bool(settings.get("use_knowledge_for_chat", True)),
                manual_mode=str(settings.get("epistemic_mode") or self.config.get("epistemic_mode", "auto")),
                reality_check=reality_check,
            )
            self.last_epistemic_assessment = epistemic.to_dict()
        else:
            epistemic = None
            self.last_epistemic_assessment = {"enabled": False}
        timings["epistemic_ms"] = _elapsed_ms(epistemic_start)

        plan_start = time.perf_counter()
        plan = plan_response(
            user_message=user_message,
            messages=messages,
            route_category="web_research" if bloodhound_query else route_decision.category,
            route_reason="bloodhound_search_detected" if bloodhound_query else route_decision.reason,
            settings=settings,
        )
        timings["planner_ms"] = _elapsed_ms(plan_start)
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
            "tags": route_decision.tags,
            "response_mode": plan.mode,
            "response_intent": plan.intent,
            "context_policy": plan.context_policy,
            "conversation_intelligence": plan.diagnostics.get("conversation_intelligence", {}),
            "topic_handling": plan.diagnostics.get("analysis", {}).get("topic_handling", {}),
            "bloodhound_query": bloodhound_query,
            "reality_research_query": reality_research_query,
        }

        pragmatic_function = str(plan.diagnostics.get("analysis", {}).get("pragmatics", {}).get("function") or "")
        topic_handling = dict(plan.diagnostics.get("analysis", {}).get("topic_handling") or {})
        followup_functions = {
            "agreement",
            "proceed",
            "choose_option",
            "choose_all",
            "continue_previous",
            "rejection",
            "backchannel_acknowledgment",
        }

        if plan.intent == "opinion_rating" and pragmatic_function == "risk_assessment":
            answer = "Maybe, but I need the situation first. Tell me what happened and I'll give you the blunt read."
            verification = verify_response(answer, tool_confirmed=True)
            completion = validate_response_against_plan(answer, plan)
            timings["provider_first_token_ms"] = 0.0
            timings["provider_total_ms"] = 0.0
            timings["total_ms"] = _elapsed_ms(started)
            self.last_verification = verification.to_dict()
            self.last_reality_audit = {"enabled": False, "reason": "slang_risk_fast_path"}
            self.last_trust_audit = {}
            log_verification(verification, "slang_risk_fast_path")
            self.last_provider_result = {
                "text": answer,
                "provider": "local_fast_path",
                "model": "",
                "elapsed": float(timings["total_ms"]) / 1000.0,
                "success": True,
                "attempts": [{"provider": "local_fast_path", "success": True}],
                "fallback_reason": "",
                "response_completion": completion,
                "planned_tokens": plan.max_tokens,
                "timings": timings,
                "provider_order": list(settings.get("provider_order") or []),
                "retrieval": {"enabled": False, "used_count": 0, "skipped_reason": "slang_risk_fast_path"},
                "sources": 0,
            }
            self.last_retrieval = self.last_provider_result["retrieval"]
            self._record_response_self_critic(user_message, answer, plan, settings)
            yield answer
            return

        if (
            plan.intent in {"casual_followup", "conversation_followup"}
            and pragmatic_function in followup_functions
            and not self._immediate_previous_assistant(messages)
        ):
            answer = self._conversation_followup_reply(user_message, messages)
            verification = verify_response(answer, tool_confirmed=True)
            completion = validate_response_against_plan(answer, plan)
            timings["provider_first_token_ms"] = 0.0
            timings["provider_total_ms"] = 0.0
            timings["total_ms"] = _elapsed_ms(started)
            self.last_verification = verification.to_dict()
            self.last_reality_audit = {"enabled": False, "reason": "conversation_followup_needs_clarification"}
            self.last_trust_audit = {}
            log_verification(verification, "conversation_followup_needs_clarification")
            self.last_provider_result = {
                "text": answer,
                "provider": "local_followup_clarification",
                "model": "",
                "elapsed": float(timings["total_ms"]) / 1000.0,
                "success": True,
                "attempts": [{"provider": "local_followup_clarification", "success": True}],
                "fallback_reason": "",
                "response_completion": completion,
                "planned_tokens": plan.max_tokens,
                "timings": timings,
                "provider_order": list(settings.get("provider_order") or []),
                "retrieval": {"enabled": False, "used_count": 0, "skipped_reason": "no_immediate_followup_context"},
                "topic_handling": topic_handling,
                "sources": 0,
            }
            self.last_retrieval = self.last_provider_result["retrieval"]
            self._record_response_self_critic(user_message, answer, plan, settings)
            yield answer
            return

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
                second_opinion=bool(settings.get("reality_research_second_opinion", True)),
                compare_meaning=bool(settings.get("reality_research_compare_meaning", True)),
                save_report=True,
                # The command word ("verify ...", "fact check ...") was stripped from the query, so
                # tell the agent this is a claim check; otherwise let it decide from the query.
                verify_claim=True if is_verification_request(user_message) else None,
            )
            report = self.run_reality_research(request, settings, rule_checked=True)
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
            self._record_response_self_critic(user_message, answer, plan, settings)
            yield answer
            return

        if settings.get("enable_bloodhound_search", True) and bloodhound_query:
            if plan.acknowledge:
                yield plan.acknowledgement
            yield f'Bloodhound Search Mode engaged for "{bloodhound_query}".\n\n'
            yield "Expanding query...\n\nSearching sources...\n\nFetching pages...\n\nRanking results...\n\n"
            result = self.run_bloodhound_search(bloodhound_query, settings, rule_checked=True)
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
            self._record_response_self_critic(user_message, answer, plan, settings)
            yield answer
            return

        if settings.get("use_web_for_chat") and route_decision.requires_web_search:
            if plan.acknowledge:
                yield plan.acknowledgement
            query = route_decision.search_query or user_message
            # Work out what the question means and what to search for, search until enough
            # relevant results are in hand, then read pages and stream the brief answer.
            plan_started = time.perf_counter()
            search_plan = self.plan_web_search(user_message, settings)
            if search_plan.source != "model":
                search_plan.queries = [query]  # no plan: search as before
            gathered = gather_research(query, max_results=5, brief=True, plan=search_plan)
            gathered["timings"]["plan_and_search"] = time.perf_counter() - plan_started
            results = gathered["results"]
            summary_started = time.perf_counter()
            model_meta: dict[str, Any] = {}
            model_answered = False
            sentence_sources: list[dict[str, Any]] = []
            if gathered["has_sources"]:
                prompt = build_summary_prompt(query, results, gathered["scraped_pages"], brief=True, meaning=search_plan.topic if search_plan.source == "model" else "")
                request = self._provider_request(
                    prompt,
                    settings,
                    BRIEF_WEB_SUMMARY_OPTIONS,
                    model=settings.get("selected_model") or "",
                )
                chunks: list[str] = []
                for chunk in self.provider_router.stream(request):
                    chunks.append(chunk)
                    yield chunk
                summary = "".join(chunks).strip()
                model_meta = dict(getattr(self.provider_router, "last_stream_metadata", {}) or {})
                model_answered = bool(summary) and bool(model_meta.get("success")) and model_meta.get("provider") != "fallback"
                if model_answered:
                    # Which page states each sentence the model wrote (item 028), for Diagnostics.
                    sentence_sources = [
                        item.to_dict() for item in map_sentences(summary, claim_sources_from(results, gathered["scraped_pages"]))
                    ]
                if not summary:
                    summary = "No summary was generated."
                    yield summary
                if model_answered:
                    # Flag version numbers, years and names the model wrote that its sources don't contain.
                    note = unsourced_numbers_note(summary, prompt) + unsourced_names_note(summary, prompt, user_message)
                else:
                    # What was shown is the fallback notice or a cut-off answer, not a summary.
                    note = (
                        "\n\nThe model did not finish a summary, so the text above is not a summary of these pages. "
                        "They are listed below so you can read them."
                    )
                if note:
                    summary += note
                    yield note
            else:
                # Without sources the model would answer from stale memory; say so instead.
                summary = NO_RESULTS_SUMMARY
                yield summary
            gathered["timings"]["summary"] = time.perf_counter() - summary_started

            answer = summary
            if settings.get("show_sources") and results:
                sources = "\n".join(
                    f"- [{item.get('title') or item.get('url')}]({item.get('url')}) ({item.get('source')})"
                    for item in results
                    if item.get("url")
                )
                if sources:
                    suffix = f"\n\nSources:\n{sources}"
                    answer += suffix
                    yield suffix
            finish_research_session(
                gathered,
                summary,
                settings={"max_results": 5, "scrape_pages": True, "summarize_with_ai": True, "brief": True},
                summary_generated=model_answered,
            )
            audited = self._audit_answer(
                answer,
                label="chat_web",
                route_category="web_research",
                source_count=len(results),
                web_used=True,
                # A "no results" reply isn't confirmed by any tool output.
                tool_confirmed=bool(results),
                settings=settings,
            )
            if audited.startswith(answer) and len(audited) > len(answer):
                yield audited[len(answer):]  # grounding note appended by the audit
            answer = audited
            verification = verify_response(answer, source_count=len(results), web_used=True)
            completion = validate_response_against_plan(answer, plan)
            self.last_verification = verification.to_dict()
            log_verification(verification, "chat_web")
            self.last_provider_result = {
                "provider": "web_research",
                "elapsed": time.perf_counter() - started,
                "response_completion": completion,
                # Which model wrote the summary, if one did.
                "model_provider": str(model_meta.get("provider") or ""),
                "model": str(model_meta.get("model") or ""),
                "success": model_answered,
                "partial": bool(model_meta.get("partial")),
                "attempts": list(model_meta.get("attempts") or []),
                "fallback_reason": "" if model_answered else str(model_meta.get("fallback_reason") or ""),
                "skipped_cloud": list(model_meta.get("skipped_cloud") or []),
                "usage": dict(model_meta.get("usage") or {}),
                "tools_run": ["web_search"],
                "sources": len(results),
                # What was searched for, how often, and what was left out as being about something else.
                "search_plan": dict(gathered.get("plan") or search_plan.to_dict()),
                "searches": list(gathered.get("searches") or []),
                "dropped_results": list(gathered.get("dropped") or []),
                "timings": dict(gathered.get("timings") or {}),
                "sentence_sources": sentence_sources,
            }
            self._record_response_self_critic(user_message, answer, plan, settings)
            return

        prompt_settings = dict(settings)
        prompt_settings["_memory_context_override"] = memory_context
        if epistemic is not None:
            prompt_settings["_epistemic_instruction"] = epistemic.constraints.instruction
        context_policy = str(plan.context_policy or plan.diagnostics.get("context_policy") or "none")
        conversation_intelligence = dict(plan.diagnostics.get("conversation_intelligence") or {})
        if context_policy in {"none", "immediate_turn_only"}:
            prompt_settings["_minimal_context_for_turn"] = True
            prompt_settings["_memory_context_override"] = ""
            prompt_settings["use_memory"] = False
            prompt_settings["use_knowledge_for_chat"] = False
            prompt_settings["use_web_for_chat"] = False
        if context_policy == "immediate_turn_only" and str(conversation_intelligence.get("function") or "") in followup_functions:
            prompt_settings["_minimal_context_for_turn"] = True
            prompt_settings["_include_immediate_previous_assistant"] = True
            if str(conversation_intelligence.get("function") or "") == "backchannel_acknowledgment":
                prompt_settings["_include_immediate_previous_user"] = True
            prompt_settings["_memory_context_override"] = ""
            prompt_settings["use_memory"] = False
            prompt_settings["use_knowledge_for_chat"] = False
        elif context_policy == "project_memory":
            prompt_settings["use_memory"] = True
            prompt_settings["use_knowledge_for_chat"] = False
        elif context_policy == "file_knowledge":
            prompt_settings["use_knowledge_for_chat"] = True
        elif context_policy == "diagnostics":
            prompt_settings["_minimal_context_for_turn"] = True
            prompt_settings["_memory_context_override"] = ""
            prompt_settings["use_memory"] = False
            prompt_settings["use_knowledge_for_chat"] = False
        prompt_start = time.perf_counter()
        options = dict(route_decision.generation_options or {})
        options["num_predict"] = int(plan.max_tokens)
        options["num_ctx"] = int(plan.num_ctx)
        if plan.mode == "short":
            options["temperature"] = min(float(options.get("temperature", 0.7)), 0.7)
        elif plan.mode in {"deep", "research"}:
            options["temperature"] = max(float(options.get("temperature", 0.75)), 0.8)
        if plan.intent == "simple_fact":
            # A short factual answer should not depend on chance. Measured: "What is 7 times 6?"
            # came back 84 once in three at the chat's usual 0.35 to 0.7. Writing keeps its temperature.
            options["temperature"] = min(float(options.get("temperature", 0.7)), 0.1)
        options = self._apply_throughput_profile(options, settings, plan)
        # Decide the model's window first, then pack the prompt to what that window leaves for
        # it. The answer rules are added after packing, so their size is taken off the allowance.
        budget = self._context_budget(route_decision.model or settings.get("selected_model") or "", options, settings, plan)
        if budget is not None:
            rules_tokens = estimate_context_tokens(self.build_planned_chat_prompt("", plan))
            prompt_settings["_max_prompt_tokens"] = max(256, budget.prompt_tokens - rules_tokens)
            options["num_ctx"] = budget.num_ctx
            options["num_predict"] = budget.reply_tokens
        prompt, context = self.build_chat_prompt(
            user_message,
            messages,
            prompt_settings,
            route_decision,
            simple_mode=plan.intent in {"casual_chat", "simple_fact", "math"},
        )
        prompt = self.build_planned_chat_prompt(prompt, plan)
        timings["context_ms"] = _elapsed_ms(prompt_start)
        retrieval_meta = dict(self.last_retrieval or {})
        timings["retrieval_ms"] = float(retrieval_meta.get("elapsed_ms", 0.0) or 0.0)
        source_count = int(retrieval_meta.get("used_count", 0) or 0)
        self.last_context = {
            "prompt_tokens_estimated": estimate_context_tokens(prompt),
            "prompt_tokens_allowed": budget.prompt_tokens if budget else None,
            "num_ctx": budget.num_ctx if budget else None,
            "reply_tokens": int(options["num_predict"]),
            "model_window": budget.model_window if budget else None,
            "limited_by": budget.limited_by if budget else "",
            "trim_steps": list(getattr(context, "trim_steps", []) or []),
            "older_messages": int(getattr(context, "older_messages_total", 0) or 0),
        }
        request = self._provider_request(
            prompt,
            settings,
            options,
            model=route_decision.model or settings.get("selected_model") or "",
            system_prompt=chat_system_prompt(profile, {**self.config, **settings}),
        )
        self.last_prompt = {"system": request.system_prompt, "prompt": prompt, "model": request.model}
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
            self._record_response_self_critic(user_message, answer, plan, settings)
            yield answer
            return
        # For simple answers, use shorter timeout unless the selected local model has a slow first-token window.
        if self._uses_slow_startup_ollama_model(request.model):
            request.timeout = max(min(request.timeout, SLOW_STARTUP_OLLAMA_READ_TIMEOUT), 75.0)
        elif plan.intent == "casual_chat":
            request.timeout = min(request.timeout, 12.0)
        elif plan.intent == "simple_fact":
            request.timeout = min(request.timeout, 12.0)
        elif plan.intent == "creative":
            request.timeout = min(request.timeout, 45.0)
        elif plan.mode == "short":
            request.timeout = min(request.timeout, 25.0)
        elif plan.intent in {"debugging", "troubleshooting", "project_planning"}:
            request.timeout = min(request.timeout, 45.0)
        chunks: list[str] = []
        if plan.acknowledge:
            chunks.append(plan.acknowledgement)
            yield plan.acknowledgement
        provider_start = time.perf_counter()
        provider_raw_chunks: list[str] = []
        provider_visible_chunks: list[str] = []
        first_provider_chunk_at: float | None = None
        guard_buffer = ""
        visible_stream_started = False
        social_presence_turn = self._is_social_presence_turn(plan)
        suppress_provider_stream = social_presence_turn
        # A short conversational reply has stock phrases taken out once it is complete
        # (_repair_social_presence_answer), so its start is held back as before.
        early_start = not self._is_backchannel_turn(plan)
        for chunk in self.provider_router.stream(request):
            if first_provider_chunk_at is None:
                first_provider_chunk_at = time.perf_counter()
                timings["provider_first_token_ms"] = _elapsed_ms(provider_start, first_provider_chunk_at)
            provider_raw_chunks.append(chunk)
            if suppress_provider_stream:
                continue
            if not visible_stream_started:
                guard_buffer += chunk
                if self._looks_like_prompt_scaffolding(guard_buffer):
                    suppress_provider_stream = True
                    guard_buffer = ""
                    continue
                # Hold back only while the text could still be the prompt's own scaffolding. It used to
                # wait for 160 characters, about eight seconds at this machine's 5 tokens a second.
                if len(guard_buffer) >= 160 or "\n" in guard_buffer or (early_start and len(guard_buffer) >= 24 and not self._could_be_scaffolding(guard_buffer)):
                    visible_stream_started = True
                    provider_visible_chunks.append(guard_buffer)
                    chunks.append(guard_buffer)
                    yield guard_buffer
                    guard_buffer = ""
                continue
            provider_visible_chunks.append(chunk)
            chunks.append(chunk)
            yield chunk
        timings["provider_total_ms"] = _elapsed_ms(provider_start)
        provider_meta = dict(getattr(self.provider_router, "last_stream_metadata", {}) or {})
        provider_speed = dict(provider_meta.get("throughput") or {})
        provider_raw_answer = "".join(provider_raw_chunks).strip()
        if suppress_provider_stream or not provider_visible_chunks:
            provider_answer = self._clean_model_answer(provider_raw_answer)
            provider_answer = self._repair_social_presence_answer(provider_answer, user_message, plan)
            if provider_answer:
                chunks.append(provider_answer)
                yield provider_answer
        elif guard_buffer:
            provider_visible_chunks.append(guard_buffer)
            chunks.append(guard_buffer)
            yield guard_buffer

        answer = "".join(chunks).strip()
        answer = self._clean_model_answer(answer)
        answer = self._repair_social_presence_answer(answer, user_message, plan)
        if not answer:
            reason = str(provider_meta.get("fallback_reason") or provider_meta.get("error") or "").strip()
            if not reason:
                failed = [
                    str(item.get("error") or item.get("reason") or "").strip()
                    for item in provider_meta.get("attempts", [])
                    if item and not item.get("success") and str(item.get("error") or item.get("reason") or "").strip()
                ]
                reason = failed[0] if failed else "Provider stream ended without visible text."
            answer = f"Fallback: provider returned no visible assistant response. Reason: {reason}"
            chunks.append(answer)
            yield answer
        # Why the model stopped. "length" means it hit the token limit it was given: the answer is
        # not finished, and is not shown as if it were.
        stopped_because = str(provider_speed.get("done_reason") or "")
        token_limit = int((request.options or {}).get("num_predict") or request.max_tokens or 0)
        if stopped_because == "length" and answer and not answer.startswith("Fallback:"):
            note = f"\n\n[Stopped at the output limit of {token_limit} tokens before the answer was finished. Say \"continue\" for the rest.]"
            chunks.append(note)
            yield note
            answer += note
        elif answer and not answer.startswith("Fallback:"):
            # A length the owner asked for and the model did not keep to is said, not left silent
            # (CN-QA-002): the model ended there by itself, and nothing in the app cut or padded it.
            note = length_note(answer, plan.diagnostics.get("requested_words"))
            if note:
                chunks.append(note)
                yield note
                answer += note
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
        self._record_response_self_critic(user_message, answer, plan, settings)
        provider_result = ProviderResult(
            text=answer,
            provider=str(provider_meta.get("provider") or ";".join(request.provider_order or [])),
            model=str(provider_meta.get("model") or request.model),
            elapsed=time.perf_counter() - started,
            success=bool(provider_meta.get("success", bool(answer))),
        )
        verification = verify_response(answer, source_count=source_count, tool_confirmed=False, web_used=False)
        completion = validate_response_against_plan(answer, plan)
        timings["total_ms"] = _elapsed_ms(started)
        output_tokens_estimate = _estimate_output_tokens(answer)
        provider_seconds = max(float(timings.get("provider_total_ms", 0.0) or 0.0) / 1000.0, 0.001)
        timings["output_tokens_estimate"] = output_tokens_estimate
        timings["output_tokens_per_second_estimate"] = round(output_tokens_estimate / provider_seconds, 2)
        if provider_speed.get("tokens_per_second"):
            timings["provider_tokens_per_second"] = round(float(provider_speed["tokens_per_second"]), 2)
        logger.info(
            "Chat timings intent=%s mode=%s total_ms=%s provider_first_token_ms=%s provider_total_ms=%s retrieval_ms=%s",
            plan.intent,
            plan.mode,
            timings.get("total_ms"),
            timings.get("provider_first_token_ms"),
            timings.get("provider_total_ms"),
            timings.get("retrieval_ms"),
        )
        self.last_provider_result = provider_result.to_dict() | {
            "context_tokens_estimate": context.estimated_tokens,
            "context_trimmed": context.trimmed,
            "context": dict(self.last_context),
            "response_completion": completion,
            "planned_tokens": plan.max_tokens,
            "timings": timings,
            "provider_order": request.provider_order,
            "attempts": provider_meta.get("attempts", []),
            "fallback_reason": provider_meta.get("fallback_reason", ""),
            "partial": bool(provider_meta.get("partial")) or stopped_because == "length",
            "stopped_because": stopped_because,
            "generation": {
                "num_predict": token_limit,
                "num_ctx": (request.options or {}).get("num_ctx"),
                "temperature": (request.options or {}).get("temperature"),
                "requested_words": plan.diagnostics.get("requested_words"),
                "words_written": len(answer.split()),
                "throughput_profile": str(settings.get("throughput_mode") or "balanced"),
            },
            "skipped_cloud": list(provider_meta.get("skipped_cloud") or []),
            "usage": dict(provider_meta.get("usage") or {}),
            "model_note": str(provider_meta.get("model_note") or ""),
            # A label only: the answer is shown exactly as the model wrote it.
            "declined_by_model": looks_like_model_refusal(provider_result.text),
            "retrieval": retrieval_meta,
            "sources": source_count,
            "throughput": {
                "mode": str(settings.get("throughput_mode") or "balanced"),
                "target_tokens_per_second": int(settings.get("target_tokens_per_second") or 0),
                "output_tokens_estimate": output_tokens_estimate,
                "output_tokens_per_second_estimate": timings["output_tokens_per_second_estimate"],
                "provider_tokens_per_second": timings.get("provider_tokens_per_second"),
                "provider_reported": provider_speed,
            },
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


