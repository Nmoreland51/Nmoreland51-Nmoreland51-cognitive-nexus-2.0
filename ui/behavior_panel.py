"""The Behaviour panel: the owner's settings for how the assistant answers, and a plain view of
everything else that shapes an answer.

Three things are shown apart, because they are different things: what the owner set, what the
app adds on its own (in full, word for word), and what the selected model or its provider may do
that the app cannot change. Permissions for the coding agent and the protections that keep the
machine and the data safe are listed separately from all of that: they are not rules about what
may be said.
"""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from modules.behavior_policy import (
    AGENT_AUTONOMY_HELP,
    AGENT_AUTONOMY_MODES,
    DEFAULT_BEHAVIOR_TEXT,
    REALITY_CHECK_HELP,
    REALITY_CHECK_MODES,
    UNTRUSTED_CONTENT_HELP,
    UNTRUSTED_CONTENT_MODES,
    apply_behavior_changes,
    policy_from,
)
from modules.nexus_config import save_runtime_config

TEXT_KEY = "behavior_text_input"
REALITY_KEY = "behavior_reality_check"
OUTSIDE_KEY = "behavior_untrusted_content"
AGENT_KEY = "behavior_agent_autonomy"
NOTICE_KEY = "behavior_notice"

REALITY_LABELS = {"label": "Answer in full, label what is not real", "withhold": "Hold back detail on impossible things", "off": "Off"}
OUTSIDE_LABELS = {
    "remove_and_fence": "Remove lines aimed at an AI, and mark the rest as material",
    "fence": "Mark as material only",
    "off": "No handling",
}
AGENT_LABELS = {
    "publishing_asks": "Works on its own; asks before publishing",
    "publish_drafts": "Works on its own and publishes drafts",
    "ask_first": "Asks before every change",
    "read_only": "May only read",
}


def _store(core: Any, changes: dict[str, Any], after_save: Callable[[], None] | None, notice: str) -> None:
    save_runtime_config(apply_behavior_changes(dict(core.config), changes))
    core.refresh_config()
    if after_save is not None:
        after_save()
    st.session_state[NOTICE_KEY] = notice


def _save_clicked(core: Any, after_save: Callable[[], None] | None) -> None:
    text = str(st.session_state.get(TEXT_KEY, "")).strip()
    _store(
        core,
        {
            # The default is stored as "no text of my own", so an improved default reaches the owner later.
            "behavior_text": None if text == DEFAULT_BEHAVIOR_TEXT else text,
            "reality_check": st.session_state.get(REALITY_KEY),
            "untrusted_content": st.session_state.get(OUTSIDE_KEY),
            "agent_autonomy": st.session_state.get(AGENT_KEY),
        },
        after_save,
        "Saved. It applies from your next message, here and on the phone.",
    )


def _default_clicked(core: Any, after_save: Callable[[], None] | None) -> None:
    st.session_state[TEXT_KEY] = DEFAULT_BEHAVIOR_TEXT
    _store(core, {"behavior_text": None}, after_save, "The default text is back.")


def render_behavior_panel(
    core: Any,
    profile: Any | None = None,
    settings: dict[str, Any] | None = None,
    *,
    after_save: Callable[[], None] | None = None,
    read_only: bool = False,
) -> None:
    """Draw the panel. `core` is the NexusCore; `after_save` clears the app's caches."""

    policy = policy_from(core.config)
    effective = core.behavior(settings, profile)
    application = effective["application"]

    st.subheader("Behaviour")
    st.caption(
        "How the assistant answers is yours to set. These settings are saved, survive a restart, apply to the phone "
        "as well, and are never switched off by Auto Precision."
    )
    notice = st.session_state.pop(NOTICE_KEY, "")
    if notice:
        st.success(notice)

    st.text_area(
        "How the assistant should answer",
        value=policy.behavior_text,
        height=150,
        key=TEXT_KEY,
        disabled=read_only,
        help="Sent to the model with every message, as your instructions. Clear it to say nothing about tone or topics.",
    )
    reality = st.selectbox(
        "Reality check",
        list(REALITY_CHECK_MODES),
        index=REALITY_CHECK_MODES.index(policy.reality_check),
        format_func=lambda value: REALITY_LABELS[value],
        key=REALITY_KEY,
        disabled=read_only,
    )
    st.caption(REALITY_CHECK_HELP[reality])
    outside = st.selectbox(
        "Text from web pages and files",
        list(UNTRUSTED_CONTENT_MODES),
        index=UNTRUSTED_CONTENT_MODES.index(policy.untrusted_content),
        format_func=lambda value: OUTSIDE_LABELS[value],
        key=OUTSIDE_KEY,
        disabled=read_only,
    )
    st.caption(UNTRUSTED_CONTENT_HELP[outside] + " Your own messages are never handled this way.")
    autonomy = st.selectbox(
        "Coding agent",
        list(AGENT_AUTONOMY_MODES),
        index=AGENT_AUTONOMY_MODES.index(policy.agent_autonomy),
        format_func=lambda value: AGENT_LABELS[value],
        key=AGENT_KEY,
        disabled=read_only,
    )
    st.caption(AGENT_AUTONOMY_HELP[autonomy])

    if not read_only:
        columns = st.columns(2)
        columns[0].button("Save behaviour", type="primary", key="behavior_save", on_click=_save_clicked, args=(core, after_save))
        columns[1].button("Use the default text", key="behavior_default", on_click=_default_clicked, args=(core, after_save))

    with st.expander("Everything the app adds to your prompt", expanded=False):
        st.markdown("The whole system prompt, word for word. There is no other, hidden one.")
        st.code(application["system_prompt"], language=None)
        st.markdown(f"**Content rules of the app: {len(application['content_rules'])}**")
        for rule in application["content_rules"]:
            st.write(rule)
        st.caption(application["content_rule_check"])
        st.markdown("**Topic filters:** none. The app does not sort messages by subject or refuse by keyword.")
        st.markdown(f"**Your own messages:** {application['owner_messages']}")
        st.markdown("**Texts the app can show instead of an answer:**")
        for text in application["refusal_templates"]:
            st.write(f"- {text}")
        st.markdown("**Added to each message, besides the system prompt:**")
        for text in application["per_turn_additions"]:
            st.write(f"- {text}")

    last_prompt = getattr(core, "last_prompt", None) or {}
    if last_prompt.get("prompt") and not read_only:
        with st.expander("The last chat prompt, exactly as it was sent", expanded=False):
            st.caption(f"Model: {last_prompt.get('model') or 'not recorded'}. First the system prompt, then the message with everything the app put around it.")
            st.code(last_prompt.get("system", ""), language=None)
            st.code(last_prompt["prompt"], language=None)

    with st.expander("What the model or its provider may do", expanded=False):
        provider = effective["provider"]
        st.write(f"The selected model runs {provider['runs']}.")
        st.write(provider["limits"])
        st.caption(f"Decided by: {provider['controlled_by']}. When an answer reads like a refusal, the line under it says it came from the model.")

    protections = effective.get("protections") or []
    if protections:
        with st.expander("Permissions and protections (not rules about what may be said)", expanded=False):
            st.caption("These keep the machine, the data and your accounts safe while tools act for you. Each says whether you can change it.")
            for item in protections:
                st.markdown(f"**{item['name']}** ({item['can_change']})")
                st.write(f"{item['what']} Why: {item['why']}")
