"""Project inventory and status helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


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


def get_project_inventory() -> Dict[str, Any]:
    """Summarize detected project systems without importing risky modules."""

    image_count = len(list((PROJECT_ROOT / "ai_system/knowledge_bank/images").glob("*.png")))
    image_count += len(list((PROJECT_ROOT / "generated_images").glob("*.png")))
    image_count += len(list((PROJECT_ROOT / "data/images/generated").glob("*.png")))

    research_dir = PROJECT_ROOT / "ai_system/knowledge_bank/web_research"
    chunks = read_json(research_dir / "chunks.json", {})
    metadata = read_json(research_dir / "metadata.json", {})

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
