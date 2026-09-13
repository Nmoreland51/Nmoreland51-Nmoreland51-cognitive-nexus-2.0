# Cognitive Nexus Mobile API (`mobile_api/`)

This FastAPI service is an additive adapter over the existing Python Cognitive Nexus source-of-truth modules.

## What it reuses
- Chat orchestration: `modules/nexus_core.py` (`NexusCore`)
- Provider routing/fallbacks: `modules/provider_router.py`
- Memory facts/profile: `modules/context_manager.py`
- Adaptive memory + feedback: `cognitive_nexus/adaptation.py` (when available)
- Reality-first research: `modules/reality_research_agent.py`
- URL ingestion/knowledge retrieval: `modules/research.py`
- Grounding metadata: `core/reality_grounding/`
- Image generation/history: `modules/image_gen.py`
- Runtime config/profile: `modules/nexus_config.py`, `modules/chat_profile.py`

## Install
From repository root:

```bash
pip install -r requirements.txt
pip install -r mobile_api/requirements.txt
```

If your environment cannot safely alter base dependencies, install only `mobile_api/requirements.txt` in a dedicated venv that also has repository runtime requirements.

## Run
From repository root:

```bash
uvicorn mobile_api.main:app --host 0.0.0.0 --port 8001 --reload
```

## Endpoints (`/api/v1`)
- `GET /health`
- `POST /chat`
- `POST /chat/stream` (SSE; emits true streamed chunks from `NexusCore.stream_chat_response`)
- `GET /conversations`
- `GET /conversations/{conversation_id}`
- `DELETE /conversations/{conversation_id}`
- `GET /memory`
- `POST /memory/facts`
- `POST /memory/forget`
- `DELETE /memory/all`
- `POST /feedback`
- `POST /research`
- `GET /research/history`
- `POST /research/url`
- `POST /images/generate`
- `GET /images/history`
- `DELETE /images/{image_id}`
- `GET /providers`
- `GET /settings`

## Persistence and scoping
- Conversation/message persistence: `data/mobile_api/conversations.db` (SQLite)
- Existing Cognitive Nexus persistence remains unchanged and is still used by underlying modules (`data/user_profile.json`, `data/research_reports`, `data/images`, etc.).
- Conversation endpoints accept `user_id` + `device_id` for safe client scoping.

## Security assumptions
- No provider API keys are ever returned by API responses.
- `GET /settings` strips obvious secret/token/key fields.
- Authenticate this API behind your existing auth/reverse proxy when exposed beyond local development.

## CORS / proxy / HTTPS
- CORS is currently open for development (`*`). Restrict in production.
- For internet or LAN exposure, place behind a TLS reverse proxy and require HTTPS.
- Do not expose local model/admin interfaces directly to untrusted networks.

## Unavailable service behavior
This API does **not** fake capabilities:
- Missing API keys/providers are surfaced via provider status and operation errors.
- If no real model is available, fallback/unavailable states are returned from existing routing logic.
- Streaming emits real chunks when generated; failures are emitted as SSE error events.
