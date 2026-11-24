"""The Settings and Agent tabs.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

from typing import Any
import streamlit as st

from modules.chat_profile import (
    ChatProfile,
    HUMOR_LEVEL_OPTIONS,
    HUMOR_STYLE_OPTIONS,
    save_chat_profile,
)
from ui.agent_panel import render_agent_panel
from ui.accounts_panel import render_accounts_panel
from ui.behavior_panel import render_behavior_panel
from nexus_router import (
    get_prompt_template_examples,
)
from ui.shared import clear_runtime_caches, get_nexus_core, is_demo_safe


def render_settings_tab(settings: dict[str, Any]) -> None:
    profile = settings["chat_profile"]
    render_behavior_panel(
        get_nexus_core(),
        profile,
        settings,
        after_save=clear_runtime_caches,
        read_only=is_demo_safe(settings),
    )
    st.divider()
    render_accounts_panel(read_only=is_demo_safe(settings))
    st.divider()
    st.subheader("Persona")
    st.caption("Name, voice and style. Like the behaviour text above, this is sent to the model as your instructions.")
    with st.form("chat_profile_form"):
        enabled = st.checkbox("Enable persona", value=profile.enabled)
        user_name = st.text_input("User name", value=profile.user_name)
        assistant_name = st.text_input("Assistant name", value=profile.assistant_name)
        persona_summary = st.text_area("Persona summary", value=profile.persona_summary, height=100)
        tone_notes = st.text_area("Tone notes", value=profile.tone_notes, height=80)
        style_notes = st.text_area("Style notes", value=profile.style_notes, height=120)
        humor_level = st.select_slider(
            "Humor",
            options=list(HUMOR_LEVEL_OPTIONS),
            value=getattr(profile, "humor_level", "light"),
        )
        humor_styles = list(HUMOR_STYLE_OPTIONS)
        current_humor_style = getattr(profile, "humor_style", "warm_wit")
        if current_humor_style not in humor_styles:
            current_humor_style = "warm_wit"
        humor_style = st.selectbox(
            "Humor style",
            humor_styles,
            index=humor_styles.index(current_humor_style),
            format_func=lambda key: HUMOR_STYLE_OPTIONS.get(key, key),
        )
        humor_notes = st.text_area("Humor notes", value=getattr(profile, "humor_notes", ChatProfile.humor_notes), height=80)
        additional_instructions = st.text_area("Additional instructions", value=profile.additional_instructions, height=100)
        show_capability_greeting = st.checkbox("Show greeting on fresh chat", value=getattr(profile, 'show_capability_greeting', True))

        saved = st.form_submit_button("Save Persona")
        if saved:
            updated = ChatProfile(
                enabled=enabled,
                user_name=user_name,
                assistant_name=assistant_name,
                persona_summary=persona_summary,
                tone_notes=tone_notes,
                style_notes=style_notes,
                humor_level=humor_level,
                humor_style=humor_style,
                humor_notes=humor_notes,
                # Stored by older versions and used by nothing; carried over so a saved profile is not changed.
                creative_min_words=int(getattr(profile, "creative_min_words", 500)),
                direct_language_for_adult_fiction=bool(getattr(profile, "direct_language_for_adult_fiction", True)),
                show_capability_greeting=show_capability_greeting,
                additional_instructions=additional_instructions,
                allow_extreme_adult_content=getattr(profile, "allow_extreme_adult_content", True),
                allow_illegal_topics=getattr(profile, "allow_illegal_topics", True),
            )
            save_chat_profile(updated)
            st.success("Persona saved.")
            st.rerun()

    with st.expander("Developer diagnostics: router prompt templates", expanded=False):
        st.json(get_prompt_template_examples())


def render_agent_tab(settings: dict[str, Any]) -> None:
    """The coding agent: tasks, what waits for the owner, and everything it did."""

    from agent.cli import build_agent
    from agent.handlers import default_handlers
    from agent.jobs import Worker
    from agent.store import AgentStore

    store = AgentStore()
    model = str(settings.get("selected_model") or "")

    def build():
        return build_agent(store, model)

    render_agent_panel(
        store,
        build,
        read_only=is_demo_safe(settings),
        make_worker=lambda queue: Worker(queue, default_handlers(queue, build), capacity=1),
    )
