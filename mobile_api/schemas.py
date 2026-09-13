from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    generated_at: datetime
    summary: dict[str, Any]
    providers: list[dict[str, Any]]
    image_providers: list[dict[str, Any]]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(default="local_user", min_length=1)
    device_id: str = Field(default="device_default", min_length=1)
    conversation_id: str | None = None
    selected_model: str | None = None
    provider_order: list[str] | None = None
    use_memory: bool = True
    use_web_for_chat: bool = True
    use_knowledge_for_chat: bool = True


class ChatMetadata(BaseModel):
    provider: str = ""
    model: str = ""
    route: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    grounding: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    research: dict[str, Any] = Field(default_factory=dict)


class ChatMessageResponse(BaseModel):
    conversation_id: str
    message_id: str
    user_message_id: str
    assistant_reply: str
    metadata: ChatMetadata
    created_at: datetime


class ConversationSummary(BaseModel):
    conversation_id: str
    user_id: str
    device_id: str
    title: str
    message_count: int
    updated_at: datetime


class ConversationMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationDetail(BaseModel):
    conversation_id: str
    user_id: str
    device_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage]


class DeleteResponse(BaseModel):
    success: bool
    id: str
    message: str


class MemoryOverviewResponse(BaseModel):
    summary: dict[str, Any]
    adaptive: dict[str, Any]


class MemoryFactRequest(BaseModel):
    text: str = Field(min_length=1)


class MemoryForgetRequest(BaseModel):
    query: str = Field(min_length=1)


class MemoryActionResponse(BaseModel):
    success: bool
    action: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down", "neutral"]
    turn_id: str = Field(default="mobile_api")
    correction: str = ""


class FeedbackResponse(BaseModel):
    success: bool
    event: dict[str, Any] | None = None
    unavailable_reason: str | None = None


class ResearchRequestBody(BaseModel):
    query: str = Field(min_length=1)
    depth: str = "Standard"
    max_sources: int = Field(default=25, ge=1, le=100)
    follow_links: bool = True
    save_to_memory: bool = True
    use_ai_summary: bool = True


class ResearchResponse(BaseModel):
    success: bool
    report: dict[str, Any]


class UrlResearchRequest(BaseModel):
    url: str = Field(min_length=1)


class UrlResearchResponse(BaseModel):
    success: bool
    result: dict[str, Any]


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    mode: Literal["local_private", "hosted_budget", "hosted_premium"] = "local_private"
    provider: str | None = None
    style: str = "realistic"
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 25
    cfg_scale: float = 7.0
    seed: int | None = None
    num_images: int = 1


class ImageGenerateResponse(BaseModel):
    success: bool
    provider: str
    result: dict[str, Any]


class ProvidersResponse(BaseModel):
    text_providers: list[dict[str, Any]]
    image_providers: list[dict[str, Any]]


class SettingsResponse(BaseModel):
    runtime_config: dict[str, Any]
    chat_profile: dict[str, Any]
    non_secret_keys_only: bool = True
