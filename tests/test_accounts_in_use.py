"""The places that use a linked account ask for it per use, and take no for an answer."""

from __future__ import annotations

import pytest
import requests

from modules import accounts, web_research
from modules.provider_router import ProviderRequest, ProviderRouter

KEY = "-".join(["cloud", "credential", "for", "tests"])


@pytest.fixture(autouse=True)
def nothing_linked_through_the_environment(monkeypatch):
    for described in accounts.SERVICES.values():
        for name in described.variables:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def no_network(monkeypatch):
    sent = []

    def refuse(*args, **kwargs):
        sent.append((args, kwargs))
        raise requests.ConnectionError("no request may be sent in this test")

    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(requests.Session, "post", refuse)
    monkeypatch.setattr(requests.Session, "get", refuse)
    return sent


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_a_cloud_provider_is_available_only_while_its_account_allows_chat(provider):
    router = ProviderRouter({"provider_order": [provider]})
    assert not router.detect_provider(provider).available

    accounts.link(provider, KEY, permissions=["chat"])
    router = ProviderRouter({"provider_order": [provider]})
    assert router.detect_provider(provider).available and "is linked" in router.detect_provider(provider).message

    accounts.withdraw(provider, "chat")
    router = ProviderRouter({"provider_order": [provider]})
    found = router.detect_provider(provider)
    assert not found.available and "not allowed for 'chat'" in found.message


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_a_key_in_the_environment_still_works_and_can_be_withheld(provider, monkeypatch):
    monkeypatch.setenv(accounts.SERVICES[provider].variables[0], KEY)
    assert ProviderRouter({"provider_order": [provider]}).detect_provider(provider).available

    accounts.withdraw(provider, "chat")

    found = ProviderRouter({"provider_order": [provider]}).detect_provider(provider)
    assert not found.available and "'chat' is withheld" in found.message


def test_a_provider_whose_account_was_withdrawn_is_not_sent_the_prompt(no_network):
    """Withdrawn between the availability check and the request: the credential is refused, nothing leaves."""

    accounts.link("openai", KEY, permissions=["chat"])
    router = ProviderRouter({"provider_order": ["openai", "fallback"], "allow_cloud_fallback": True})
    assert router.detect_provider("openai").available
    accounts.withdraw("openai", "chat")

    result = router.generate(ProviderRequest(prompt="hello", provider_order=["openai", "fallback"]))

    assert result.provider == "fallback" and not no_network  # the request to OpenAI was never built


def test_brave_search_is_used_only_while_its_account_allows_search(monkeypatch):
    assert "link Brave Search" in web_research._source_setup_hint("brave")
    accounts.link("brave_search", KEY, permissions=["search"])
    assert web_research._source_setup_hint("brave") == ""
    seen = {}

    def fake_get_json(url, *, params, headers=None):
        seen.update(url=url, headers=headers)
        return {"web": {"results": [{"title": "T", "url": "https://example.org/a", "description": "D"}]}}

    monkeypatch.setattr(web_research, "_get_json", fake_get_json)
    assert web_research._search_brave("anything", 3)[0]["url"] == "https://example.org/a"
    assert seen["url"].startswith("https://api.search.brave.com/") and seen["headers"] == {"X-Subscription-Token": KEY}

    accounts.withdraw("brave_search", "search")
    assert "link Brave Search" in web_research._source_setup_hint("brave")
    with pytest.raises(accounts.NotPermitted):
        web_research._search_brave("anything", 3)
