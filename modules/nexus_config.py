"""Central runtime configuration for the Cognitive Nexus dashboard."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from modules.data_stores import CONFIG_ROOT, LOG_ROOT
from modules.file_lock import locked
from modules.file_utils import atomic_write_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = CONFIG_ROOT
LOG_DIR = LOG_ROOT
INTERNAL_DIR = PROJECT_ROOT / "internal"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "nexus_config.json"
ENV_FILE = PROJECT_ROOT / ".env"


DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"

# Claude model IDs that the API no longer serves, with the current model in the same tier.
# Source: the "Retired Models" table in Anthropic's model reference, read 2026-11-23. A saved
# config or .env that still names one of these would fail on every request.
RETIRED_MODEL_IDS = {
    "claude-opus-4-1-20250805": "claude-opus-5-5",
    "claude-opus-4-1": "claude-opus-5-5",
    "claude-opus-4-20250514": "claude-opus-5-5",
    "claude-opus-4-0": "claude-opus-5-5",
    "claude-sonnet-4-20250514": "claude-sonnet-5-5",
    "claude-sonnet-4-0": "claude-sonnet-5-5",
    "claude-3-7-sonnet-20250219": "claude-sonnet-5-5",
    "claude-3-5-sonnet-20241022": "claude-sonnet-5-5",
    "claude-3-5-sonnet-20240620": "claude-sonnet-5-5",
    "claude-3-sonnet-20240229": "claude-sonnet-5-5",
    "claude-3-opus-20240229": "claude-opus-5-5",
    "claude-3-5-haiku-20241022": "claude-haiku-5-5",
    "claude-3-haiku-20240307": "claude-haiku-5-5",
    "claude-2.1": "claude-sonnet-5-5",
    "claude-2.0": "claude-sonnet-5-5",
}


# Models with an announced shutdown date: (date it stops working, replacement the vendor names).
# Sources, read 2026-11-23: OpenAI's deprecations page (the row for gpt-4.1-mini-2025-04-14,
# which the undated alias points to) and Anthropic's model reference.
SCHEDULED_SHUTDOWNS = {
    "gpt-4.1-mini": ("2027-01-14", "gpt-6-luna"),
    "gpt-4.1-mini-2025-04-14": ("2027-01-14", "gpt-6-luna"),
    "claude-sonnet-4-5": ("2026-11-30", "claude-sonnet-5-5"),
    "claude-sonnet-4-5-20250929": ("2026-11-30", "claude-sonnet-5-5"),
}


def current_model_id(model: str, today: date | None = None) -> tuple[str, str]:
    """Return (usable model ID, note).

    A retired ID is replaced. An ID with an announced shutdown date is kept until that date,
    with a warning, and replaced from that date on. The note is empty when nothing applies.
    """

    name = str(model or "").strip()
    replacement = RETIRED_MODEL_IDS.get(name)
    if replacement:
        return replacement, f"Model '{name}' has been retired by Anthropic; using '{replacement}' instead."
    scheduled = SCHEDULED_SHUTDOWNS.get(name)
    if scheduled:
        shutdown, replacement = scheduled
        if (today or date.today()) >= date.fromisoformat(shutdown):
            return replacement, f"Model '{name}' was shut down on {shutdown}; using '{replacement}' instead."
        return name, (
            f"Model '{name}' is scheduled to stop working on {shutdown}. "
            f"Its vendor recommends '{replacement}'; change the model setting before then."
        )
    return name, ""


DEFAULT_CONFIG: dict[str, Any] = {
    "provider_order": ["ollama", "openai", "anthropic", "huggingface_local", "fallback"],
    "ollama_url": "http://localhost:11434",
    "openai_model": "gpt-4.1-mini",
    "anthropic_model": DEFAULT_ANTHROPIC_MODEL,
    # How much thinking Claude does before answering: low, medium, high, xhigh or max.
    "anthropic_effort": "low",
    # Let the API re-run a request on another Claude model when a safety classifier declines it.
    "anthropic_refusal_fallback": True,
    # Owner-controlled behaviour (modules/behavior_policy.py). None means "the default text".
    "behavior_text": None,
    "reality_check": "label",
    "untrusted_content": "remove_and_fence",
    "agent_autonomy": "publishing_asks",
    # Off: a cloud provider is used only when it is first in provider_order. On: a configured
    # cloud provider lower in the order may answer when the providers before it fail.
    "allow_cloud_fallback": False,
    "hf_local_model": "",
    "comfyui_url": "http://127.0.0.1:8188",
    "max_context_chars": 12000,
    "recent_message_limit": 8,
    "summary_message_limit": 18,
    "provider_status_ttl_seconds": 45,
    "enable_response_verification": True,
    "enable_reality_grounding": True,
    "show_grounding_notes": True,
    "enable_reality_first_reasoning": True,
    "enable_reality_research_agent": True,
    "epistemic_mode": "auto",
    "enable_bloodhound_search": True,
    "enable_onion_search": False,
    "tor_socks_proxy": "127.0.0.1:9050",
    "max_search_results": 50,
    "search_timeout_seconds": 20,
    "enable_search_cache": True,
    "search_cache_ttl_hours": 24,
    "enable_link_following": True,
}


def ensure_runtime_dirs() -> None:
    """Create runtime folders used by the centralized backend."""

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    INTERNAL_DIR.mkdir(parents=True, exist_ok=True)


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load simple KEY=VALUE pairs from .env without requiring python-dotenv."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_runtime_config(path: Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """Load config/nexus_config.json and merge it with conservative defaults."""

    ensure_runtime_dirs()
    load_env_file()
    config = dict(DEFAULT_CONFIG)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config.update(payload)
    except Exception:
        pass

    config["ollama_url"] = os.environ.get("OLLAMA_URL", str(config["ollama_url"])).rstrip("/")
    config["openai_model"], openai_note = current_model_id(os.environ.get("OPENAI_MODEL") or str(config["openai_model"]))
    config["anthropic_model"], anthropic_note = current_model_id(os.environ.get("ANTHROPIC_MODEL") or str(config["anthropic_model"]))
    # Shown in Diagnostics, and only for a provider that is actually set up.
    config["model_id_notes"] = [
        note
        for note, key in ((openai_note, "OPENAI_API_KEY"), (anthropic_note, "ANTHROPIC_API_KEY"))
        if note and os.environ.get(key)
    ]
    config["anthropic_effort"] = os.environ.get("ANTHROPIC_EFFORT", str(config.get("anthropic_effort") or "low"))
    config["allow_cloud_fallback"] = _env_bool("ALLOW_CLOUD_FALLBACK", bool(config.get("allow_cloud_fallback", False)))
    config["ollama_max_num_ctx"] = _env_int("OLLAMA_MAX_NUM_CTX", int(config.get("ollama_max_num_ctx") or 0))
    config["hf_local_model"] = os.environ.get("HF_LOCAL_MODEL", str(config["hf_local_model"]))
    config["comfyui_url"] = os.environ.get("COMFYUI_URL", str(config["comfyui_url"])).rstrip("/")
    config["enable_bloodhound_search"] = _env_bool("ENABLE_BLOODHOUND_SEARCH", bool(config["enable_bloodhound_search"]))
    config["enable_reality_grounding"] = _env_bool("ENABLE_REALITY_GROUNDING", bool(config["enable_reality_grounding"]))
    config["show_grounding_notes"] = _env_bool("SHOW_GROUNDING_NOTES", bool(config["show_grounding_notes"]))
    config["enable_reality_first_reasoning"] = _env_bool("ENABLE_REALITY_FIRST_REASONING", bool(config["enable_reality_first_reasoning"]))
    config["enable_reality_research_agent"] = _env_bool("ENABLE_REALITY_RESEARCH_AGENT", bool(config["enable_reality_research_agent"]))
    config["epistemic_mode"] = os.environ.get("EPISTEMIC_MODE", str(config["epistemic_mode"]))
    config["enable_onion_search"] = _env_bool("ENABLE_ONION_SEARCH", bool(config["enable_onion_search"]))
    config["tor_socks_proxy"] = os.environ.get("TOR_SOCKS_PROXY", str(config["tor_socks_proxy"]))
    config["max_search_results"] = _env_int("MAX_SEARCH_RESULTS", int(config["max_search_results"]))
    config["search_timeout_seconds"] = _env_int("SEARCH_TIMEOUT_SECONDS", int(config["search_timeout_seconds"]))
    config["enable_search_cache"] = _env_bool("ENABLE_SEARCH_CACHE", bool(config["enable_search_cache"]))
    config["search_cache_ttl_hours"] = _env_int("SEARCH_CACHE_TTL_HOURS", int(config["search_cache_ttl_hours"]))
    config["enable_link_following"] = _env_bool("ENABLE_LINK_FOLLOWING", bool(config["enable_link_following"]))
    return config


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


def save_runtime_config(config: dict[str, Any], path: Path = DEFAULT_CONFIG_FILE) -> None:
    """Persist the non-secret runtime config."""

    ensure_runtime_dirs()
    serializable = {key: value for key, value in config.items() if "key" not in key.lower() and key != "model_id_notes"}
    with locked(path):
        atomic_write_text(path, json.dumps(serializable, indent=2, ensure_ascii=False))
