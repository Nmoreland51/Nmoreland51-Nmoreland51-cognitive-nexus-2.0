"""Shared application configuration for Cognitive Nexus AI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CognitiveNexusSettings:
    app_title: str = "Cognitive Nexus"
    page_icon: str = ":brain:"
    host: str = "localhost"
    port: int = 8501
    ollama_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    hosted_budget_image_model: str = "gpt-image-1-mini"
    hosted_premium_image_model: str = "gpt-image-1.5"
    data_dir: Path = Path("data")
    app_dir: Path = Path("ai_system")
    knowledge_bank_dir: Path = Path("ai_system/knowledge_bank")
    reasoning_dir: Path = Path("ai_system/knowledge_bank/reasoning")
    image_dir: Path = Path("ai_system/knowledge_bank/images")
    web_research_dir: Path = Path("ai_system/knowledge_bank/web_research")
    icon_path: Path = Path("icon.ico")
    main_app_file: str = "cognitive_nexus_ai.py"

    @property
    def app_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@lru_cache(maxsize=1)
def get_settings() -> CognitiveNexusSettings:
    host = os.environ.get("COGNITIVE_NEXUS_HOST", "localhost")
    port = int(os.environ.get("COGNITIVE_NEXUS_PORT", "8501"))
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    hosted_budget_image_model = os.environ.get("COGNITIVE_NEXUS_HOSTED_BUDGET_IMAGE_MODEL", "gpt-image-1-mini")
    hosted_premium_image_model = os.environ.get("COGNITIVE_NEXUS_HOSTED_PREMIUM_IMAGE_MODEL", "gpt-image-1.5")

    settings = CognitiveNexusSettings(
        host=host,
        port=port,
        ollama_url=ollama_url,
        openai_api_key=openai_api_key,
        hosted_budget_image_model=hosted_budget_image_model,
        hosted_premium_image_model=hosted_premium_image_model,
    )
    ensure_directories(settings)
    return settings


def ensure_directories(settings: CognitiveNexusSettings) -> None:
    for path in (
        settings.data_dir,
        settings.app_dir,
        settings.knowledge_bank_dir,
        settings.reasoning_dir,
        settings.image_dir,
        settings.web_research_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
