"""General utility helpers."""

from __future__ import annotations


def format_history_for_prompt(
    messages: list[dict[str, str]],
    latest_message: str,
    system_preamble: str = "",
) -> str:
    """Build a compact prompt with recent session context for Ollama."""

    recent_messages = messages[-4:]
    if not recent_messages:
        lines = []
        if system_preamble.strip():
            lines.extend([system_preamble.strip(), ""])
        lines.extend([f"User: {latest_message}", "Assistant:"])
        return "\n".join(lines)

    lines = []
    if system_preamble.strip():
        lines.extend([system_preamble.strip(), ""])
    lines.extend(
        [
            "Use the recent conversation for context.",
            "",
            "Recent conversation:",
        ]
    )
    for message in recent_messages:
        role = message.get("role", "user").title()
        content = message.get("content", "")
        lines.append(f"{role}: {content}")

    lines.extend(["", f"User: {latest_message}", "Assistant:"])
    return "\n".join(lines)
