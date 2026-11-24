"""NexusCore's research outside the chat: web research, Bloodhound search, the Reality-First research agent and knowledge answers.

Moved out of NexusCore (modules/nexus_core.py) unchanged; NexusCore is built from this class
(audit item 121). The methods use the attributes NexusCore.__init__ sets.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from modules import retellings
from modules.reality_research_agent import (
    ResearchReport,
    ResearchRequest,
    run_reality_research,
)
from modules.research import query_knowledge
from modules.research_plan import PLAN_OPTIONS, SearchPlan, as_typed, plan_search
from modules.web_research import (
    run_research_session,
)
from search.bloodhound_search import (
    default_bloodhound_config,
    run_bloodhound_search,
)
from modules.core_shared import BRIEF_WEB_SUMMARY_OPTIONS, FULL_WEB_SUMMARY_OPTIONS

logger = logging.getLogger("modules.nexus_core")  # the same name as before the move


class ResearchServices:
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
        brief: bool = False,
    ) -> dict[str, Any]:
        """Run web research through the central provider router for summaries.

        brief=True gives a short answer (see BRIEF_WEB_SUMMARY_OPTIONS). Chat streams its brief
        answer instead; see _stream_web_answer.
        """

        self._require_content_rule(query, settings)
        options = BRIEF_WEB_SUMMARY_OPTIONS if brief else FULL_WEB_SUMMARY_OPTIONS
        ai_callback = None
        planner = None
        if summarize_with_ai:
            def ai_callback(prompt: str) -> str:
                return self._model_text(prompt, settings, options)

            def planner(question: str) -> SearchPlan:
                return self.plan_web_search(question, settings)

        started = time.perf_counter()
        self.provider_router.last_stream_metadata = {}
        session = run_research_session(
            query,
            max_results=max_results,
            scrape_pages=scrape_pages,
            summarize_with_ai=summarize_with_ai,
            save_locally=save_locally,
            save_to_memory=save_to_memory,
            ai_callback=ai_callback,
            brief=brief,
            planner=planner,
        )
        session["produced_by"] = self._produced_by(
            "web_research", started, answered=bool(session.get("summary_generated")), tools=["web_search"]
        )
        return session

    def plan_web_search(self, question: str, settings: dict[str, Any]) -> SearchPlan:
        """What a question for the web means and what to search for (modules/research_plan.py).

        One model call, held to a JSON Schema. Switched off with the setting plan_web_search, or
        when no model answers: the question is then searched as typed.
        """

        if not settings.get("plan_web_search", self.config.get("plan_web_search", True)):
            return as_typed(question, "switched off")
        return plan_search(question, self._json_asker(settings, PLAN_OPTIONS))

    def _json_asker(self, settings: dict[str, Any], options: dict[str, Any]) -> Any:
        """ask(prompt, schema) -> the model's reply, held to the JSON Schema where the provider can do that."""

        def ask(prompt: str, schema: dict[str, Any]) -> str:
            request = self._provider_request(prompt, settings, dict(options), model=settings.get("selected_model") or "")
            request.response_schema = schema
            return self.provider_router.generate_or_raise(request).text

        return ask

    def run_bloodhound_search(self, query: str, settings: dict[str, Any], *, rule_checked: bool = False) -> dict[str, Any]:
        """Run Bloodhound Search Mode through the shared provider router.

        rule_checked=True is passed by a chat turn, which has already applied the content rule to the message.
        """

        if not rule_checked:
            self._require_content_rule(query, settings)
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
            return self._model_text(prompt, settings, {"temperature": 0.2, "num_predict": 700, "num_ctx": 4096})

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
        *,
        rule_checked: bool = False,
    ) -> ResearchReport:
        """Run the signature source-grounded research workflow.

        rule_checked=True is passed by a chat turn, which has already applied the content rule to the message.
        """

        if not rule_checked:
            self._require_content_rule(request.query, settings)
        def ai_callback(prompt: str) -> str:
            return self._model_text(prompt, settings, {"temperature": 0.2, "num_predict": 700, "num_ctx": 4096})

        def second_opinion(prompt: str) -> str:
            # One word is wanted; a short answer keeps each passage to a few seconds on a CPU.
            return self._model_text(prompt, settings, {"temperature": 0.0, "num_predict": 6, "num_ctx": 2048})

        def meaning() -> tuple[Any, str]:
            return retellings.meaning_embedder(str(settings.get("base_url") or self.config.get("ollama_url") or "") or None)

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
            second_opinion_callback=second_opinion if settings.get("provider_order") else None,
            meaning_embedder=meaning,
        )

    def answer_knowledge(
        self,
        query: str,
        settings: dict[str, Any],
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Query local knowledge and synthesize through provider router when available."""

        use_ai_synthesis = bool(settings.get("knowledge_use_ai", False))
        if use_ai_synthesis:
            # Looking passages up writes nothing. The rule matters once a model answers from them.
            self._require_content_rule(query, settings)
        module = self.get_research_module()

        def ai_callback(prompt: str) -> str:
            return self._model_text(prompt, settings, {"temperature": 0.25, "num_predict": 420, "num_ctx": 4096})

        started = time.perf_counter()
        self.provider_router.last_stream_metadata = {}
        result = query_knowledge(
            module,
            query,
            model=settings.get("selected_model"),
            base_url=settings.get("base_url", ""),
            provider_ready=use_ai_synthesis,
            top_k=top_k,
            ai_callback=ai_callback if use_ai_synthesis else None,
        )
        result["produced_by"] = self._produced_by(
            "local_knowledge", started, answered=bool(result.get("model_answered")), tools=["local_knowledge"]
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
