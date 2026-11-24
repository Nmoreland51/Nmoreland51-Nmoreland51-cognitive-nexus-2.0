"""One list of what this installation can do: tools with their shapes and needs, apps, linked accounts."""

from __future__ import annotations

import pytest

from agent import capabilities
from agent.approvals import ApprovalPolicy
from agent.capabilities import catalogue, register_assistant_tools, summary
from agent.github import register_github_tools
from agent.registry import ToolContext, ToolRegistry
from agent.store import AgentStore
from modules import accounts, image_gen, providers, web_research
from modules.providers import ProviderStatus

CREDENTIAL = "-".join(["catalogue", "credential", "for", "tests"])


@pytest.fixture(autouse=True)
def a_known_machine(monkeypatch):
    """Nothing linked through the environment, a model server with one chat model, no image backend."""

    for described in accounts.SERVICES.values():
        for name in described.variables:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.setenv("SEARCH_SOURCES", "searxng,brave,wikipedia")
    monkeypatch.setattr(providers, "check_ollama_status", lambda base_url=None, timeout=2.5: ProviderStatus(available=True, models=["chat:8b"], message="Ollama is running.", base_url="http://x", embedding_models=["embed"]))
    monkeypatch.setattr(image_gen, "detect_image_providers", lambda: [{"name": "automatic1111", "label": "Automatic1111 API", "available": False, "implemented": True, "message": "Automatic1111 is not reachable."}])


@pytest.fixture
def registry():
    return register_github_tools(register_assistant_tools(ToolRegistry()))


@pytest.fixture
def context(tmp_path):
    store = AgentStore(tmp_path / "agent.db")
    yield ToolContext(store=store, policy=ApprovalPolicy("trusted"))
    store.close()


# ---- the assistant's own tools -----------------------------------------------------------------------


def test_the_assistant_tools_declare_what_they_take_and_what_they_return(registry):
    described = {tool["name"]: tool for tool in registry.describe(adapters=("web", "knowledge"))}

    assert sorted(described) == ["read_page", "search_knowledge", "web_search"]
    assert described["web_search"]["effect"] == "network" and described["search_knowledge"]["effect"] == "read"
    for tool in described.values():
        assert tool["parameters"]["additionalProperties"] is False and tool["returns"]["type"] == "object" and tool["returns"]["required"]
    assert described["web_search"]["needs"] == ["search"] and described["read_page"]["parameters"]["properties"]["url"]["pattern"] == "^https?://"


def test_a_web_search_goes_through_the_registry_and_comes_back_in_the_declared_shape(registry, context, monkeypatch):
    monkeypatch.setattr(web_research, "search_web", lambda query, max_results=5: [{"title": "A", "url": "https://example.org/a", "snippet": "about a", "source": "example.org", "retrieved_at": "now"}, {"title": "no address", "url": ""}])

    result = registry.call("web_search", {"query": "something", "max_results": 3}, context)

    assert result.ok and result.data == {"query": "something", "results": [{"title": "A", "url": "https://example.org/a", "snippet": "about a", "source": "example.org"}]}
    assert "1. A (https://example.org/a)" in result.output and context.store.actions()[0]["tool"] == "web_search"
    assert registry.call("web_search", {"query": "x"}, context).status == "invalid"  # too short for a search
    assert registry.call("web_search", {"query": "fine", "engine": "any"}, context).status == "invalid"  # no such argument


def test_no_search_source_is_a_failure_with_the_reason(registry, context, monkeypatch):
    def nothing(query, max_results=5):
        raise RuntimeError("No search source is available. Set SEARXNG_URL or BRAVE_SEARCH_API_KEY, or install ddgs.")

    monkeypatch.setattr(web_research, "search_web", nothing)
    failed = registry.call("web_search", {"query": "something"}, context)
    assert not failed.ok and failed.status == "failed" and "No search source is available" in failed.error


def test_a_page_is_read_cut_to_size_and_only_over_http(registry, context, monkeypatch):
    monkeypatch.setattr(web_research, "scrape_url", lambda url, timeout=8: {"success": True, "url": url, "canonical_url": url, "title": "Long page", "text": "word " * 1000, "published": "2026-01-02", "retrieved_at": "now"})

    result = registry.call("read_page", {"url": "https://example.org/long", "max_characters": 500}, context)

    assert result.ok and result.data["cut_short"] and len(result.data["text"]) == 500 and result.data["characters"] == 5000 and result.data["published"] == "2026-01-02"
    assert registry.call("read_page", {"url": "file:///C:/Users/me/secrets.txt"}, context).status == "invalid"
    monkeypatch.setattr(web_research, "scrape_url", lambda url, timeout=8: {"success": False, "error": "Only public addresses can be fetched.", "url": url})
    refused = registry.call("read_page", {"url": "http://192.168.1.1/admin"}, context)
    assert not refused.ok and "Only public addresses can be fetched." in refused.error


def test_the_knowledge_base_is_searched_on_this_machine(registry, context):
    class Notes:
        def search(self, query, top_k=5, **_):
            return [{"url": "notes/a.md", "title": "A note", "kind": "file", "text": "The fence was repaired in May.", "confidence": "high", "matched": "both", "updated_at": "2026-05-02", "score": 0.9}]

    context.settings["knowledge_store"] = Notes()
    result = registry.call("search_knowledge", {"query": "fence repair"}, context)

    assert result.ok and result.data["passages"] == [{"source": "notes/a.md", "title": "A note", "kind": "file", "text": "The fence was repaired in May.", "confidence": "high", "matched": "both", "updated_at": "2026-05-02"}]
    assert context.store.actions()[0]["effect"] == "read"


# ---- apps, accounts, and whether a tool can be used now ------------------------------------------------------


def test_apps_are_looked_for_and_reported_found_or_not():
    found = {app["key"]: app for app in capabilities.apps()}

    assert found["git"]["found"] and found["git"]["detail"].startswith("git version")
    assert found["ollama"]["found"] and found["ollama"]["detail"] == "Models: chat:8b, embed (search vectors)"
    assert not found["search:searxng"]["found"] and "set SEARXNG_URL" in found["search:searxng"]["detail"]
    assert found["search:wikipedia"]["found"] and not found["images:automatic1111"]["found"]


def test_one_app_that_cannot_be_looked_for_does_not_hide_the_others(monkeypatch):
    def broken():
        raise ImportError("an optional package is damaged")

    monkeypatch.setattr(image_gen, "detect_image_providers", broken)
    found = capabilities.apps()

    assert any(app["key"] == "git" and app["found"] for app in found)
    assert {"key": "images", "name": "Image backends", "found": False, "detail": "Could not be looked for: ImportError", "used_for": ""} in found
    assert not any(app["key"].startswith("images:") for app in capabilities.apps(look_for_image_backends=False))


def test_a_tool_is_usable_only_when_what_it_needs_is_there(registry):
    listing = catalogue(registry)
    tools = {tool["name"]: tool for tool in listing["tools"]}

    assert tools["search_knowledge"]["usable"] and tools["read_page"]["usable"] and tools["web_search"]["usable"]  # Wikipedia is ready
    assert tools["push_branch"]["usable"]  # needs Git only; a remote that is not GitHub needs no account
    assert not tools["open_pull_request"]["usable"]
    assert tools["open_pull_request"]["missing"] == ["needs a GitHub account allowed for 'pull_request' (COGNITIVE_NEXUS_GITHUB_TOKEN is not set.)"]

    accounts.link("github", CREDENTIAL, permissions=["read"])
    tools = {tool["name"]: tool for tool in catalogue(registry)["tools"]}
    assert tools["ci_status"]["usable"] and not tools["open_pull_request"]["usable"]
    assert "linked, but not allowed for 'pull_request'" in tools["open_pull_request"]["missing"][0]

    accounts.grant("github", "pull_request")
    assert {tool["name"]: tool for tool in catalogue(registry)["tools"]}["open_pull_request"]["usable"]


def test_web_search_is_not_usable_without_any_search_source(registry, monkeypatch):
    monkeypatch.setenv("SEARCH_SOURCES", "searxng,brave")

    tool = next(tool for tool in catalogue(registry)["tools"] if tool["name"] == "web_search")

    assert not tool["usable"] and tool["missing"] == ["No web search source is set up."]


def test_accounts_are_listed_with_the_tools_that_use_them_and_never_a_secret(registry):
    accounts.link("github", CREDENTIAL, permissions=["read", "push"])

    listing = catalogue(registry)
    github = next(entry for entry in listing["accounts"] if entry["service"] == "github")

    assert github["linked"] and github["permissions"] == ["push", "read"]
    assert github["used_by_tools"] == ["ci_status", "latest_release", "open_pull_request", "read_issue"]
    assert next(entry for entry in listing["accounts"] if entry["service"] == "openai")["used_by_tools"] == []
    assert CREDENTIAL not in str(listing)


def test_the_whole_list_prints_in_lines(registry):
    text = summary(catalogue(registry))

    assert "tool     web       web_search          network  ready" in text
    assert "tool     github    open_pull_request   external not usable: needs a GitHub account allowed for 'pull_request'" in text
    assert "app      Git" in text and "account  GitHub                        not linked" in text
