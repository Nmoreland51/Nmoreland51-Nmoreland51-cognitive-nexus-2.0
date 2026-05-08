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
from fastapi.responses import FileResponse
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


def chat_with_ollama(user_message: str, context: List[dict]) -> str:
    system = {
        "role": "system",
        "content": "You are a local AI assistant. Use context and be concise.",
    }
    payload = {
        "model": CHAT_MODEL,
        "messages": [system, *context, {"role": "user", "content": user_message}],
        "stream": False,
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "No response generated.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chat backend error: {e}")


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
    return {"ok": True, "chat_model": CHAT_MODEL, "time": datetime.utcnow().isoformat()}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    context = recent_context(req.session_id)
    add_message(req.session_id, "user", req.message)
    answer = chat_with_ollama(req.message, context)
    add_message(req.session_id, "assistant", answer)
    return {"reply": answer, "session_id": req.session_id}


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
