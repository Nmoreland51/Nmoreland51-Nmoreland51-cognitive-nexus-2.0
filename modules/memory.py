"""Session memory helpers for the Streamlit chatbot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import streamlit as st


Message = Dict[str, str]
SESSION_HISTORY_FILE = Path("data/chat_history.json")
LEGACY_HISTORY_FILE = Path("ai_system/knowledge_bank/chat_history.json")


def initialize_chat_state() -> None:
    """Create session message storage if it does not already exist."""

    if "messages" not in st.session_state:
        st.session_state.messages = []


def get_messages() -> List[Message]:
    """Return the current session's chat messages."""

    initialize_chat_state()
    return st.session_state.messages


def add_message(role: str, content: str) -> None:
    """Append a chat message to the current Streamlit session."""

    initialize_chat_state()
    st.session_state.messages.append({"role": role, "content": content})


def clear_messages() -> None:
    """Clear chat history for the current session."""

    st.session_state.messages = []


def load_json_history(path: Path) -> List[dict]:
    """Load a JSON chat-history list."""

    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return payload
    except Exception:
        return []
    return []


def save_session_history() -> None:
    """Persist the current session chat to data/chat_history.json."""

    SESSION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "messages": get_messages(),
    }
    SESSION_HISTORY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_session_history_file() -> None:
    """Persist an empty dashboard chat history file."""

    SESSION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "messages": [],
    }
    SESSION_HISTORY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_session_history_file() -> List[dict]:
    """Load the dashboard session history file."""

    try:
        if SESSION_HISTORY_FILE.exists():
            payload = json.loads(SESSION_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                messages = payload.get("messages", [])
                return messages if isinstance(messages, list) else []
            if isinstance(payload, list):
                return payload
    except Exception:
        return []
    return []


def load_legacy_history() -> List[dict]:
    """Load conversation history from the legacy Cognitive Nexus knowledge bank."""

    return load_json_history(LEGACY_HISTORY_FILE)
