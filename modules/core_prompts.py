"""How NexusCore builds a chat prompt: memory, retrieved knowledge, the context budget, and the self-critic's hints.

Moved out of NexusCore (modules/nexus_core.py) unchanged; NexusCore is built from this class
(audit item 121). The methods use the attributes NexusCore.__init__ sets.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from modules.context_manager import (
    ContextBundle,
    build_context_bundle,
    estimate_tokens as estimate_context_tokens,
    load_user_fact_records,
)
from modules.internal_prompts import chat_system_prompt
from modules.response_planner import (
    ResponsePlan,
    is_casual_chat_message,
)
from modules.response_self_critic import (
    build_self_critic_prompt_hints,
    evaluate_response_self_critic,
    store_self_critic_observation,
)
from nexus_router import CATEGORY_LABELS, build_routed_prompt
from modules.core_shared import _elapsed_ms

logger = logging.getLogger("modules.nexus_core")  # the same name as before the move


class PromptBuilding:
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
                # The prompt already has the recent conversation in full (build_context_bundle in
                # modules/context_manager.py). Repeating clips of it here cost about 200 tokens a
                # turn and put earlier answers, which may quote web pages, among the app's notes.
                recent_messages=[],
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
            "elapsed_ms": 0.0,
        }
        if not enabled:
            return "", metadata
        started = time.perf_counter()
        try:
            module = self.get_research_module()
            # Only matches that are confident enough go into a chat prompt unasked: an unrelated
            # passage costs prompt space and misleads a small model. (An explicit knowledge
            # query shows weaker matches too, marked as such.)
            results = module.semantic_search(user_message, top_k=top_k, min_confidence="medium")
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
                        "confidence": item.get("confidence", ""),
                        "matched": item.get("matched", ""),
                        "excerpt": excerpt[:500],
                    }
                )
            metadata["result_count"] = len(results)
            metadata["used_count"] = len(chunks)
            metadata["sources"] = sources
            metadata["elapsed_ms"] = _elapsed_ms(started)
            return "\n\n".join(chunks), metadata
        except Exception as exc:
            logger.info("Knowledge retrieval unavailable: %s", exc)
            metadata["error"] = str(exc)
            metadata["elapsed_ms"] = _elapsed_ms(started)
            return "", metadata

    def _retrieved_context(self, user_message: str, enabled: bool, top_k: int = 3) -> str:
        """Compatibility wrapper for older tests and callers."""

        context, metadata = self._retrieve_context(user_message, enabled, top_k=top_k)
        self.last_retrieval = metadata
        return context

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
        if is_casual_chat_message(user_message):
            return True
        context_terms = {
            "file",
            "files",
            "memory",
            "remember",
            "research",
            "source",
            "sources",
            "history",
            "notes",
            "knowledge",
            "project",
        }
        if len(words) <= 3 and not any(term in words for term in context_terms):
            return True
        casual_phrases = {
            "hi",
            "hello",
            "hey",
            "yo",
            "sup",
            "what's up",
            "whats up",
            "what up",
            "hi there",
            "thanks",
            "thank you",
            "good morning",
            "good afternoon",
            "good evening",
        }
        return lowered in casual_phrases

    def _context_budget(self, model: str, options: dict[str, Any], settings: dict[str, Any], plan: ResponsePlan):
        """Window and prompt allowance when the turn goes to the local Ollama model, else None.

        Cloud models have windows far larger than any prompt this app builds, so only the
        character limit applies to them.
        """

        order = list(settings.get("provider_order") or self.config.get("provider_order", []))
        primary = next((name for name in order if name != "fallback"), "")
        if primary != "ollama" or not model:
            return None
        try:
            return self.provider_router.plan_context(
                model,
                requested_ctx=int(options.get("num_ctx") or 0),
                reply_tokens=int(options.get("num_predict") or 512),
                throughput_mode=str(settings.get("throughput_mode") or "balanced"),
                long_task=plan.intent in {"research", "reality_check"} or plan.mode in {"deep", "research"},
                base_url=settings.get("base_url") or "",
            )
        except Exception as exc:
            logger.info("Context budget unavailable: %s", exc)
            return None

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
        minimal_context = bool(settings.get("_minimal_context_for_turn", False))
        if minimal_context:
            # Who the assistant is and how it should sound is said once, in the system prompt, by the
            # owner's text. This line only keeps a quick turn from dragging in old material.
            routed_system = "Answer only the current message. Do not bring in old chat, files, memory, research or unrelated topics."
        else:
            base_prompt = chat_system_prompt(profile, {**self.config, **settings})
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
        memory_context = "" if minimal_context else str(settings.get("_memory_context_override") or "")
        if not memory_context and not minimal_context:
            memory_context, _ = self._memory_context(user_message, messages, bool(settings.get("use_memory")))
        skip_retrieval = minimal_context or self._skip_retrieval_for_simple_chat(user_message, simple_mode)
        retrieval_enabled = bool(settings.get("use_knowledge_for_chat", True)) and not skip_retrieval
        retrieved_context = ""
        skipped_reason = "minimal_context" if minimal_context else ("simple_greeting" if skip_retrieval else "")
        retrieval_meta: dict[str, Any] = {
            "enabled": retrieval_enabled,
            "query": user_message,
            "top_k": int(settings.get("knowledge_top_k", 3)),
            "result_count": 0,
            "used_count": 0,
            "sources": [],
            "error": "",
            "skipped_reason": skipped_reason,
            "elapsed_ms": 0.0,
        }
        if retrieval_enabled:
            retrieved_context, retrieval_meta = self._retrieve_context(
                user_message,
                True,
                top_k=int(settings.get("knowledge_top_k", 3)),
            )
        self.last_retrieval = retrieval_meta
        if minimal_context:
            immediate_previous = ""
            immediate_previous_user = ""
            if settings.get("_include_immediate_previous_assistant"):
                immediate_previous = self._immediate_previous_assistant(messages)
            if settings.get("_include_immediate_previous_user"):
                immediate_previous_user = self._immediate_previous_user(messages)
            previous_parts = []
            if immediate_previous_user:
                previous_parts.append(f"Immediate previous user message:\n{immediate_previous_user}")
            if immediate_previous:
                previous_parts.append(f"Immediate previous assistant message:\n{immediate_previous}")
            previous_block = "\n\n" + "\n\n".join(previous_parts) if previous_parts else ""
            prompt = f"{routed_system}\n\nUser request:\n{str(user_message or '').strip()}\n\nFinal answer:"
            if previous_block:
                prompt = f"{routed_system}{previous_block}\n\nUser request:\n{str(user_message or '').strip()}\n\nFinal answer:"
            context = ContextBundle(
                prompt=prompt,
                recent_history=[
                    item
                    for item in (
                        {"role": "user", "content": immediate_previous_user} if immediate_previous_user else None,
                        {"role": "assistant", "content": immediate_previous} if immediate_previous else None,
                    )
                    if item
                ],
                memory_context="",
                retrieved_context="",
                user_facts=[],
                estimated_tokens=estimate_context_tokens(prompt),
                trimmed=False,
                trust_audit={},
            )
            self.last_trust_audit = {}
            return context.prompt, context
        context_messages = [] if minimal_context else messages
        user_facts = [] if minimal_context else load_user_fact_records()
        recent_message_limit = 0 if minimal_context else int(settings.get("recent_message_limit") or self.config.get("recent_message_limit", 8))
        context = build_context_bundle(
            user_message=user_message,
            messages=context_messages,
            system_prompt=routed_system,
            route_label=CATEGORY_LABELS.get(route_decision.category, route_decision.category),
            route_reason=route_decision.reason,
            memory_context=memory_context,
            retrieved_context=retrieved_context,
            user_facts=user_facts,
            max_context_chars=min(
                int(settings.get("max_context_chars") or self.config.get("max_context_chars", 12000)),
                1800 if minimal_context else 12000,
            ),
            recent_message_limit=recent_message_limit,
            max_prompt_tokens=settings.get("_max_prompt_tokens"),
        )
        self.last_trust_audit = context.trust_audit
        return context.prompt, context

    def build_planned_chat_prompt(self, prompt: str, plan: ResponsePlan) -> str:
        """Append response-planning instructions without exposing hidden reasoning."""

        critic_hints = self._self_critic_prompt_hints(plan.intent)
        compact_rules = {
            "casual_chat": "Reply like a present conversational assistant: brief, natural, and responsive. Do not give technical self-status, define yourself, mention constraints, or use old context.",
            "simple_fact": "Answer in 1-3 short sentences. No bullets unless the user asks.",
            "explanation": "Answer in one compact paragraph when the user asks for one paragraph.",
            "debugging": "Give likely cause first, then the smallest fix or next command. Stay concise.",
            "troubleshooting": "Give likely cause first, then the next concrete check. Stay under 180 words.",
            "project_planning": "Start with '1.'. Give exactly 3 short concrete steps, each under 10 words, with no preamble.",
            "opinion_rating": "Start with Score or Verdict, then a compact reason and next upgrade.",
        }
        if plan.intent in compact_rules and not plan.diagnostics.get("requested_words"):
            base = prompt.rstrip()
            if base.endswith("Final answer:"):
                base = base[: -len("Final answer:")].rstrip()
            extra_rules = []
            social_policy = dict(plan.diagnostics.get("social_presence") or {})
            if social_policy.get("enabled"):
                blocked = "; ".join(str(item) for item in social_policy.get("blocked_phrases", []) if item)
                extra_rules.extend(
                    [
                        "Use only the current social exchange; no memory, research, file context, old reports, or diagnostics.",
                        "Do not sound like a system monitor, corporate status report, or identity disclaimer.",
                        "Do not sound like customer support or a survey. Avoid 'highlight of your day' style questions.",
                        "Keep it compact, human, and matched to the user's tone; do not copy canned example replies.",
                    ]
                )
                if blocked:
                    extra_rules.append(f"Do not use these phrases or close variants: {blocked}.")
            backchannel_policy = dict(plan.diagnostics.get("backchannel_continuity") or {})
            if backchannel_policy.get("enabled"):
                blocked = "; ".join(str(item) for item in backchannel_policy.get("blocked_phrases", []) if item)
                extra_rules.extend(
                    [
                        "Treat the user's acknowledgment as conversation flow, not a phrase to analyze.",
                        "Use only the current message and immediate previous exchange.",
                        "Continue naturally or lightly pivot to the next useful action; keep it short.",
                        "Avoid customer-support phrasing like 'It's great to hear...' or 'What's been a highlight of your day?'",
                        "Let the model write one short natural continuation instead of using a scripted catchphrase.",
                    ]
                )
                if blocked:
                    extra_rules.append(f"Do not use these analysis phrases or close variants: {blocked}.")
            extra_rules.extend(critic_hints)
            extra_block = "".join(f"- {rule}\n" for rule in extra_rules)
            return (
                f"{base}\n\nAnswer rules:\n"
                f"- {compact_rules[plan.intent]}\n"
                f"{extra_block}"
                f"- Maximum output: about {plan.max_tokens} tokens.\n"
                "- Write only the final user-facing answer.\n\n"
                "Final answer:"
            )

        critic_block = ""
        if critic_hints:
            critic_block = "Adaptive response observations:\n" + "".join(f"- {hint}\n" for hint in critic_hints)
        return (
            f"{prompt}\n\n{plan.instructions}\n"
            f"{critic_block}"
            "Output rule: write only the final user-facing answer. Do not restate the user request, "
            "route, response plan, target length, intent, mode, or these instructions."
        )

    def _self_critic_prompt_hints(self, intent: str) -> list[str]:
        try:
            return build_self_critic_prompt_hints(intent=intent, path=self.response_preferences_path)
        except Exception as exc:
            logger.info("Response self-critic hints unavailable: %s", exc)
            return []

    def _record_response_self_critic(
        self,
        user_message: str,
        answer: str,
        plan: ResponsePlan,
        settings: dict[str, Any],
    ) -> None:
        if not bool(settings.get("enable_response_self_critic", False)):
            self.last_response_critic = {"enabled": False, "stored_response_text": False}
            return
        try:
            result = evaluate_response_self_critic(user_message=user_message, answer=answer, plan=plan)
            state = store_self_critic_observation(result, path=self.response_preferences_path)
            self.last_response_critic = result.to_dict() | {
                "stored": True,
                "critic_samples": state.get("samples", 0),
            }
        except Exception as exc:
            logger.info("Response self-critic failed: %s", exc)
            self.last_response_critic = {"stored": False, "error": str(exc), "stored_response_text": False}
