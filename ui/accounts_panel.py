"""Settings, Linked accounts: which outside services the assistant holds a credential for, and what for.

Everything here is modules/accounts.py shown as it is. A credential is typed into a password
field, stored, and never shown again: no part of this panel can display one.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from modules import accounts

NOTICE_KEY = "accounts_notice"


def _notice(text: str) -> None:
    st.session_state[NOTICE_KEY] = text


def state_line(entry: dict[str, Any]) -> str:
    """One line saying where an account stands."""

    if not entry["linked"]:
        return f"{entry['name']}: not linked"
    allowed = ", ".join(entry["permissions"]) if entry["permissions"] else "nothing"
    trouble = " (needs attention)" if entry["problem"] else ""
    return f"{entry['name']}: linked, may be used for {allowed}{trouble}"


def _linked(entry: dict[str, Any], read_only: bool) -> None:
    service = entry["service"]
    st.write(f"Linked through: {entry['how']}.")
    st.caption(entry["kept"])
    if entry["expires_at"]:
        st.write(f"Runs out: {entry['expires_at'][:16].replace('T', ' ')} UTC" + (" (renewed automatically before then)" if entry["renews_itself"] else " (it cannot be renewed from here: link again when it does)"))
    if entry["last_used"]:
        st.caption(f"Last used: {entry['last_used'][:16].replace('T', ' ')} UTC")
    if entry["problem"]:
        st.warning(entry["problem"])
    st.markdown("**What the assistant may use it for**")
    chosen = [
        name
        for name, meaning in entry["known_permissions"].items()
        if st.checkbox(f"{name}: {meaning}" if meaning else name, value=name in entry["permissions"], key=f"account_{service}_may_{name}", disabled=read_only)
    ]
    if read_only:
        return
    if sorted(chosen) != sorted(entry["permissions"]) and st.button("Save what it may be used for", key=f"account_save_{service}"):
        accounts.set_permissions(service, chosen)
        _notice(f"{entry['name']} may now be used for: {', '.join(sorted(chosen)) or 'nothing'}.")
        st.rerun()
    if service == "github" and entry["permissions"] and st.button("Ask GitHub whether the token still works", key="account_check_github"):
        try:
            answer = accounts.check_github()
            if answer["accepted"]:
                until = f", valid until {answer['expires_at'][:10]}" if answer["expires_at"] else ", with no expiry date"
                _notice(f"GitHub accepts the token (account {answer['login']}{until}).")
            else:
                _notice(f"GitHub does not accept the token (it answered {answer['status']}).")
        except Exception as exc:  # the service could not be reached, or the account may not be used
            _notice(f"GitHub could not be asked: {exc}")
        st.rerun()
    if entry["can_be_deleted_here"]:
        if st.button("Unlink and delete the credential", key=f"account_unlink_{service}"):
            outcome = accounts.unlink(service)
            cancelled = " The service confirmed that it cancelled it." if outcome["cancelled_at_the_service"] else ""
            _notice(f"{entry['name']} is unlinked and the credential is deleted from this machine.{cancelled} {outcome['still_to_do']}".strip())
            st.rerun()
    else:
        st.caption("This account is linked outside the app. To unlink it, remove the environment variable. Unticking everything above stops the assistant from using it.")


def _not_linked(entry: dict[str, Any], read_only: bool) -> None:
    service = entry["service"]
    if entry["how_to_get"]:
        st.caption(f"What to link: {entry['how_to_get']}")
    if read_only:
        return
    with st.form(f"account_link_{service}", clear_on_submit=True):
        secret = st.text_input("Token or key", type="password", key=f"account_secret_{service}", help="Stored on this machine and never shown again.")
        st.markdown("**What the assistant may use it for**")
        chosen = [
            name
            for name, meaning in entry["known_permissions"].items()
            if st.checkbox(f"{name}: {meaning}" if meaning else name, value=False, key=f"account_new_{service}_may_{name}")
        ]
        expires = st.text_input("Runs out on (YYYY-MM-DD, optional)", key=f"account_expires_{service}", help="For a token with an expiry date. The app then says so instead of failing on the day.")
        if st.form_submit_button(f"Link {entry['name']}"):
            try:
                accounts.link(service, secret, permissions=chosen, expires_at=f"{expires.strip()}T00:00:00+00:00" if expires.strip() else "")
            except ValueError as exc:
                st.error(str(exc) if "empty" in str(exc) or "permission" in str(exc) else "The date could not be read. Use YYYY-MM-DD.")
            else:
                _notice(f"{entry['name']} is linked and may be used for: {', '.join(sorted(chosen)) or 'nothing yet'}.")
                st.rerun()


def render_accounts_panel(*, read_only: bool = False) -> None:
    st.subheader("Linked accounts")
    st.caption(
        "Credentials for outside services, and what the assistant may use each one for. Linking an account allows nothing by itself: "
        "tick what it may be used for. Whether an action then happens is still decided by the approval settings above. " + accounts.protection()[1]
    )
    notice = st.session_state.pop(NOTICE_KEY, "")
    if notice:
        st.success(notice)
    for entry in accounts.accounts():
        with st.expander(state_line(entry), expanded=bool(entry["problem"])):
            st.caption(entry["used_for"])
            if entry["linked"]:
                _linked(entry, read_only)
            else:
                _not_linked(entry, read_only)
