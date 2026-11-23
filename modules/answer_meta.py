"""What produced an answer.

Every reply is labelled with who wrote it (which provider and model, or no model at all), where
the prompt went (this machine or a cloud service), how long it took, what it cost when a cloud
provider reported usage, and which tools actually ran. The record is small enough to store with
the chat message, so the label is still there when the chat is reloaded.
"""

from __future__ import annotations

from typing import Any

LOCAL_MODEL_PROVIDERS = {"ollama": "Ollama", "huggingface_local": "Local Transformers"}
CLOUD_MODEL_PROVIDERS = {"openai": "OpenAI", "anthropic": "Anthropic"}
# Paths that searched the web. The search queries and page requests leave this machine even when
# the model that summarizes the pages is local.
WEB_TOOL_PROVIDERS = {
    "web_research": "web search",
    "reality_research_agent": "research agent",
    "bloodhound_search": "Bloodhound search",
}
# Replies written by the app's own rules, with no model involved.
BUILT_IN_PROVIDERS = {
    "direct_response",
    "local_capability",
    "local_memory",
    "adaptive_memory",
    "local_fast_path",
    "local_followup_clarification",
    "local_topic_handler",
}


def answer_meta(provider_result: dict[str, Any] | None) -> dict[str, Any]:
    """Reduce a turn's provider result to a small record that can be saved with the message."""

    result = dict(provider_result or {})
    provider = str(result.get("provider") or "")
    tools: list[str] = [str(tool) for tool in result.get("tools_run") or []]
    model_provider = provider
    if provider in WEB_TOOL_PROVIDERS:
        if WEB_TOOL_PROVIDERS[provider] not in tools and "web_search" not in tools:
            tools.append("web_search")
        model_provider = str(result.get("model_provider") or "")
    retrieval = result.get("retrieval") or {}
    if int(retrieval.get("used_count") or 0) > 0:
        tools.append("local_knowledge")

    if model_provider in LOCAL_MODEL_PROVIDERS or model_provider in CLOUD_MODEL_PROVIDERS:
        answered = bool(result.get("success", True))
    else:
        answered = False

    if model_provider in CLOUD_MODEL_PROVIDERS:
        locality = "cloud"
    elif provider in WEB_TOOL_PROVIDERS:
        locality = "web"
    else:
        locality = "local"

    meta: dict[str, Any] = {
        "provider": provider,
        "model_provider": model_provider,
        "model": str(result.get("model") or ""),
        "answered": answered,
        "partial": bool(result.get("partial")),
        "locality": locality,
        "seconds": round(float(result.get("elapsed") or 0.0), 1),
        "tools": tools,
    }
    usage = result.get("usage") or {}
    if usage.get("input_tokens") or usage.get("output_tokens"):
        meta["input_tokens"] = int(usage.get("input_tokens") or 0)
        meta["output_tokens"] = int(usage.get("output_tokens") or 0)
        if usage.get("estimated_cost_usd") is not None:
            meta["cost_usd"] = float(usage["estimated_cost_usd"])
    reason = str(result.get("fallback_reason") or result.get("error") or "").strip()
    if reason and not answered:
        meta["reason"] = reason[:300]
    skipped = [str(name) for name in result.get("skipped_cloud") or []]
    if skipped:
        meta["skipped_cloud"] = skipped
    return meta


def _model_label(meta: dict[str, Any]) -> str:
    provider = str(meta.get("model_provider") or "")
    name = LOCAL_MODEL_PROVIDERS.get(provider) or CLOUD_MODEL_PROVIDERS.get(provider) or provider
    model = str(meta.get("model") or "")
    return f"{name} / {model}" if model else name


def describe_answer(meta: dict[str, Any] | None) -> str:
    """One line for under an answer. Empty when nothing is known about how it was produced."""

    if not meta or not meta.get("provider"):
        return ""
    provider = str(meta.get("provider") or "")
    model_provider = str(meta.get("model_provider") or "")
    answered = bool(meta.get("answered"))
    reason = str(meta.get("reason") or "")
    parts: list[str] = []

    if provider in WEB_TOOL_PROVIDERS:
        tool = WEB_TOOL_PROVIDERS[provider]
        if answered:
            parts.append(f"{tool.capitalize()}, written up by {_model_label(meta)}")
        elif model_provider and model_provider != "fallback":
            parts.append(f"{tool.capitalize()}; {_model_label(meta)} did not finish the write-up")
        elif provider == "web_research":
            parts.append(f"{tool.capitalize()}; no model wrote a summary")
        else:
            parts.append(tool.capitalize())
    elif provider == "fallback":
        parts.append("No model answered (this is the app's fallback notice)")
    elif provider == "local_knowledge_fallback":
        parts.append("Passages from your saved knowledge; no model was available")
    elif provider in BUILT_IN_PROVIDERS:
        parts.append("Built-in reply, no model used")
    elif answered:
        parts.append(f"Answered by {_model_label(meta)}")
    elif meta.get("partial"):
        parts.append(f"{_model_label(meta)} stopped part-way through this answer")
    else:
        parts.append(f"{_model_label(meta) or provider} did not answer")

    locality = meta.get("locality")
    if locality == "cloud":
        cloud = CLOUD_MODEL_PROVIDERS.get(model_provider, "a cloud service")
        sent = f"your prompt was sent to {cloud}"
        if provider in WEB_TOOL_PROVIDERS:
            sent += " and searches went to the web"
        parts.append(sent)
    elif locality == "web":
        parts.append("searches went to the web; the text was written on this machine" if answered else "searches went to the web")
    else:
        parts.append("stayed on this machine")

    seconds = float(meta.get("seconds") or 0.0)
    if seconds >= 0.05:
        parts.append(f"{seconds:.1f} s")

    if "cost_usd" in meta:
        parts.append(f"about ${float(meta['cost_usd']):.4f} ({int(meta.get('input_tokens', 0))} in / {int(meta.get('output_tokens', 0))} out tokens)")
    elif meta.get("input_tokens") or meta.get("output_tokens"):
        parts.append(f"{int(meta.get('input_tokens', 0))} in / {int(meta.get('output_tokens', 0))} out tokens, price not known")

    tools = [str(tool).replace("_", " ") for tool in meta.get("tools") or []]
    if provider in WEB_TOOL_PROVIDERS:
        tools = [tool for tool in tools if tool != "web search"]
    if tools:
        parts.append("used " + ", ".join(tools))

    line = " · ".join(parts)
    if reason and not answered and provider not in BUILT_IN_PROVIDERS and provider != "local_knowledge_fallback":
        line += f". Reason: {reason}"
    skipped = meta.get("skipped_cloud") or []
    if skipped and not answered:
        line += f" ({', '.join(CLOUD_MODEL_PROVIDERS.get(name, name) for name in skipped)} is set up but cloud fallback is off.)"
    return line
