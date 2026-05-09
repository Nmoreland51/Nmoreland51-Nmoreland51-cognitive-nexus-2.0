"""Central runtime configuration for the Cognitive Nexus dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"
INTERNAL_DIR = PROJECT_ROOT / "internal"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "nexus_config.json"
ENV_FILE = PROJECT_ROOT / ".env"


DEFAULT_CONFIG: dict[str, Any] = {
    "provider_order": ["ollama", "openai", "anthropic", "huggingface_local", "fallback"],
    "ollama_url": "http://localhost:11434",
    "openai_model": "gpt-4.1-mini",
    "anthropic_model": "claude-sonnet-4-20250514",
    "hf_local_model": "",
    "comfyui_url": "http://127.0.0.1:8188",
    "max_context_chars": 12000,
    "recent_message_limit": 8,
    "summary_message_limit": 18,
    "provider_status_ttl_seconds": 45,
    "enable_response_verification": True,
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
    config["openai_model"] = os.environ.get("OPENAI_MODEL", str(config["openai_model"]))
    config["anthropic_model"] = os.environ.get("ANTHROPIC_MODEL", str(config["anthropic_model"]))
    config["hf_local_model"] = os.environ.get("HF_LOCAL_MODEL", str(config["hf_local_model"]))
    config["comfyui_url"] = os.environ.get("COMFYUI_URL", str(config["comfyui_url"])).rstrip("/")
    config["enable_bloodhound_search"] = _env_bool("ENABLE_BLOODHOUND_SEARCH", bool(config["enable_bloodhound_search"]))
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
    serializable = {key: value for key, value in config.items() if "key" not in key.lower()}
    path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
