"""Project inventory and status helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def count_files(pattern: str) -> int:
    return len(list(PROJECT_ROOT.glob(pattern)))


def count_matching_files(directory: Path, patterns: Iterable[str]) -> int:
    """Count files across multiple patterns under one directory."""

    if not directory.exists():
        return 0
    seen: set[Path] = set()
    for pattern in patterns:
        seen.update(path for path in directory.glob(pattern) if path.is_file())
    return len(seen)


def recent_files(directory: Path, patterns: Iterable[str], limit: int = 8) -> List[Dict[str, Any]]:
    """Return recent files for dashboard diagnostics without reading file bodies."""

    if not directory.exists():
        return []
    seen: set[Path] = set()
    for pattern in patterns:
        seen.update(path for path in directory.glob(pattern) if path.is_file())
    rows: List[Dict[str, Any]] = []
    for path in sorted(seen, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        stat = path.stat()
        try:
            display_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            display_path = str(path)
        rows.append(
            {
                "name": path.name,
                "path": display_path,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return rows


def get_project_inventory() -> Dict[str, Any]:
    """Summarize detected project systems without importing risky modules."""

    image_count = len(list((PROJECT_ROOT / "ai_system/knowledge_bank/images").glob("*.png")))
    image_count += len(list((PROJECT_ROOT / "generated_images").glob("*.png")))
    image_count += len(list((PROJECT_ROOT / "data/images/generated").glob("*.png")))

    research_dir = PROJECT_ROOT / "ai_system/knowledge_bank/web_research"
    chunks = read_json(research_dir / "chunks.json", {})
    metadata = read_json(research_dir / "metadata.json", {})
    report_dir = PROJECT_ROOT / "data" / "research_reports"
    web_research_dir = PROJECT_ROOT / "data" / "web_research"
    search_history_dir = PROJECT_ROOT / "data" / "search_history"
    knowledge_notes_dir = PROJECT_ROOT / "data" / "knowledge_notes"
    user_profile = read_json(PROJECT_ROOT / "data" / "user_profile.json", {})
    profile_facts = user_profile.get("facts", []) if isinstance(user_profile, dict) else []

    return {
        "streamlit_entrypoints": sorted(path.name for path in PROJECT_ROOT.glob("*streamlit*.py")) + ["app.py"],
        "python_files": count_files("*.py") + count_files("cognitive_nexus/*.py") + count_files("modules/*.py"),
        "legacy_main_apps": [
            "cognitive_nexus_ai.py",
            "cognitive_nexus_simple.py",
            "cognitive_web_research.py",
            "cognitive_nexus_with_reasoning.py",
            "fullstack_local_backend_app.py",
        ],
        "generated_images": image_count,
        "research_sources": len(metadata),
        "research_chunks": sum(len(value) for value in chunks.values() if isinstance(value, dict)),
        "research_reports": count_matching_files(report_dir, ("*.json", "*.md")),
        "web_research_sessions": count_matching_files(web_research_dir, ("*.json", "*.md")),
        "search_history_sessions": count_matching_files(search_history_dir, ("*.json", "*.md")),
        "knowledge_notes": count_matching_files(knowledge_notes_dir, ("*.md",)),
        "user_facts": len(profile_facts) if isinstance(profile_facts, list) else 0,
        "recent_research_reports": recent_files(report_dir, ("*.json", "*.md")),
        "recent_web_research": recent_files(web_research_dir, ("*.json", "*.md")),
        "recent_search_history": recent_files(search_history_dir, ("*.json", "*.md")),
        "recent_knowledge_notes": recent_files(knowledge_notes_dir, ("*.md",)),
        "memory_files": [
            "data/user_profile.json",
            "data/memory_candidates.json",
            "data/feedback_log.jsonl",
            "ai_system/knowledge_bank/chat_history.json",
        ],
        "skills": count_files("skills/*/SKILL.md"),
        "commands": count_files("commands/*.md"),
        "logs": sorted(path.name for path in PROJECT_ROOT.glob("*.log")),
    }


def get_environment_status() -> Dict[str, Any]:
    return {
        "cwd": str(PROJECT_ROOT),
        "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


def tail_file(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[-max_chars:]


def list_project_tools() -> List[Dict[str, str]]:
    tools: List[Dict[str, str]] = []
    for pattern in ("*.bat", "*.ps1", "commands/*.md", "skills/*/SKILL.md"):
        for path in sorted(PROJECT_ROOT.glob(pattern)):
            tools.append({"name": path.name, "path": str(path.relative_to(PROJECT_ROOT))})
    return tools
