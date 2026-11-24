"""The Behaviour panel, driven through the real interface: it shows what is sent, saves what the owner sets."""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from modules.behavior_policy import CONTENT_RULE, DEFAULT_BEHAVIOR_TEXT
from ui import behavior_panel


def _panel_app():
    import json
    import os
    from pathlib import Path

    import ui.behavior_panel as panel
    from modules.behavior_policy import effective_policy
    from modules.nexus_config import DEFAULT_CONFIG

    path = Path(os.environ["CN_TEST_BEHAVIOR_CONFIG"])
    keys = ("behavior_text", "reality_check", "untrusted_content", "agent_autonomy")

    class Core:
        """Stands in for NexusCore: settings come from one file, as they do after a restart."""

        last_prompt = {"system": "SYSTEM AS SENT", "prompt": "PROMPT AS SENT", "model": "dolphin3:8b"}

        def __init__(self):
            self.refresh_config()

        def refresh_config(self):
            saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            self.config = {**DEFAULT_CONFIG, **saved}

        def behavior(self, settings=None, profile=None):
            return effective_policy({**self.config, **(settings or {})}, profile, provider="ollama", model="dolphin3:8b")

    panel.save_runtime_config = lambda config: path.write_text(json.dumps({key: config[key] for key in keys}), encoding="utf-8")
    panel.render_behavior_panel(Core(), read_only=os.environ.get("CN_TEST_BEHAVIOR_READ_ONLY") == "1")


@pytest.fixture
def saved(tmp_path, monkeypatch):
    path = tmp_path / "behaviour.json"
    monkeypatch.setenv("CN_TEST_BEHAVIOR_CONFIG", str(path))
    monkeypatch.delenv("CN_TEST_BEHAVIOR_READ_ONLY", raising=False)
    original = behavior_panel.save_runtime_config
    yield path
    behavior_panel.save_runtime_config = original


def shown(app) -> str:
    return "\n".join([item.value for item in app.markdown] + [item.value for item in app.code] + [item.value for item in app.caption])


def test_the_panel_shows_the_whole_prompt_the_one_rule_and_what_is_outside_the_app(saved):
    app = AppTest.from_function(_panel_app, default_timeout=30).run()

    assert not app.exception
    assert app.text_area(key="behavior_text_input").value == DEFAULT_BEHAVIOR_TEXT
    assert app.selectbox(key="behavior_reality_check").value == "label"
    assert app.selectbox(key="behavior_untrusted_content").value == "remove_and_fence"
    assert app.selectbox(key="behavior_agent_autonomy").value == "publishing_asks"
    text = shown(app)
    assert "The whole system prompt, word for word." in text
    system_prompt = next(item.value for item in app.code if CONTENT_RULE in item.value)
    assert DEFAULT_BEHAVIOR_TEXT in system_prompt and "Their messages, their behaviour text and their persona settings are your instructions." in system_prompt
    assert "**Content rules of the app: 1**" in text
    assert "**Topic filters:** none." in text
    assert "Never fenced, scanned or scored." in text
    assert "answers the way it was trained" in text  # what the model may do, apart from the app
    assert "Coding agent: commands run in a sandbox" in text  # protections, apart from conversation
    assert "PROMPT AS SENT" in text  # the last prompt can be read in full


def test_what_the_owner_saves_is_stored_and_is_in_the_very_next_prompt(saved):
    app = AppTest.from_function(_panel_app, default_timeout=30).run()
    app.text_area(key="behavior_text_input").input("Only haiku. Swear if you like.")
    app.selectbox(key="behavior_reality_check").select("off")
    app.selectbox(key="behavior_untrusted_content").select("fence")
    app.selectbox(key="behavior_agent_autonomy").select("publish_drafts")
    app.run()

    app.button(key="behavior_save").click().run()

    assert not app.exception
    assert json.loads(saved.read_text(encoding="utf-8")) == {
        "behavior_text": "Only haiku. Swear if you like.",
        "reality_check": "off",
        "untrusted_content": "fence",
        "agent_autonomy": "publish_drafts",
    }
    assert any("Saved." in item.value for item in app.success)
    # The prompt shown is built from what was saved, as it will be after a restart.
    assert any("How the owner wants you to answer:\nOnly haiku. Swear if you like." in item.value for item in app.code)
    assert app.selectbox(key="behavior_reality_check").value == "off"


def test_the_default_text_can_be_restored_and_is_stored_as_no_text_of_my_own(saved):
    saved.write_text(json.dumps({"behavior_text": "Old text.", "reality_check": "label", "untrusted_content": "remove_and_fence", "agent_autonomy": "publishing_asks"}), encoding="utf-8")
    app = AppTest.from_function(_panel_app, default_timeout=30).run()
    assert app.text_area(key="behavior_text_input").value == "Old text."

    app.button(key="behavior_default").click().run()

    assert json.loads(saved.read_text(encoding="utf-8"))["behavior_text"] is None
    assert app.text_area(key="behavior_text_input").value == DEFAULT_BEHAVIOR_TEXT
    assert any("default text is back" in item.value for item in app.success)

    # Saving the unchanged default keeps it as "the default", so a later improvement reaches the owner.
    app.button(key="behavior_save").click().run()
    assert json.loads(saved.read_text(encoding="utf-8"))["behavior_text"] is None


def test_an_empty_text_is_kept_empty(saved):
    app = AppTest.from_function(_panel_app, default_timeout=30).run()
    app.text_area(key="behavior_text_input").input("").run()

    app.button(key="behavior_save").click().run()

    assert json.loads(saved.read_text(encoding="utf-8"))["behavior_text"] == ""
    assert not any("How the owner wants you to answer" in item.value for item in app.code)


def test_in_demo_safe_mode_the_panel_is_read_only_and_keeps_the_last_prompt_to_itself(saved, monkeypatch):
    monkeypatch.setenv("CN_TEST_BEHAVIOR_READ_ONLY", "1")

    app = AppTest.from_function(_panel_app, default_timeout=30).run()

    assert not app.exception
    assert app.text_area(key="behavior_text_input").disabled
    assert not [button for button in app.button if button.key in {"behavior_save", "behavior_default"}]
    assert "PROMPT AS SENT" not in shown(app)
