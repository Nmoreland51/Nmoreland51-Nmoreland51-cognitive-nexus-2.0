from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "backend" / "local_memory.db"
IMAGES_DIR = ROOT / "generated_images"
FRONTEND_DIR = ROOT / "frontend"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1:8b")

app = FastAPI(title="Cognitive Nexus Local Fullstack")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(default="default")
    model: Optional[str] = None

class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1)
    style: str = "realistic"
    session_id: str = Field(default="default")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def add_message(session_id: str, role: str, content: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.utcnow().isoformat()),
        )


def recent_context(session_id: str, limit: int = 10) -> List[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def chat_with_ollama(user_message: str, context: List[dict], model: str = "") -> str:
    """Generate a response using Ollama's /api/chat endpoint.
    
    Args:
        user_message: The user's message.
        context: Recent chat history (list of dicts with 'role' and 'content').
        model: Model name to use. If empty, uses global CHAT_MODEL.
    
    Returns:
        The assistant's response text.
    
    Raises:
        HTTPException: If Ollama is unavailable or fails to respond.
    """
    effective_model = model or CHAT_MODEL
    system = {
        "role": "system",
        "content": "You are a local AI assistant. Use context and be concise.",
    }
    payload = {
        "model": effective_model,
        "messages": [system, *context, {"role": "user", "content": user_message}],
        "stream": False,
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "No response generated.")
    except requests.RequestException as e:
        # Log detailed error server-side; return safe error to client
        import logging
        logging.error(f"Ollama chat error with model '{effective_model}': {e}")
        raise HTTPException(status_code=502, detail="Ollama is unavailable or failed to respond.")
    except Exception as e:
        import logging
        logging.error(f"Unexpected error in chat_with_ollama: {e}")
        raise HTTPException(status_code=500, detail="Internal server error.")


def generate_placeholder_image(prompt: str, style: str, context_summary: str) -> str:
    # Fully local fallback image path if no SD backend configured.
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1024, 1024), color=(18, 24, 38))
    draw = ImageDraw.Draw(img)
    text = f"Local Image\nStyle: {style}\n\nPrompt:\n{prompt[:220]}\n\nContext:\n{context_summary[:220]}"
    draw.multiline_text((40, 40), text, fill=(230, 238, 255), spacing=8)
    filename = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    out = IMAGES_DIR / filename
    img.save(out)
    return filename


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    """Check backend and Ollama availability.
    
    Returns HTTP 200 with ok=true if Ollama is available.
    Returns HTTP 503 with ok=false if Ollama is unavailable.
    """
    from modules.providers import check_ollama_status
    
    try:
        status = check_ollama_status(base_url=OLLAMA_URL, timeout=2.0)
    except Exception:
        status = None
    
    if status and status.available:
        return {
            "ok": True,
            "ollama_available": True,
            "chat_model": CHAT_MODEL,
            "time": datetime.utcnow().isoformat(),
        }
    else:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "ollama_available": False,
                "chat_model": CHAT_MODEL,
                "time": datetime.utcnow().isoformat(),
                "detail": "Ollama is unavailable",
            }
        )


@app.get("/api/models")
def get_models() -> dict:
    """Return list of available Ollama models for client model picker.
    
    Returns HTTP 200 with model list if Ollama is available.
    Returns HTTP 503 if Ollama is unavailable.
    
    Response (HTTP 200):
        {
            "models": ["model-name:tag", ...],
            "default_model": "model-name:tag",
            "ollama_available": true
        }
    
    Response (HTTP 503):
        {
            "detail": "Ollama is unavailable",
            "ollama_available": false,
            "models": [],
            "default_model": null
        }
    """
    from modules.providers import check_ollama_status
    
    try:
        status = check_ollama_status(base_url=OLLAMA_URL, timeout=2.0)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Ollama is unavailable",
                "ollama_available": False,
                "models": [],
                "default_model": None,
            }
        )
    
    if not status.available:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Ollama is unavailable",
                "ollama_available": False,
                "models": [],
                "default_model": None,
            }
        )
    
    # Ollama is available
    models = status.models or []
    
    # Determine default model: prefer CHAT_MODEL if installed, else first model, else None
    default_model = None
    if CHAT_MODEL in models:
        default_model = CHAT_MODEL
    elif models:
        default_model = models[0]
    
    return {
        "models": models,
        "default_model": default_model,
        "ollama_available": True,
    }


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    """Send a message and get an AI response.
    
    Supports optional model selection via the 'model' field.
    If no model is specified, uses the configured CHAT_MODEL.
    
    Request:
        {
            "message": "Your question here",
            "session_id": "session-identifier",
            "model": "optional-model-name:tag"
        }
    
    Response (HTTP 200):
        {
            "reply": "Assistant response",
            "session_id": "session-identifier",
            "model": "model-used"
        }
    
    Error responses:
    - HTTP 422: Selected model is not installed
    - HTTP 503: Ollama is unavailable
    - HTTP 500: Internal server error
    """
    from modules.providers import check_ollama_status
    
    # Determine which model to use
    selected_model = req.model or CHAT_MODEL
    
    # Quick check: is Ollama available and is the model installed?
    try:
        status = check_ollama_status(base_url=OLLAMA_URL, timeout=2.0)
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama is unavailable or failed to respond.")
    
    if not status.available:
        raise HTTPException(status_code=503, detail="Ollama is unavailable.")
    
    if selected_model not in status.models:
        raise HTTPException(
            status_code=422,
            detail=f"Selected model '{selected_model}' is not installed on the Cognitive Nexus server.",
        )
    
    # Proceed with chat
    context = recent_context(req.session_id)
    add_message(req.session_id, "user", req.message)
    
    try:
        answer = chat_with_ollama(req.message, context, model=selected_model)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error.")
    
    add_message(req.session_id, "assistant", answer)
    return {
        "reply": answer,
        "session_id": req.session_id,
        "model": selected_model,
    }


@app.post("/api/image")
def image(req: ImageRequest) -> dict:
    # Image context fix: include recent conversation context in generation metadata.
    context = recent_context(req.session_id, limit=6)
    context_summary = " | ".join([f"{m['role']}: {m['content']}" for m in context])
    enhanced_prompt = f"{req.prompt}. style={req.style}. conversation_context={context_summary}".strip()

    filename = generate_placeholder_image(enhanced_prompt, req.style, context_summary)
    add_message(req.session_id, "assistant", f"[image] {filename} :: {enhanced_prompt[:400]}")
    return {
        "image_url": f"/images/{filename}",
        "effective_prompt": enhanced_prompt,
        "session_id": req.session_id,
    }


app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
