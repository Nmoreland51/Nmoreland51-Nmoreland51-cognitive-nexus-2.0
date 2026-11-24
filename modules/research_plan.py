"""Working out what a question means before searching, judging what comes back, and checking names.

The owner asked the app for "the best weed in Omaha" (2026-11-23) and found four faults: the
question was searched as typed and came back with lawn-care firms; whatever came back went to the
model; no second search was tried when the first was poor; and the answer named a shop that the
sources shown did not mention. This module stands between a question and the model:

1. plan_search: the local model reads the question once, before anything is searched, and returns
   (held to a JSON Schema) what it is about with any ambiguous word spelled out, up to three search
   queries, words that would appear only in pages about another meaning, and what kind of page
   would answer it. Without a model the question is searched as typed, as before.
2. judge_results: a result that carries one of those other-meaning words and fewer words of the
   question's own meaning is dropped. Listing pages (search results, "top 10" pages) are kept but
   put after pages about a particular place or product.
3. gather_planned: the plan's queries are searched in turn until enough relevant results are
   found, at most three searches, so a poor first search is refined instead of answered from.
4. unsourced_names: names of businesses, products and places in an answer that appear in none of
   its sources and not in the question. The app lists them under the answer.

None of this decides what may be asked: it decides which pages are worth the model's attention.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import jsonschema

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "maxLength": 300},
        "queries": {"type": "array", "items": {"type": "string", "maxLength": 120}, "minItems": 1, "maxItems": 3},
        "off_topic": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 8},
        "wants": {"type": "string", "maxLength": 200},
    },
    "required": ["topic", "queries", "off_topic", "wants"],
}

PLAN_PROMPT = """Before a web search is made for a question, work out what the person means.

Question: {question}

If a word in the question has more than one meaning, choose the meaning the rest of the question
points to, and say it plainly. For example, for "best python course in Austin" the person means
the programming language, not the snake.

Reply with one JSON object:
- topic: one sentence saying what the person wants to know, with any ambiguous word replaced by
  its meaning here.
- queries: two or three web search queries, the most specific first, in plain unambiguous words.
  Keep any place name from the question.
- off_topic: up to six words or short phrases that would appear only in pages about another
  meaning of the question's words (for the example: snake, reptile, venom). An empty list if
  nothing in the question is ambiguous.
- wants: what kind of page would answer the question (for the example: course listings with
  dates and prices).
"""

PLAN_OPTIONS = {"temperature": 0.0, "num_predict": 220, "num_ctx": 2048}
MIN_RELEVANT = 2
MAX_SEARCHES = 3

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")
_STOP = frozenset(
    "a an and are as at be best by can do does for from good how i in is it its me my near of on or the to top what where which who why with you your "
    "most more much many any some this that these those there their they them was were will would should could about into over than then also just "
    "buy get find local nearby area city place places review reviews rating ratings price prices cost costs cheap cheapest shop shops store stores "
    "list guide open hours deal deals today now new latest current 2024 2025 2026 2027".split()
)
_LISTING_PATH = re.compile(r"/(search|find|s|results|biz_list|nearby|near-me|top-?\d+)(/|$|\?)|[?&](find_desc|q|query|search)=", re.IGNORECASE)
_LISTING_TITLE = re.compile(r"^\s*(the\s+)?(top|best)\s+\d+\b|\bnear\s+me\b|\bnear\s+[A-Z]", re.IGNORECASE)


def _stem(word: str) -> str:
    word = word.lower().strip("'-")
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(str(text or "").lower())}


def _has_phrase(text: str, phrase: str) -> bool:
    phrase = " ".join(_WORD.findall(phrase.lower()))
    if not phrase:
        return False
    return re.search(r"\b" + re.escape(phrase) + r"(e?s)?\b", " ".join(_WORD.findall(str(text or "").lower()))) is not None


@dataclass
class SearchPlan:
    question: str
    topic: str
    queries: list[str]
    off_topic: list[str] = field(default_factory=list)
    wants: str = ""
    source: str = "model"  # model | as_typed (no model, or its reply could not be used)
    note: str = ""

    @property
    def sense_words(self) -> set[str]:
        """Words of the question's meaning that the question itself does not contain ("cannabis" for "weed")."""

        asked = _words(self.question)
        found = _words(" ".join([self.topic, *self.queries]))
        return {word for word in found - asked if len(word) >= 4 and word not in _STOP and not word.isdigit()}

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "topic": self.topic, "queries": list(self.queries), "off_topic": list(self.off_topic), "wants": self.wants, "source": self.source, "note": self.note}


def as_typed(question: str, note: str = "") -> SearchPlan:
    return SearchPlan(question=question, topic=question, queries=[question], source="as_typed", note=note)


def plan_search(question: str, ask: Callable[[str, dict[str, Any]], str] | None) -> SearchPlan:
    """Ask the model what the question means. `ask(prompt, schema)` returns the model's reply text."""

    question = str(question or "").strip()
    if ask is None:
        return as_typed(question, "no model")
    try:
        data = json.loads(ask(PLAN_PROMPT.format(question=question), PLAN_SCHEMA))
        jsonschema.validate(data, PLAN_SCHEMA)
    except Exception as exc:  # no model, or a reply that is not the promised shape: search as typed
        return as_typed(question, f"the plan could not be made ({type(exc).__name__})")
    queries: list[str] = []
    for query in data["queries"]:
        query = " ".join(str(query).split())
        if query and query.lower() not in {item.lower() for item in queries}:
            queries.append(query)
    # A word of the question itself is never treated as off-topic: that would throw out what was asked for.
    asked = " ".join(_WORD.findall(question.lower()))
    off_topic = [phrase.strip() for phrase in data["off_topic"] if phrase.strip() and not _has_phrase(asked, phrase)]
    return SearchPlan(question=question, topic=" ".join(str(data["topic"]).split()) or question, queries=queries[:MAX_SEARCHES] or [question], off_topic=off_topic[:8], wants=str(data["wants"]).strip())


def is_listing(result: dict[str, Any]) -> bool:
    """A page of search results or a "top 10" list, rather than a page about one place or product."""

    url = str(result.get("url") or "")
    parsed = urlparse(url)
    return bool(_LISTING_PATH.search(parsed.path + ("?" + parsed.query if parsed.query else ""))) or bool(_LISTING_TITLE.search(str(result.get("title") or "")))


def judge_result(plan: SearchPlan, result: dict[str, Any]) -> dict[str, Any]:
    """Keep or drop one search result, with the reason."""

    text = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}"
    other = [phrase for phrase in plan.off_topic if _has_phrase(text, phrase)]
    sense = sorted(plan.sense_words & _words(text))
    keep = not other or len(sense) > len(other)
    reason = "" if keep else f"about another meaning ({', '.join(other)})"
    return {"keep": keep, "reason": reason, "other_meaning": other, "sense_words": sense, "listing": is_listing(result)}


def judge_results(plan: SearchPlan, results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, dropped). Kept results are ordered: pages about something particular first, listing pages after."""

    kept, dropped = [], []
    for result in results:
        verdict = judge_result(plan, result)
        (kept if verdict["keep"] else dropped).append({**result, "relevance": verdict})
    kept.sort(key=lambda item: item["relevance"]["listing"])  # stable: search order within each group
    return kept, dropped


def _canonical(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return f"{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/')}"


def gather_planned(plan: SearchPlan, search: Callable[..., list[dict[str, Any]]], *, max_results: int = 5, min_relevant: int = MIN_RELEVANT) -> dict[str, Any]:
    """Search the plan's queries in turn until `min_relevant` relevant results are in hand."""

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    searches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in plan.queries[:MAX_SEARCHES]:
        try:
            found = search(query, max_results=max_results)
        except Exception as exc:  # one failing search must not end the research
            searches.append({"query": query, "returned": 0, "kept": 0, "dropped": 0, "error": str(exc)[:200]})
            continue
        fresh = []
        for result in found:
            key = _canonical(str(result.get("url") or ""))
            if key and key not in seen:
                seen.add(key)
                fresh.append(result)
        good, bad = judge_results(plan, fresh)
        kept.extend(good)
        dropped.extend(bad)
        searches.append({"query": query, "returned": len(found), "kept": len(good), "dropped": len(bad)})
        if sum(not item["relevance"]["listing"] for item in kept) >= min_relevant or len(kept) >= max_results:
            break
    kept.sort(key=lambda item: item["relevance"]["listing"])
    return {"plan": plan.to_dict(), "results": kept[:max_results], "dropped": dropped, "searches": searches}


# ---- names in the answer that the sources do not contain ------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CAPITALISED = re.compile(r"[A-Z][\w'’&.-]*")
_JOINERS = {"of", "the", "and", "&", "de", "la", "le", "von", "van", "on", "at"}
_NOT_NAMES = frozenset(
    "I A An The This That These Those It Its There Their They We You Your Our My However Based According Also Some Many Most "
    "Yes No Not None Note If When While Although Because For In On At By From With Without To As Overall Here Both Each "
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September October November December "
    "Web Results Sources Source".split()
)


def _names_in(sentence: str) -> list[str]:
    words = sentence.split()
    names: list[str] = []
    run: list[str] = []
    for index, raw in enumerate(words):
        token = raw.strip(",;:()[]\"“”'’!?")
        if token.endswith(".") and not re.match(r"^(?:[A-Z]\.)+$", token):
            token = token[:-1]
        capital = bool(_CAPITALISED.fullmatch(token)) and token not in _NOT_NAMES
        if capital and not (index == 0 and len(words) > 1 and not _CAPITALISED.fullmatch(words[1].strip(",;:()[]\"'"))):
            run.append(token)
        elif run and token.lower() in _JOINERS and index + 1 < len(words) and _CAPITALISED.fullmatch(words[index + 1].strip(",;:()[]\"'")):
            run.append(token)
        else:
            if run:
                names.append(" ".join(run))
            run = []
        if raw.rstrip().endswith((",", ";", ":", ")", "!", "?")) and run:
            names.append(" ".join(run))
            run = []
    if run:
        names.append(" ".join(run))
    return [name.strip(" .") for name in names if len(name.strip(" .")) > 1 and not name.isupper() or len(name) > 3]


def unsourced_names(answer: str, sources: str, question: str = "") -> list[str]:
    """Names in the answer that appear neither in the sources nor in the question."""

    known = " ".join(_WORD.findall(f"{sources} {question}".lower()))
    missing: list[str] = []
    for sentence in _SENTENCE.split(str(answer or "")):
        for name in _names_in(sentence.strip()):
            plain = " ".join(_WORD.findall(name.lower()))
            if plain and re.search(r"\b" + re.escape(plain) + r"\b", known) is None and name not in missing:
                missing.append(name)
    return missing


def unsourced_names_note(answer: str, sources: str, question: str = "") -> str:
    missing = unsourced_names(answer, sources, question)
    if not missing:
        return ""
    return "\n\nNot found in the sources above: " + ", ".join(missing) + ". Check these before relying on them."


__all__ = [
    "PLAN_OPTIONS",
    "PLAN_PROMPT",
    "PLAN_SCHEMA",
    "SearchPlan",
    "as_typed",
    "gather_planned",
    "is_listing",
    "judge_result",
    "judge_results",
    "plan_search",
    "unsourced_names",
    "unsourced_names_note",
]
