"""Settings, Linked accounts, driven through the real interface against the real accounts file."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from modules import accounts
from ui import accounts_panel

SECRET = "-".join(["panel", "credential", "for", "tests"])


@pytest.fixture(autouse=True)
def nothing_linked_through_the_environment(monkeypatch):
    for described in accounts.SERVICES.values():
        for name in described.variables:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("CN_TEST_ACCOUNTS_READ_ONLY", raising=False)


def _panel_app():
    import os

    from ui.accounts_panel import render_accounts_panel

    render_accounts_panel(read_only=os.environ.get("CN_TEST_ACCOUNTS_READ_ONLY") == "1")


def everything_shown(app) -> str:
    parts = [item.value for kind in ("markdown", "caption", "success", "warning", "error", "info") for item in getattr(app, kind)]
    parts += [str(item.label) for item in app.expander] + [str(item.label) for item in app.checkbox] + [str(item.value) for item in app.text_input]
    return "\n".join(str(part) for part in parts)


def test_an_account_is_linked_narrowed_and_unlinked_through_the_panel():
    app = AppTest.from_function(_panel_app, default_timeout=60).run()
    assert not app.exception and "GitHub: not linked" in everything_shown(app)

    app.text_input(key="account_secret_github").input(SECRET)
    app.checkbox(key="account_new_github_may_read").check()
    app.checkbox(key="account_new_github_may_push").check()
    next(button for button in app.button if button.label == "Link GitHub").click().run()

    assert not app.exception
    assert accounts.describe("github")["permissions"] == ["push", "read"] and accounts.credential("github", "push") == SECRET
    shown = everything_shown(app)
    assert "GitHub is linked and may be used for: push, read." in shown and "GitHub: linked, may be used for push, read" in shown
    assert SECRET not in shown  # typed once, stored, never shown again

    app.checkbox(key="account_github_may_push").uncheck().run()
    app.button(key="account_save_github").click().run()

    assert not app.exception and accounts.describe("github")["permissions"] == ["read"]
    with pytest.raises(accounts.NotPermitted):
        accounts.credential("github", "push")

    app.button(key="account_unlink_github").click().run()

    assert not app.exception and not accounts.describe("github")["linked"]
    shown = everything_shown(app)
    assert "GitHub is unlinked and the credential is deleted from this machine." in shown and "still valid at GitHub until you cancel it there" in shown


def test_linking_without_ticking_anything_allows_nothing():
    app = AppTest.from_function(_panel_app, default_timeout=60).run()
    app.text_input(key="account_secret_openai").input(SECRET)
    next(button for button in app.button if button.label == "Link OpenAI").click().run()

    assert not app.exception and accounts.describe("openai")["linked"]
    assert "may be used for: nothing yet" in everything_shown(app)
    assert accounts.available("openai", "chat") == (False, "OpenAI is linked, but not allowed for 'chat'.")


def test_an_empty_credential_and_an_unreadable_date_are_refused_in_words():
    app = AppTest.from_function(_panel_app, default_timeout=60).run()
    next(button for button in app.button if button.label == "Link GitHub").click().run()
    assert "The credential is empty." in everything_shown(app)

    app.text_input(key="account_secret_github").input(SECRET)
    app.text_input(key="account_expires_github").input("next spring")
    next(button for button in app.button if button.label == "Link GitHub").click().run()

    assert "The date could not be read. Use YYYY-MM-DD." in everything_shown(app) and not accounts.describe("github")["linked"]


def test_an_account_from_the_environment_can_be_narrowed_but_not_deleted(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", SECRET)
    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    shown = everything_shown(app)
    assert "Brave Search: linked, may be used for search" in shown and "remove the environment variable" in shown and SECRET not in shown
    assert not [button for button in app.button if button.key == "account_unlink_brave_search"]

    app.checkbox(key="account_brave_search_may_search").uncheck().run()
    app.button(key="account_save_brave_search").click().run()

    assert accounts.available("brave_search", "search") == (False, "Brave Search is linked through BRAVE_SEARCH_API_KEY, but 'search' is withheld.")


def test_a_credential_that_has_run_out_is_pointed_out():
    accounts.link("github", SECRET, permissions=["push"], expires_in=-3600)

    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    assert "GitHub: linked, may be used for push (needs attention)" in everything_shown(app)
    assert "The credential has run out." in [item.value for item in app.warning]


def test_in_demo_safe_mode_nothing_can_be_changed(monkeypatch):
    accounts.link("github", SECRET, permissions=["push"])
    monkeypatch.setenv("CN_TEST_ACCOUNTS_READ_ONLY", "1")

    app = AppTest.from_function(_panel_app, default_timeout=60).run()

    assert not app.exception and not list(app.button) and not list(app.text_input)
    assert all(box.disabled for box in app.checkbox) and SECRET not in everything_shown(app)


def test_the_state_line_names_what_an_account_may_be_used_for():
    assert accounts_panel.state_line({"linked": False, "name": "X"}) == "X: not linked"
    assert accounts_panel.state_line({"linked": True, "name": "X", "permissions": [], "problem": ""}) == "X: linked, may be used for nothing"
