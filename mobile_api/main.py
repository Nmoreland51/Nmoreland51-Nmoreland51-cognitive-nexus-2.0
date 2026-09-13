from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from mobile_api.schemas import (
    ChatMessageResponse,
    ChatRequest,
    ConversationDetail,
    ConversationSummary,
    DeleteResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    MemoryActionResponse,
    MemoryFactRequest,
    MemoryForgetRequest,
    MemoryOverviewResponse,
    ProvidersResponse,
    ResearchRequestBody,
    ResearchResponse,
    SettingsResponse,
    UrlResearchRequest,
    UrlResearchResponse,
)
from mobile_api.services import MobileApiService


@lru_cache(maxsize=1)
def get_service() -> MobileApiService:
    return MobileApiService()


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitive Nexus Mobile API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(service: MobileApiService = Depends(get_service)):
        return service.health()

    @app.post("/api/v1/chat", response_model=ChatMessageResponse)
    def chat(payload: ChatRequest, service: MobileApiService = Depends(get_service)):
        return service.chat(
            message=payload.message,
            user_id=payload.user_id,
            device_id=payload.device_id,
            conversation_id=payload.conversation_id,
            selected_model=payload.selected_model,
            provider_order=payload.provider_order,
            use_memory=payload.use_memory,
            use_web_for_chat=payload.use_web_for_chat,
            use_knowledge_for_chat=payload.use_knowledge_for_chat,
        )

    @app.post("/api/v1/chat/stream")
    def chat_stream(payload: ChatRequest, service: MobileApiService = Depends(get_service)):
        stream = service.stream_chat(
            message=payload.message,
            user_id=payload.user_id,
            device_id=payload.device_id,
            conversation_id=payload.conversation_id,
            selected_model=payload.selected_model,
            provider_order=payload.provider_order,
            use_memory=payload.use_memory,
            use_web_for_chat=payload.use_web_for_chat,
            use_knowledge_for_chat=payload.use_knowledge_for_chat,
        )
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/api/v1/conversations", response_model=list[ConversationSummary])
    def list_conversations(
        user_id: str | None = Query(default=None),
        device_id: str | None = Query(default=None),
        service: MobileApiService = Depends(get_service),
    ):
        return service.list_conversations(user_id=user_id, device_id=device_id)

    @app.get("/api/v1/conversations/{conversation_id}", response_model=ConversationDetail)
    def get_conversation(conversation_id: str, service: MobileApiService = Depends(get_service)):
        item = service.get_conversation(conversation_id)
        if not item:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return item

    @app.delete("/api/v1/conversations/{conversation_id}", response_model=DeleteResponse)
    def delete_conversation(conversation_id: str, service: MobileApiService = Depends(get_service)):
        deleted = service.delete_conversation(conversation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"success": True, "id": conversation_id, "message": "Conversation deleted."}

    @app.get("/api/v1/memory", response_model=MemoryOverviewResponse)
    def memory(service: MobileApiService = Depends(get_service)):
        return service.memory_overview()

    @app.post("/api/v1/memory/facts", response_model=MemoryActionResponse)
    def memory_fact(payload: MemoryFactRequest, service: MobileApiService = Depends(get_service)):
        return service.remember_fact(payload.text)

    @app.post("/api/v1/memory/forget", response_model=MemoryActionResponse)
    def memory_forget(payload: MemoryForgetRequest, service: MobileApiService = Depends(get_service)):
        return service.forget_fact(payload.query)

    @app.delete("/api/v1/memory/all", response_model=MemoryActionResponse)
    def memory_clear(service: MobileApiService = Depends(get_service)):
        return service.clear_memory()

    @app.post("/api/v1/feedback", response_model=FeedbackResponse)
    def feedback(payload: FeedbackRequest, service: MobileApiService = Depends(get_service)):
        return service.record_feedback(turn_id=payload.turn_id, rating=payload.rating, correction=payload.correction)

    @app.post("/api/v1/research", response_model=ResearchResponse)
    def research(payload: ResearchRequestBody, service: MobileApiService = Depends(get_service)):
        return service.run_research(
            query=payload.query,
            depth=payload.depth,
            max_sources=payload.max_sources,
            follow_links=payload.follow_links,
            save_to_memory=payload.save_to_memory,
            use_ai_summary=payload.use_ai_summary,
        )

    @app.get("/api/v1/research/history")
    def research_history(service: MobileApiService = Depends(get_service)):
        return service.research_history()

    @app.post("/api/v1/research/url", response_model=UrlResearchResponse)
    def research_url(payload: UrlResearchRequest, service: MobileApiService = Depends(get_service)):
        return service.research_url(url=payload.url)

    @app.post("/api/v1/images/generate", response_model=ImageGenerateResponse)
    def images_generate(payload: ImageGenerateRequest, service: MobileApiService = Depends(get_service)):
        return service.generate_image(
            prompt=payload.prompt,
            mode=payload.mode,
            provider=payload.provider,
            style=payload.style,
            negative_prompt=payload.negative_prompt,
            width=payload.width,
            height=payload.height,
            steps=payload.steps,
            cfg_scale=payload.cfg_scale,
            seed=payload.seed,
            num_images=payload.num_images,
        )

    @app.get("/api/v1/images/history")
    def images_history(service: MobileApiService = Depends(get_service)):
        return service.image_history()

    @app.delete("/api/v1/images/{image_id}", response_model=DeleteResponse)
    def images_delete(image_id: str, service: MobileApiService = Depends(get_service)):
        deleted = service.delete_image(image_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Image not found")
        return {"success": True, "id": image_id, "message": "Image deleted."}

    @app.get("/api/v1/providers", response_model=ProvidersResponse)
    def providers(service: MobileApiService = Depends(get_service)):
        return service.providers()

    @app.get("/api/v1/settings", response_model=SettingsResponse)
    def settings(service: MobileApiService = Depends(get_service)):
        return service.settings()

    return app


app = create_app()
