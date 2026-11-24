"""Everything this installation can do, as data: tools, apps and linked accounts.

The coding agent's tools were already in a registry (agent/registry.py). This adds what was not:

    tool      something that can be called: a schema for what it takes, a schema for what it
              returns, a declared effect, and what it needs (an app, an account with a permission).
              Every call goes through ToolRegistry.call: approval, history, checked result.
    app       a program on this machine or network that tools rely on (Ollama, Git, an image
              backend, a search source). Found or not found, looked for when asked.
    account   an outside service that needs a credential of the owner's (modules/accounts.py):
              linked or not, how, and which uses the owner allowed.

`catalogue()` puts the three together and answers, for every tool, "can this be used here, now,
and if not, what is missing". Nothing in this module grants anything: an entry describes, the
approval policy (agent/approvals.py) decides, and an account's permissions (modules/accounts.py)
decide whether its credential is handed over.

The assistant's own tools registered here (web_search, read_page, search_knowledge) are the same
functions the chat and research tabs use, made callable one at a time with declared shapes.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any
from urllib.parse import urljoin

from agent.registry import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from modules import accounts

_TEXT = {"type": "string"}
MAX_LINKS = 20  # links of a page that are passed on, so that they can be followed


def _object(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


# ---- the assistant's own tools ---------------------------------------------------------------------------

SEARCH_RESULT = _object({"title": _TEXT, "url": _TEXT, "snippet": _TEXT, "source": _TEXT}, ("title", "url", "snippet"))
WEB_SEARCH_RETURNS = _object({"query": _TEXT, "results": {"type": "array", "items": SEARCH_RESULT}}, ("query", "results"))
READ_PAGE_RETURNS = _object(
    {
        "url": _TEXT,
        "title": _TEXT,
        "text": _TEXT,
        "published": _TEXT,
        "retrieved_at": _TEXT,
        "characters": {"type": "integer", "minimum": 0},
        "cut_short": {"type": "boolean"},
        "links": {"type": "array", "maxItems": MAX_LINKS, "items": _object({"text": _TEXT, "url": {"type": "string", "pattern": "^https?://"}}, ("text", "url"))},
    },
    ("url", "title", "text", "characters", "cut_short", "links"),
)
PASSAGE = _object(
    {"source": _TEXT, "title": _TEXT, "kind": _TEXT, "text": _TEXT, "confidence": _TEXT, "matched": _TEXT, "updated_at": _TEXT},
    ("source", "title", "text", "confidence"),
)
SEARCH_KNOWLEDGE_RETURNS = _object({"query": _TEXT, "passages": {"type": "array", "items": PASSAGE}}, ("query", "passages"))


def web_search(context: ToolContext, query: str, max_results: int = 5) -> ToolResult:
    from modules import web_research

    try:
        found = web_research.search_web(query, max_results=int(max_results))
    except RuntimeError as exc:  # no search source is set up, or every one of them failed
        raise ToolError(str(exc)) from exc
    results = [{"title": str(item.get("title", "")), "url": str(item.get("url", "")), "snippet": str(item.get("snippet", "")), "source": str(item.get("source", ""))} for item in found if item.get("url")]
    lines = [f"{number}. {item['title']} ({item['url']})\n   {item['snippet']}" for number, item in enumerate(results, 1)]
    return ToolResult(ok=True, output="\n".join(lines) or "The search returned nothing.", data={"query": query, "results": results})


def read_page(context: ToolContext, url: str, max_characters: int = 6000) -> ToolResult:
    from modules import web_research

    page = web_research.scrape_url(url)
    if not page.get("success"):
        raise ToolError(f"The page could not be read: {page.get('error') or 'no readable text was found'}")
    text = str(page.get("text") or "")
    cut = len(text) > int(max_characters)
    shown = text[: int(max_characters)]
    address = str(page.get("canonical_url") or page.get("url") or url)
    links: list[dict[str, str]] = []
    for link in page.get("links") or []:
        target = urljoin(address, str(link.get("href") or "")).split("#")[0]
        if target.startswith(("http://", "https://")) and target != address and target not in {item["url"] for item in links}:
            links.append({"text": str(link.get("text") or "")[:120], "url": target})
        if len(links) >= MAX_LINKS:
            break
    data = {
        "url": address,
        "title": str(page.get("title") or ""),
        "text": shown,
        "published": str(page.get("published") or ""),
        "retrieved_at": str(page.get("retrieved_at") or ""),
        "characters": len(text),
        "cut_short": cut,
        "links": links,
    }
    listed = "\n\nLinks on the page:\n" + "\n".join(f"- {link['text']}: {link['url']}" for link in links) if links else ""
    return ToolResult(ok=True, output=f"{data['title']}\n{data['url']}\n\n{shown}" + ("\n[...]" if cut else "") + listed, data=data)


def search_knowledge(context: ToolContext, query: str, limit: int = 5) -> ToolResult:
    from modules.knowledge_store import KnowledgeStore

    store = context.settings.get("knowledge_store") or KnowledgeStore()
    found = store.search(query, top_k=int(limit))
    passages = [
        {
            "source": str(item.get("url") or ""),
            "title": str(item.get("title") or ""),
            "kind": str(item.get("kind") or ""),
            "text": str(item.get("text") or ""),
            "confidence": str(item.get("confidence") or ""),
            "matched": str(item.get("matched") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        }
        for item in found
    ]
    lines = [f"{number}. {item['title'] or item['source']} [{item['confidence']}]\n   {item['text'][:400]}" for number, item in enumerate(passages, 1)]
    return ToolResult(ok=True, output="\n".join(lines) or "Nothing in the knowledge base matches.", data={"query": query, "passages": passages})


def register_assistant_tools(registry: ToolRegistry) -> ToolRegistry:
    """Add web search, page reading and knowledge search to a registry."""

    registry.register(
        Tool(
            "web_search",
            "Search the web. Use it for things that change or are recent: news, prices, results, current versions. Returns titles, addresses and short excerpts; it does not open the pages.",
            _object({"query": {"type": "string", "minLength": 2, "maxLength": 300}, "max_results": {"type": "integer", "minimum": 1, "maximum": 10}}, ("query",)),
            "network",
            web_search,
            adapter="web",
            repeatable=True,
            returns=WEB_SEARCH_RETURNS,
            needs=("search",),
            summarize=lambda arguments: f"search the web for {arguments.get('query', '')!r}",
        )
    )
    registry.register(
        Tool(
            "read_page",
            "Fetch one public web page and return its readable text. Use it only when the request gives the address of a page, or a search returned it. Addresses on this machine or a private network are refused.",
            _object({"url": {"type": "string", "pattern": "^https?://", "maxLength": 2000}, "max_characters": {"type": "integer", "minimum": 500, "maximum": 20000}}, ("url",)),
            "network",
            read_page,
            adapter="web",
            repeatable=True,
            returns=READ_PAGE_RETURNS,
            summarize=lambda arguments: f"read the page {arguments.get('url', '')}",
        )
    )
    registry.register(
        Tool(
            "search_knowledge",
            "Search the documents, notes and saved research the owner added to the knowledge base on this machine. Use it only when the request is about the owner's own notes, files or documents.",
            _object({"query": {"type": "string", "minLength": 2, "maxLength": 300}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ("query",)),
            "read",
            search_knowledge,
            adapter="knowledge",
            repeatable=True,
            returns=SEARCH_KNOWLEDGE_RETURNS,
        )
    )
    return registry


# ---- apps ---------------------------------------------------------------------------------------------------


def _git() -> dict[str, Any]:
    program = shutil.which("git")
    version = ""
    if program:
        try:
            version = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
    return {"key": "git", "name": "Git", "found": bool(program and version), "detail": version or "Git was not found on this machine.", "used_for": "The coding agent's checkouts, branches, commits and pushes."}


def _ollama(settings: dict[str, Any]) -> dict[str, Any]:
    from modules.providers import check_ollama_status, get_ollama_base_url

    status = check_ollama_status(base_url=str(settings.get("ollama_url") or get_ollama_base_url()), timeout=1.5)
    models = list(status.models) + [f"{name} (search vectors)" for name in getattr(status, "embedding_models", [])]
    return {
        "key": "ollama",
        "name": "Ollama",
        "found": bool(status.available),
        "detail": (f"Models: {', '.join(models)}" if models else status.message) if status.available else status.message,
        "used_for": "Local models: chat, the coding agent, and search vectors for the knowledge base.",
    }


def _search_sources() -> list[dict[str, Any]]:
    from modules import web_research

    return [
        {
            "key": f"search:{source['name']}",
            "name": source["label"],
            "found": bool(source["available"]),
            "detail": "Ready." if source["available"] else f"Not set up: {source['setup']}.",
            "used_for": "Web search.",
        }
        for source in web_research.search_sources_status()
    ]


def _image_backends() -> list[dict[str, Any]]:
    from modules import image_gen

    found = []
    for provider in image_gen.detect_image_providers():
        found.append(
            {
                "key": f"images:{provider.get('name')}",
                "name": str(provider.get("label") or provider.get("name") or "Image backend"),
                "found": bool(provider.get("available")) and bool(provider.get("implemented", True)),
                "detail": str(provider.get("message") or ""),
                "used_for": "Making pictures.",
            }
        )
    return found


def apps(settings: dict[str, Any] | None = None, *, look_for_image_backends: bool = True) -> list[dict[str, Any]]:
    """The programs tools rely on, each looked for now. Never raises: an app that cannot be asked is reported as not found."""

    settings = settings or {}
    looks: list[tuple[str, str, Any]] = [("git", "Git", _git), ("ollama", "Ollama", lambda: _ollama(settings)), ("search", "Web search sources", _search_sources)]
    if look_for_image_backends:
        looks.append(("images", "Image backends", _image_backends))
    found: list[dict[str, Any]] = []
    for key, name, look in looks:
        try:
            result = look()
        except Exception as exc:  # a broken optional package must not hide everything else
            result = {"key": key, "name": name, "found": False, "detail": f"Could not be looked for: {type(exc).__name__}", "used_for": ""}
        found.extend(result if isinstance(result, list) else [result])
    return found


# ---- everything together ----------------------------------------------------------------------------------------


def _need(need: str, found_apps: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    """(met?, what is missing) for one requirement of a tool."""

    kind, _, rest = need.partition(":")
    if kind == "account":
        service, _, permission = rest.partition(":")
        usable, why = accounts.available(service, permission)
        return usable, "" if usable else f"needs a {accounts.service_for(service).name} account allowed for '{permission}' ({why})"
    if kind == "app":
        app = found_apps.get(rest)
        return (True, "") if app and app["found"] else (False, (app or {}).get("detail") or f"{rest} was not found.")
    if kind == "search":
        ready = [app for key, app in found_apps.items() if key.startswith("search:") and app["found"]]
        return (True, "") if ready else (False, "No web search source is set up.")
    return False, f"Unknown requirement {need!r}."


def catalogue(registry: ToolRegistry, settings: dict[str, Any] | None = None, *, look_for_image_backends: bool = True) -> dict[str, list[dict[str, Any]]]:
    """Every tool, app and account, with whether each tool can be used here and now."""

    found = apps(settings, look_for_image_backends=look_for_image_backends)
    by_key = {app["key"]: app for app in found}
    tools = []
    for tool in registry.describe():
        missing = []
        for need in tool.get("needs") or ():
            met, why = _need(need, by_key)
            if not met:
                missing.append(why)
        tools.append({**tool, "usable": not missing, "missing": missing})
    linked = accounts.accounts()
    used_by: dict[str, list[str]] = {}
    for tool in tools:
        for need in tool.get("needs") or ():
            if need.startswith("account:"):
                used_by.setdefault(need.split(":")[1], []).append(tool["name"])
    for entry in linked:
        entry["used_by_tools"] = sorted(used_by.get(entry["service"], []))
    return {"tools": tools, "apps": found, "accounts": linked}


def summary(listing: dict[str, list[dict[str, Any]]]) -> str:
    """The catalogue in a few lines, for a terminal."""

    lines = []
    for tool in listing["tools"]:
        state = "ready" if tool["usable"] else "not usable: " + "; ".join(tool["missing"])
        lines.append(f"tool     {tool['adapter']:<9} {tool['name']:<19} {tool['effect']:<8} {state}")
    for app in listing["apps"]:
        lines.append(f"app      {app['name']:<29} {'found' if app['found'] else 'not found':<9} {app['detail'][:90]}")
    for entry in listing["accounts"]:
        state = f"linked, may be used for: {', '.join(entry['permissions']) or 'nothing'}" if entry["linked"] else "not linked"
        lines.append(f"account  {entry['name']:<29} {state}")
    return "\n".join(lines)


__all__ = ["apps", "catalogue", "read_page", "register_assistant_tools", "search_knowledge", "summary", "web_search"]
