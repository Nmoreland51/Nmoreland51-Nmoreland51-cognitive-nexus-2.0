"""Adaptive memory and feedback layer for Cognitive Nexus."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


PROMOTION_THRESHOLD = 3
MAX_FACTS = 25
MAX_FEEDBACK_EVENTS = 20
MAX_SEED_SNIPPETS = 3
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "been",
    "before",
    "being",
    "from",
    "have",
    "into",
    "just",
    "like",
    "more",
    "need",
    "only",
    "over",
    "really",
    "that",
    "them",
    "then",
    "there",
    "they",
    "this",
    "want",
    "what",
    "when",
    "where",
    "with",
    "would",
    "your",
}


def _timestamp() -> str:
    return datetime.now().isoformat()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def clip_text(text: str, limit: int = 180) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def extract_keywords(text: str, limit: int = 5) -> List[str]:
    keywords: List[str] = []
    for word in re.findall(r"[a-zA-Z]{4,}", text.lower()):
        if word in STOPWORDS:
            continue
        if word not in keywords:
            keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords


@dataclass
class MemoryCandidate:
    key: str
    value: str
    kind: str = "preference"
    count: int = 1
    last_seen: str = field(default_factory=_timestamp)
    source: str = "implicit"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "kind": self.kind,
            "count": self.count,
            "last_seen": self.last_seen,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MemoryCandidate":
        return cls(
            key=str(payload.get("key", "")),
            value=str(payload.get("value", "")),
            kind=str(payload.get("kind", "preference")),
            count=int(payload.get("count", 1)),
            last_seen=str(payload.get("last_seen", _timestamp())),
            source=str(payload.get("source", "implicit")),
        )


@dataclass
class FeedbackEvent:
    turn_id: str
    rating: str
    correction: str = ""
    timestamp: str = field(default_factory=_timestamp)
    inferred_preferences: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "rating": self.rating,
            "correction": self.correction,
            "timestamp": self.timestamp,
            "inferred_preferences": dict(self.inferred_preferences),
        }


@dataclass
class TurnSignals:
    tone_preference: Optional[str] = None
    detail_level: Optional[str] = None
    search_preference: Optional[str] = None
    directness: Optional[str] = None
    frustration: bool = False
    follow_up_depth: Optional[str] = None
    style_mirroring: Optional[str] = None
    correction_text: str = ""
    explicit_memory_text: str = ""
    forget_request: str = ""
    explicit_preferences: Dict[str, str] = field(default_factory=dict)
    implicit_preferences: Dict[str, str] = field(default_factory=dict)
    topic_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tone_preference": self.tone_preference,
            "detail_level": self.detail_level,
            "search_preference": self.search_preference,
            "directness": self.directness,
            "frustration": self.frustration,
            "follow_up_depth": self.follow_up_depth,
            "style_mirroring": self.style_mirroring,
            "correction_text": self.correction_text,
            "explicit_memory_text": self.explicit_memory_text,
            "forget_request": self.forget_request,
            "explicit_preferences": dict(self.explicit_preferences),
            "implicit_preferences": dict(self.implicit_preferences),
            "topic_keywords": list(self.topic_keywords),
        }


@dataclass
class AdaptivePolicy:
    tone: str = "warm"
    detail_level: str = "balanced"
    search_preference: str = "explicit_plus_current"
    directness: str = "balanced"
    style_mirroring: str = "adaptive"
    correction_note: str = ""

    def to_prompt_text(self) -> str:
        lines = [
            "Adaptive response policy:",
            f"- Tone: {self.tone}",
            f"- Detail level: {self.detail_level}",
            f"- Search preference: {self.search_preference}",
            f"- Directness: {self.directness}",
            f"- Style mirroring: {self.style_mirroring}",
        ]
        if self.correction_note:
            lines.append(f"- Recent correction: {clip_text(self.correction_note, 120)}")
        return "\n".join(lines)


@dataclass
class ContextBundle:
    policy: AdaptivePolicy
    short_term_context: List[str] = field(default_factory=list)
    profile_summary: List[str] = field(default_factory=list)
    episodic_memories: List[str] = field(default_factory=list)
    seed_knowledge: List[str] = field(default_factory=list)

    @property
    def rendered_context(self) -> str:
        sections = [self.policy.to_prompt_text()]
        if self.profile_summary:
            sections.append("Persistent profile memory:\n" + "\n".join(f"- {item}" for item in self.profile_summary))
        if self.short_term_context:
            sections.append("Recent conversation:\n" + "\n".join(f"- {item}" for item in self.short_term_context))
        if self.episodic_memories:
            sections.append("Relevant past context:\n" + "\n".join(f"- {item}" for item in self.episodic_memories))
        if self.seed_knowledge:
            sections.append("Seeded knowledge:\n" + "\n".join(f"- {item}" for item in self.seed_knowledge))
        return "\n\n".join(section for section in sections if section.strip())


@dataclass
class UserProfile:
    facts: List[Dict[str, Any]] = field(default_factory=list)
    preferences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    recurring_topics: Dict[str, int] = field(default_factory=dict)
    recent_feedback: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=_timestamp)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": list(self.facts),
            "preferences": dict(self.preferences),
            "patterns": dict(self.patterns),
            "recurring_topics": dict(self.recurring_topics),
            "recent_feedback": list(self.recent_feedback),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UserProfile":
        return cls(
            facts=list(payload.get("facts", [])),
            preferences=dict(payload.get("preferences", {})),
            patterns=dict(payload.get("patterns", {})),
            recurring_topics=dict(payload.get("recurring_topics", {})),
            recent_feedback=list(payload.get("recent_feedback", [])),
            updated_at=str(payload.get("updated_at", _timestamp())),
        )


class AdaptiveMemoryManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_file = self.data_dir / "user_profile.json"
        self.feedback_log_file = self.data_dir / "feedback_log.jsonl"
        self.memory_candidates_file = self.data_dir / "memory_candidates.json"
        self.seed_knowledge_dir = self.data_dir / "seed_knowledge"
        self.seed_knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.profile = self._load_profile()
        self.memory_candidates = self._load_candidates()

    def reload(self) -> None:
        self.profile = self._load_profile()
        self.memory_candidates = self._load_candidates()

    def create_turn_id(self) -> str:
        return f"turn_{uuid.uuid4().hex[:12]}"

    def _load_profile(self) -> UserProfile:
        if not self.profile_file.exists():
            return UserProfile()
        try:
            return UserProfile.from_dict(json.loads(self.profile_file.read_text(encoding="utf-8")))
        except Exception:
            return UserProfile()

    def _load_candidates(self) -> Dict[str, MemoryCandidate]:
        if not self.memory_candidates_file.exists():
            return {}
        try:
            payload = json.loads(self.memory_candidates_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        candidates: Dict[str, MemoryCandidate] = {}
        for key, value in payload.items():
            candidates[key] = MemoryCandidate.from_dict(value)
        return candidates

    def _save_profile(self) -> None:
        self.profile.updated_at = _timestamp()
        self.profile_file.write_text(json.dumps(self.profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_candidates(self) -> None:
        payload = {key: candidate.to_dict() for key, candidate in self.memory_candidates.items()}
        self.memory_candidates_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def clear_all(self) -> None:
        self.profile = UserProfile()
        self.memory_candidates = {}
        self._save_profile()
        self._save_candidates()
        if self.feedback_log_file.exists():
            self.feedback_log_file.unlink()

    def _store_preference(self, key: str, value: str, source: str) -> None:
        self.profile.preferences[key] = {
            "value": value,
            "source": source,
            "updated_at": _timestamp(),
        }

    def _store_pattern(self, key: str, value: str, count: int) -> None:
        self.profile.patterns[key] = {
            "value": value,
            "count": count,
            "updated_at": _timestamp(),
        }

    def _observe_candidate(self, key: str, value: str) -> None:
        candidate_key = f"{key}:{value}"
        candidate = self.memory_candidates.get(candidate_key)
        if candidate is None:
            candidate = MemoryCandidate(key=key, value=value)
            self.memory_candidates[candidate_key] = candidate
        else:
            candidate.count += 1
            candidate.last_seen = _timestamp()

        if candidate.count >= PROMOTION_THRESHOLD:
            self._store_pattern(key, value, candidate.count)

    def _extract_fact_kind(self, text: str) -> str:
        normalized = normalize_text(text)
        if normalized.startswith("my name is") or normalized.startswith("call me"):
            return "identity"
        if normalized.startswith("i prefer") or normalized.startswith("i like"):
            return "preference"
        if normalized.startswith("my favorite"):
            return "favorite"
        return "note"

    def remember_text(self, text: str) -> str:
        content = text.strip()
        if not content:
            return "Tell me what you want me to remember."

        signals = self.extract_turn_signals(content)
        stored_preference = False
        for key, value in signals.explicit_preferences.items():
            self._store_preference(key, value, "explicit_memory")
            stored_preference = True

        if not stored_preference or self._extract_fact_kind(content) != "preference":
            fact_entry = {
                "id": f"fact_{uuid.uuid4().hex[:8]}",
                "text": content,
                "kind": self._extract_fact_kind(content),
                "source": "explicit_memory",
                "updated_at": _timestamp(),
            }
            self.profile.facts = [item for item in self.profile.facts if normalize_text(item.get("text", "")) != normalize_text(content)]
            self.profile.facts.append(fact_entry)
            self.profile.facts = self.profile.facts[-MAX_FACTS:]

        self._save_profile()
        self._save_candidates()
        return f"I'll remember that: {clip_text(content, 100)}"

    def forget_text(self, text: str) -> str:
        query = normalize_text(text)
        query_terms = [term for term in query.split() if term]
        removed_facts = 0
        removed_preferences = 0
        removed_patterns = 0

        def matches(candidate_text: str) -> bool:
            normalized_candidate = normalize_text(candidate_text)
            if query in normalized_candidate:
                return True
            return any(term in normalized_candidate for term in query_terms)

        original_facts = list(self.profile.facts)
        self.profile.facts = [item for item in original_facts if not matches(item.get("text", ""))]
        removed_facts = len(original_facts) - len(self.profile.facts)

        for key in list(self.profile.preferences.keys()):
            value = normalize_text(str(self.profile.preferences[key].get("value", "")))
            if matches(key) or matches(value):
                del self.profile.preferences[key]
                removed_preferences += 1

        for key in list(self.profile.patterns.keys()):
            value = normalize_text(str(self.profile.patterns[key].get("value", "")))
            if matches(key) or matches(value):
                del self.profile.patterns[key]
                removed_patterns += 1

        for candidate_key, candidate in list(self.memory_candidates.items()):
            if matches(candidate.key) or matches(candidate.value):
                del self.memory_candidates[candidate_key]

        self._save_profile()
        self._save_candidates()

        if removed_facts or removed_preferences or removed_patterns:
            return "I forgot the matching memory."
        return "I couldn't find a matching saved memory to forget."

    def handle_memory_command(self, message: str) -> Optional[str]:
        remember_match = re.match(r"^\s*(?:please\s+)?remember(?:\s+this)?(?:\s*:\s*|\s+)(.+)$", message, flags=re.IGNORECASE)
        if remember_match:
            return self.remember_text(remember_match.group(1))

        forget_match = re.match(r"^\s*(?:please\s+)?forget(?:\s+this)?(?:\s*:\s*|\s+)(.+)$", message, flags=re.IGNORECASE)
        if forget_match:
            return self.forget_text(forget_match.group(1))

        return None

    def extract_turn_signals(self, message: str, recent_messages: Optional[List[Dict[str, Any]]] = None) -> TurnSignals:
        text = message.strip()
        normalized = normalize_text(text)
        signals = TurnSignals(topic_keywords=extract_keywords(text))

        if not normalized:
            return signals

        explicit_map = {
            "tone": {
                "casual": [
                    "be more casual",
                    "talk more casually",
                    "more casual",
                    "less formal",
                    "be chill",
                    "i prefer casual replies",
                    "i like casual replies",
                ],
                "formal": [
                    "be more formal",
                    "be professional",
                    "more professional",
                    "more formal",
                    "i prefer formal replies",
                    "i like formal replies",
                ],
            },
            "detail_level": {
                "short": [
                    "keep it short",
                    "be shorter",
                    "be concise",
                    "keep it brief",
                    "short version",
                    "brief answer",
                    "i prefer short answers",
                    "i like short answers",
                    "i prefer brief answers",
                ],
                "detailed": [
                    "more detail",
                    "go deeper",
                    "more detailed",
                    "step by step",
                    "explain more",
                    "i prefer detailed answers",
                    "i like detailed explanations",
                ],
            },
            "search_preference": {
                "only_when_requested": [
                    "dont search unless i ask",
                    "don t search unless i ask",
                    "do not search unless i ask",
                    "don't search unless i ask",
                    "just chat",
                    "just talk to me",
                    "i prefer you not search unless i ask",
                ],
                "adaptive": ["search when needed", "look it up when needed", "feel free to search"],
            },
            "directness": {
                "direct": ["be direct", "get to the point", "be blunt", "i prefer direct answers"],
                "warm": ["be warmer", "be more friendly", "be nicer", "be gentler", "i prefer warmer replies"],
            },
        }

        for value, phrases in explicit_map["tone"].items():
            if any(phrase in normalized for phrase in phrases):
                signals.tone_preference = value
                signals.explicit_preferences["tone"] = value
                break

        for value, phrases in explicit_map["detail_level"].items():
            if any(phrase in normalized for phrase in phrases):
                signals.detail_level = value
                signals.explicit_preferences["detail_level"] = value
                break

        for value, phrases in explicit_map["search_preference"].items():
            if any(phrase in normalized for phrase in phrases):
                signals.search_preference = value
                signals.explicit_preferences["search_preference"] = value
                break

        for value, phrases in explicit_map["directness"].items():
            if any(phrase in normalized for phrase in phrases):
                signals.directness = value
                signals.explicit_preferences["directness"] = value
                break

        if any(phrase in normalized for phrase in ("tell me more", "go deeper", "expand on that", "how so")):
            signals.follow_up_depth = "detailed"
            signals.implicit_preferences["detail_level"] = "detailed"

        if any(phrase in normalized for phrase in ("that s wrong", "that is wrong", "not what i meant", "no i meant", "i meant")):
            signals.frustration = True
            signals.correction_text = text

        if len(text.split()) <= 4 and text.endswith("?"):
            signals.style_mirroring = "brief_follow_up"

        return signals

    def observe_turn(self, message: str, signals: TurnSignals) -> None:
        for key, value in signals.explicit_preferences.items():
            self._store_preference(key, value, "explicit_signal")

        for key, value in signals.implicit_preferences.items():
            self._observe_candidate(key, value)

        for keyword in signals.topic_keywords:
            self.profile.recurring_topics[keyword] = self.profile.recurring_topics.get(keyword, 0) + 1

        self._save_profile()
        self._save_candidates()

    def resolve_policy(self, signals: Optional[TurnSignals] = None) -> AdaptivePolicy:
        policy = AdaptivePolicy()

        preferences = self.profile.preferences
        patterns = self.profile.patterns

        if "tone" in preferences:
            policy.tone = str(preferences["tone"].get("value", policy.tone))
        elif "tone" in patterns:
            policy.tone = str(patterns["tone"].get("value", policy.tone))

        if "detail_level" in preferences:
            policy.detail_level = str(preferences["detail_level"].get("value", policy.detail_level))
        elif "detail_level" in patterns:
            policy.detail_level = str(patterns["detail_level"].get("value", policy.detail_level))

        if "search_preference" in preferences:
            policy.search_preference = str(preferences["search_preference"].get("value", policy.search_preference))
        elif "search_preference" in patterns:
            policy.search_preference = str(patterns["search_preference"].get("value", policy.search_preference))

        if "directness" in preferences:
            policy.directness = str(preferences["directness"].get("value", policy.directness))
        elif "directness" in patterns:
            policy.directness = str(patterns["directness"].get("value", policy.directness))

        for event in self.profile.recent_feedback[-3:]:
            for key, value in event.get("inferred_preferences", {}).items():
                if key == "tone":
                    policy.tone = value
                elif key == "detail_level":
                    policy.detail_level = value
                elif key == "search_preference":
                    policy.search_preference = value
                elif key == "directness":
                    policy.directness = value

        if signals:
            if signals.tone_preference:
                policy.tone = signals.tone_preference
            if signals.detail_level:
                policy.detail_level = signals.detail_level
            elif signals.follow_up_depth == "detailed":
                policy.detail_level = "detailed"
            if signals.search_preference:
                policy.search_preference = signals.search_preference
            if signals.directness:
                policy.directness = signals.directness
            if signals.style_mirroring:
                policy.style_mirroring = signals.style_mirroring
            if signals.correction_text:
                policy.correction_note = signals.correction_text

        return policy

    def _load_seed_knowledge(self) -> List[str]:
        entries: List[str] = []
        for path in sorted(self.seed_knowledge_dir.glob("**/*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            try:
                if suffix in {".txt", ".md"}:
                    entries.append(path.read_text(encoding="utf-8", errors="ignore"))
                elif suffix == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    entries.append(json.dumps(payload, ensure_ascii=False))
                elif suffix == ".jsonl":
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    entries.extend(lines[:10])
            except Exception:
                continue
        return entries

    def search_seed_knowledge(self, query: str) -> List[str]:
        query_terms = extract_keywords(query, limit=6)
        if not query_terms:
            return []
        scored: List[tuple[int, str]] = []
        for entry in self._load_seed_knowledge():
            normalized = normalize_text(entry)
            score = sum(1 for term in query_terms if term in normalized)
            if score:
                scored.append((score, clip_text(entry, 220)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [snippet for _, snippet in scored[:MAX_SEED_SNIPPETS]]

    def build_context_bundle(
        self,
        query: str,
        recent_messages: Optional[List[Dict[str, Any]]],
        chat_history: List[Dict[str, Any]],
        topic_knowledge: Dict[str, Any],
        learned_facts: Dict[str, Any],
        *,
        signals: Optional[TurnSignals] = None,
        policy: Optional[AdaptivePolicy] = None,
    ) -> ContextBundle:
        active_policy = policy or self.resolve_policy(signals)
        query_terms = extract_keywords(query, limit=6)

        short_term_context: List[str] = []
        for message in (recent_messages or [])[-6:]:
            role = str(message.get("role", "user")).capitalize()
            content = clip_text(str(message.get("content", "")), 140)
            if content:
                short_term_context.append(f"{role}: {content}")

        episodic_memories: List[str] = []
        for record in reversed(chat_history[-30:]):
            haystacks = [
                normalize_text(str(record.get("user", ""))),
                normalize_text(str(record.get("assistant", ""))),
            ]
            if query_terms and any(term in haystack for haystack in haystacks for term in query_terms):
                episodic_memories.append(
                    f"Past turn: user said '{clip_text(str(record.get('user', '')), 90)}'"
                )
            if len(episodic_memories) >= 3:
                break

        profile_summary: List[str] = []
        for key, value in self.profile.preferences.items():
            profile_summary.append(f"Preference - {key}: {value.get('value', '')}")
        for fact in self.profile.facts[-5:]:
            profile_summary.append(f"Fact - {clip_text(str(fact.get('text', '')), 120)}")
        for key, pattern in self.profile.patterns.items():
            profile_summary.append(f"Pattern - {key}: {pattern.get('value', '')}")

        if self.profile.recurring_topics:
            top_topics = sorted(self.profile.recurring_topics.items(), key=lambda item: item[1], reverse=True)[:3]
            if top_topics:
                profile_summary.append("Recurring topics: " + ", ".join(topic for topic, _ in top_topics))

        for fact_key, fact_value in learned_facts.items():
            if any(term in normalize_text(fact_key) for term in query_terms):
                profile_summary.append(f"Knowledge - {fact_key}: {clip_text(str(fact_value), 90)}")

        for topic, data in topic_knowledge.items():
            if any(term in normalize_text(topic) for term in query_terms):
                findings = ""
                if isinstance(data, dict) and data.get("learned"):
                    latest = data["learned"][-1]
                    findings = clip_text(str(latest.get("findings", "")), 120)
                profile_summary.append(f"Topic - {topic}: {findings or 'Known topic'}")

        return ContextBundle(
            policy=active_policy,
            short_term_context=short_term_context,
            profile_summary=profile_summary[:8],
            episodic_memories=episodic_memories,
            seed_knowledge=self.search_seed_knowledge(query),
        )

    def record_feedback(self, turn_id: str, rating: str, correction: str = "") -> FeedbackEvent:
        correction = correction.strip()
        event = FeedbackEvent(turn_id=turn_id, rating=rating, correction=correction)

        if correction:
            correction_signals = self.extract_turn_signals(correction)
            for key, value in correction_signals.explicit_preferences.items():
                event.inferred_preferences[key] = value
                self._store_preference(key, value, "correction")

        self.feedback_log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.feedback_log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        self.profile.recent_feedback.append(event.to_dict())
        self.profile.recent_feedback = self.profile.recent_feedback[-MAX_FEEDBACK_EVENTS:]
        self._save_profile()
        self._save_candidates()
        return event

    def get_memory_overview(self) -> Dict[str, Any]:
        return {
            "facts": list(self.profile.facts),
            "preferences": dict(self.profile.preferences),
            "patterns": dict(self.profile.patterns),
            "feedback_count": len(self.profile.recent_feedback),
            "seed_knowledge_files": len(list(self.seed_knowledge_dir.glob("**/*"))),
        }
