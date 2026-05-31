"""Core stability checks for the Cognitive Nexus dashboard."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from modules.nexus_config import DEFAULT_CONFIG, ensure_runtime_dirs, load_runtime_config
from modules.project_status import PROJECT_ROOT
from modules.provider_router import ProviderRequest, ProviderRouter
from modules.providers import FALLBACK_RESPONSE


CORE_IMPORTS = (
    "core",
    "core.reasoning",
    "core.reality_grounding",
    "modules.nexus_core",
    "modules.provider_router",
    "modules.providers",
    "modules.research",
    "modules.web_research",
    "nexus_router",
    "web_research_module",
)

LOCAL_TEXT_PROVIDERS = ("ollama", "huggingface_local")


def check_imports(import_names: Iterable[str] = CORE_IMPORTS) -> list[dict[str, Any]]:
    """Import critical modules and report failures without raising."""

    rows: list[dict[str, Any]] = []
    for module_name in import_names:
        started = time.perf_counter()
        try:
            importlib.import_module(module_name)
            rows.append(
                {
                    "name": module_name,
                    "status": "ok",
                    "message": "Imported cleanly.",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "name": module_name,
                    "status": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                }
            )
    return rows


def check_provider_status(
    provider_order: Iterable[str] | None = None,
    *,
    config: dict[str, Any] | None = None,
    router: ProviderRouter | None = None,
) -> list[dict[str, Any]]:
    """Detect configured providers and normalize them for diagnostics."""

    resolved_config = dict(config or load_runtime_config())
    order = list(provider_order or resolved_config.get("provider_order") or DEFAULT_CONFIG["provider_order"])
    provider_router = router or ProviderRouter(resolved_config)
    rows: list[dict[str, Any]] = []
    for provider in order:
        started = time.perf_counter()
        try:
            info = provider_router.detect_provider(provider, ttl=0)
            rows.append(
                {
                    "name": info.name,
                    "status": "ready" if info.available else "offline",
                    "available": bool(info.available),
                    "models": list(info.models or []),
                    "model_count": len(info.models or []),
                    "base_url": info.base_url,
                    "message": info.message,
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "name": provider,
                    "status": "error",
                    "available": False,
                    "models": [],
                    "model_count": 0,
                    "base_url": "",
                    "message": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                }
            )
    return rows


def check_storage_paths(project_root: Path = PROJECT_ROOT) -> list[dict[str, Any]]:
    """Check the local folders that keep Nexus state on disk."""

    paths = (
        ("project_root", project_root, True),
        ("config", project_root / "config", True),
        ("logs", project_root / "logs", True),
        ("data", project_root / "data", True),
        ("research_reports", project_root / "data" / "research_reports", False),
        ("knowledge_notes", project_root / "data" / "knowledge_notes", False),
        ("web_research", project_root / "ai_system" / "knowledge_bank" / "web_research", False),
    )
    rows: list[dict[str, Any]] = []
    for name, path, required in paths:
        exists = path.exists()
        writable = bool(exists and os.access(path, os.W_OK))
        if exists and writable:
            status = "ok"
            message = "Present and writable."
        elif exists:
            status = "error" if required else "warning"
            message = "Present but not writable."
        else:
            status = "error" if required else "missing"
            message = "Missing required path." if required else "Not created yet."
        rows.append(
            {
                "name": name,
                "path": str(path),
                "required": required,
                "status": status,
                "exists": exists,
                "writable": writable,
                "message": message,
            }
        )
    return rows


def choose_local_probe_order(provider_order: Iterable[str] | None = None) -> list[str]:
    """Probe local providers first and keep fallback as a final diagnostic path."""

    order = list(provider_order or DEFAULT_CONFIG["provider_order"])
    local_order = [name for name in order if name in LOCAL_TEXT_PROVIDERS]
    if not local_order:
        local_order = list(LOCAL_TEXT_PROVIDERS)
    return local_order + ["fallback"]


def run_provider_probe(
    provider_order: Iterable[str] | None = None,
    *,
    selected_model: str = "",
    config: dict[str, Any] | None = None,
    router_factory: Callable[[dict[str, Any]], ProviderRouter] = ProviderRouter,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Ask a local text provider for a tiny answer and report whether it was real."""

    resolved_config = dict(config or load_runtime_config())
    started = time.perf_counter()
    probe_order = choose_local_probe_order(provider_order)
    router = router_factory(resolved_config)
    request = ProviderRequest(
        prompt="Reply with exactly: Cognitive Nexus works.",
        model=str(selected_model or ""),
        provider_order=probe_order,
        base_url=str(resolved_config.get("ollama_url") or ""),
        options={"temperature": 0.0, "num_predict": 24, "num_ctx": 1024},
        timeout=timeout,
        max_tokens=24,
    )
    try:
        result = router.generate(request)
        text = result.text.strip()
        used_fallback = result.provider == "fallback" or text.startswith(FALLBACK_RESPONSE)
        success = bool(result.success and text and not used_fallback)
        return {
            "status": "ok" if success else "error",
            "success": success,
            "provider": result.provider,
            "model": result.model,
            "text_preview": text[:300],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "attempts": result.attempts,
            "error": "" if success else (result.error or "Only fallback responded to the live model probe."),
            "provider_order": probe_order,
        }
    except Exception as exc:
        return {
            "status": "error",
            "success": False,
            "provider": "",
            "model": str(selected_model or ""),
            "text_preview": "",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "attempts": [],
            "error": f"{type(exc).__name__}: {exc}",
            "provider_order": probe_order,
        }


def collect_recent_log_signals(project_root: Path = PROJECT_ROOT, limit: int = 12) -> list[dict[str, str]]:
    """Collect recent error-looking log lines for the diagnostics panel."""

    candidates = (
        project_root / "streamlit_app.err.log",
        project_root / "logs" / "cognitive_nexus.log",
    )
    signals: list[dict[str, str]] = []
    markers = ("error", "exception", "traceback", "failed", "warning")
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        interesting = [line for line in lines if any(marker in line.lower() for marker in markers)]
        for line in (interesting or lines)[-limit:]:
            signals.append({"file": path.name, "line": line[-500:]})
    return signals[-limit:]


def summarize_health(
    import_rows: list[dict[str, Any]],
    provider_rows: list[dict[str, Any]],
    storage_rows: list[dict[str, Any]],
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collapse detailed health rows into one honest dashboard verdict."""

    import_errors = [row for row in import_rows if row.get("status") == "error"]
    storage_errors = [
        row
        for row in storage_rows
        if row.get("required") and row.get("status") not in {"ok"}
    ]
    ready_model_providers = [
        row
        for row in provider_rows
        if row.get("name") != "fallback" and row.get("available")
    ]
    probe_failed = bool(probe and probe.get("status") == "error")

    if import_errors or storage_errors:
        status = "error"
    elif probe_failed or not ready_model_providers:
        status = "degraded"
    else:
        status = "ok"

    if import_errors:
        message = f"{len(import_errors)} critical import(s) failed."
    elif storage_errors:
        message = f"{len(storage_errors)} required local storage path(s) are broken."
    elif probe_failed:
        message = "Live local model probe failed; chat may fall back instead of answering."
    elif not ready_model_providers:
        message = "No real model provider is ready; only fallback text is available."
    else:
        message = "Core imports, local storage, and at least one real model provider are ready."

    return {
        "status": status,
        "message": message,
        "import_errors": len(import_errors),
        "storage_errors": len(storage_errors),
        "ready_model_providers": [str(row.get("name")) for row in ready_model_providers],
        "provider_ready": bool(ready_model_providers),
        "probe_status": (probe or {}).get("status", "not_run"),
    }


def run_core_health_check(
    project_root: Path = PROJECT_ROOT,
    provider_order: Iterable[str] | None = None,
    *,
    selected_model: str = "",
    include_probe: bool = False,
) -> dict[str, Any]:
    """Run the self-check used by Diagnostics and by `python -m modules.core_health`."""

    ensure_runtime_dirs()
    config = load_runtime_config()
    order = list(provider_order or config.get("provider_order") or DEFAULT_CONFIG["provider_order"])
    import_rows = check_imports()
    provider_rows = check_provider_status(order, config=config)
    storage_rows = check_storage_paths(project_root)
    probe = (
        run_provider_probe(order, selected_model=selected_model, config=config)
        if include_probe
        else {"status": "not_run", "success": None, "message": "Live probe not requested."}
    )
    summary = summarize_health(import_rows, provider_rows, storage_rows, probe)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "imports": import_rows,
        "providers": provider_rows,
        "storage": storage_rows,
        "probe": probe,
        "recent_log_signals": collect_recent_log_signals(project_root),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Cognitive Nexus core stability checks.")
    parser.add_argument("--probe", action="store_true", help="Run a live local model probe.")
    parser.add_argument("--model", default="", help="Optional selected Ollama/local model.")
    args = parser.parse_args()
    report = run_core_health_check(selected_model=args.model, include_probe=args.probe)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
