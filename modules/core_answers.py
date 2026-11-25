"""What NexusCore does to a model's answer before showing it: prompt scaffolding removed, social replies repaired, the reality check, compression and hedging.

Moved out of NexusCore (modules/nexus_core.py) unchanged; NexusCore is built from this class
(audit item 121). The methods use the attributes NexusCore.__init__ sets.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from core.reality_grounding import audit_answer
from modules.response_planner import (
    ResponsePlan,
    SOCIAL_PRESENCE_BLOCKED_PHRASES,
)

logger = logging.getLogger("modules.nexus_core")  # the same name as before the move


class AnswerFinishing:
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

    def _could_be_scaffolding(self, text: str) -> bool:
        """True while the start of an answer could still turn out to be leaked prompt scaffolding."""

        prefix = (text or "").lstrip().lower()
        starts = ("user request:", "response plan:", "adaptive response plan:")
        if any(start.startswith(prefix) or prefix.startswith(start) for start in starts):
            return True
        return any(marker in prefix for marker in ("user request:", "response plan:", "target length:", "intent:", "mode:"))

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

    def _is_social_presence_turn(self, plan: ResponsePlan) -> bool:
        policy = dict(plan.diagnostics.get("social_presence") or {})
        return plan.intent == "casual_chat" and bool(policy.get("enabled"))

    def _is_backchannel_turn(self, plan: ResponsePlan) -> bool:
        policy = dict(plan.diagnostics.get("backchannel_continuity") or {})
        return plan.intent == "conversation_followup" and bool(policy.get("enabled"))

    def _has_robotic_social_phrase(self, text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        return any(phrase in normalized for phrase in SOCIAL_PRESENCE_BLOCKED_PHRASES)

    def _has_scripted_social_phrase(self, text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        scripted_markers = (
            "it's great to hear",
            "great to hear that",
            "things are going well for you",
            "what's been a highlight",
            "highlight of your day",
            "how's it going?",
            "how is it going?",
            "what's been keeping you busy today",
        )
        return any(marker in normalized for marker in scripted_markers)

    def _repair_social_presence_answer(self, answer: str, user_message: str, plan: ResponsePlan) -> str:
        """Trim bad social clauses only when the model left a usable remainder."""

        eligible = self._is_social_presence_turn(plan) or self._is_backchannel_turn(plan)
        if not eligible or not (self._has_robotic_social_phrase(answer) or self._has_scripted_social_phrase(answer)):
            return answer
        parts = re.split(r"(?<=[.!?])\s+", str(answer or "").strip())
        kept = [
            part.strip()
            for part in parts
            if part.strip()
            and not self._has_robotic_social_phrase(part)
            and not self._has_scripted_social_phrase(part)
        ]
        repaired = " ".join(kept).strip()
        if repaired:
            return repaired
        return answer

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
        
        # The research-simulation route used to delete words such as "Maybe", "I think", "However," and
        # "Note that" from the stored copy of the answer, and to collapse its paragraphs, depending on
        # the persona's numbers. Removed on 2026-11-25 (register R-A19 c): the app does not rewrite a
        # model's sentences.
        return cleaned_answer
