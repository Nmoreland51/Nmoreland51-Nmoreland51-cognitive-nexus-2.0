from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from mobile_api.storage import ConversationStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


class MobileApiService:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or PROJECT_ROOT
        self.data_dir = self.project_root / "data"
        self.store = ConversationStore(self.data_dir / "mobile_api" / "conversations.db")

        from modules.chat_profile import load_chat_profile
        from modules.nexus_core import NexusCore

        self._core = NexusCore(project_root=self.project_root)
        self._load_chat_profile = load_chat_profile

    @property
    def core(self):
        return self._core

    def _runtime_settings(self, *, selected_model: str | None = None, provider_order: list[str] | None = None) -> dict[str, Any]:
        from nexus_router import RouterConfig

        cfg = dict(self.core.config)
        profile = self._load_chat_profile()
        model = (selected_model or cfg.get("openai_model") or "").strip()
        order = list(provider_order or cfg.get("provider_order") or ["ollama", "openai", "anthropic", "huggingface_local", "fallback"])
        return {
            "provider_ready": True,
            "selected_model": model,
            "base_url": cfg.get("ollama_url", ""),
            "provider_message": "Configured by mobile API",
            "use_memory": True,
            "use_knowledge_for_chat": True,
            "knowledge_top_k": 5,
            "knowledge_use_ai": True,
            "use_web_for_chat": True,
            "show_sources": True,
            "show_perf_timings": True,
            "advanced_mode": False,
            "demo_mode": False,
            "demo_safe_mode": False,
            "auto_precision_mode": True,
            "generation_timeout": 90.0,
            "provider_order": order,
            "throughput_mode": "balanced",
            "target_tokens_per_second": 0,
            "max_context_chars": int(cfg.get("max_context_chars", 12000)),
            "recent_message_limit": int(cfg.get("recent_message_limit", 8)),
            "response_mode": "balanced",
            "verbosity_level": 2,
            "reasoning_depth": 2,
            "staged_streaming": True,
            "enable_response_self_critic": True,
            "enable_reality_grounding": bool(cfg.get("enable_reality_grounding", True)),
            "enable_reality_first_reasoning": bool(cfg.get("enable_reality_first_reasoning", True)),
            "enable_reality_research_agent": bool(cfg.get("enable_reality_research_agent", True)),
            "epistemic_mode": str(cfg.get("epistemic_mode", "auto")),
            "show_grounding_notes": bool(cfg.get("show_grounding_notes", True)),
            "enable_bloodhound_search": bool(cfg.get("enable_bloodhound_search", True)),
            "bloodhound_depth": "Standard",
            "bloodhound_max_results": int(cfg.get("max_search_results", 50)),
            "bloodhound_timeout_seconds": int(cfg.get("search_timeout_seconds", 20)),
            "bloodhound_follow_links": bool(cfg.get("enable_link_following", True)),
            "bloodhound_enable_cache": bool(cfg.get("enable_search_cache", True)),
            "bloodhound_enable_onion": bool(cfg.get("enable_onion_search", False)),
            "hf_local_model": str(cfg.get("hf_local_model", "")),
            "reality_research_depth": "Standard",
            "reality_research_max_sources": int(cfg.get("max_search_results", 50)),
            "reality_research_follow_links": bool(cfg.get("enable_link_following", True)),
            "reality_research_save_memory": True,
            "reality_research_show_weak": True,
            "reality_research_use_ai": True,
            "comfyui_url": str(cfg.get("comfyui_url", "http://127.0.0.1:8188")),
            "chat_profile": profile,
            "safety_config": {"level": "balanced", "allow_nsfw": False, "allow_controversial": False, "allow_technical_dark": False},
            "router_config": RouterConfig(
                enabled=True,
                god_mode=False,
                freedom_level=0.6,
                use_llm_classifier=True,
                show_debug=False,
                default_model=model,
                creative_model=model,
                technical_model=model,
                sensitive_model=model,
                current_info_model=model,
            ),
        }

    def health(self) -> dict[str, Any]:
        from modules.core_health import run_core_health_check
        from modules.image_gen import detect_image_providers

        report = run_core_health_check(include_probe=False)
        return {
            "status": report.get("summary", {}).get("status", "unknown"),
            "generated_at": datetime.now(timezone.utc),
            "summary": report,
            "providers": self.core.status_snapshot().get("providers", []),
            "image_providers": detect_image_providers(),
        }

    def _chat_metadata(self) -> dict[str, Any]:
        return {
            "provider": str((self.core.last_provider_result or {}).get("provider", "")),
            "model": str((self.core.last_provider_result or {}).get("model", "")),
            "route": dict(self.core.last_route_decision or {}),
            "verification": dict(self.core.last_verification or {}),
            "grounding": dict(self.core.last_reality_audit or {}),
            "memory": dict(self.core.last_memory or {}),
            "retrieval": dict(self.core.last_retrieval or {}),
            "research": dict(self.core.last_reality_research_report or {}),
        }

    def chat(
        self,
        *,
        message: str,
        user_id: str,
        device_id: str,
        conversation_id: str | None,
        selected_model: str | None,
        provider_order: list[str] | None,
        use_memory: bool,
        use_web_for_chat: bool,
        use_knowledge_for_chat: bool,
    ) -> dict[str, Any]:
        title = message.strip()[:80] or "Conversation"
        cid = self.store.ensure_conversation(conversation_id=conversation_id, user_id=user_id, device_id=device_id, title=title)
        conv = self.store.get_conversation(cid) or {"messages": []}
        history = [{"role": item["role"], "content": item["content"]} for item in conv.get("messages", [])]
        settings = self._runtime_settings(selected_model=selected_model, provider_order=provider_order)
        settings["use_memory"] = use_memory
        settings["use_web_for_chat"] = use_web_for_chat
        settings["use_knowledge_for_chat"] = use_knowledge_for_chat

        user_mid = self.store.add_message(cid, "user", message, metadata={"source": "mobile_api"})
        history = history + [{"role": "user", "content": message}]
        answer = self.core.generate_chat_response(message, history, settings)
        meta = self._chat_metadata()
        assistant_mid = self.store.add_message(cid, "assistant", answer, metadata=meta)
        return {
            "conversation_id": cid,
            "message_id": assistant_mid,
            "user_message_id": user_mid,
            "assistant_reply": answer,
            "metadata": meta,
            "created_at": datetime.now(timezone.utc),
        }

    def stream_chat(self, *, message: str, user_id: str, device_id: str, conversation_id: str | None, selected_model: str | None, provider_order: list[str] | None, use_memory: bool, use_web_for_chat: bool, use_knowledge_for_chat: bool) -> Generator[str, None, None]:
        title = message.strip()[:80] or "Conversation"
        cid = self.store.ensure_conversation(conversation_id=conversation_id, user_id=user_id, device_id=device_id, title=title)
        conv = self.store.get_conversation(cid) or {"messages": []}
        history = [{"role": item["role"], "content": item["content"]} for item in conv.get("messages", [])]
        settings = self._runtime_settings(selected_model=selected_model, provider_order=provider_order)
        settings["use_memory"] = use_memory
        settings["use_web_for_chat"] = use_web_for_chat
        settings["use_knowledge_for_chat"] = use_knowledge_for_chat

        user_mid = self.store.add_message(cid, "user", message, metadata={"source": "mobile_api"})
        history = history + [{"role": "user", "content": message}]
        chunks: list[str] = []
        try:
            for chunk in self.core.stream_chat_response(message, history, settings):
                chunks.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'delta': chunk}, ensure_ascii=False)}\n\n"
        except Exception:
            self.store.add_message(
                cid,
                "assistant",
                "Streaming failed before completion.",
                metadata={"provider": "mobile_api", "error": "stream_failed"},
            )
            yield f"data: {json.dumps({'type': 'error', 'message': 'Streaming failed in backend adapter.'}, ensure_ascii=False)}\n\n"
            return

        answer = "".join(chunks).strip()
        meta = self._chat_metadata()
        assistant_mid = self.store.add_message(cid, "assistant", answer, metadata=meta)
        done = {
            "type": "done",
            "conversation_id": cid,
            "message_id": assistant_mid,
            "user_message_id": user_mid,
            "assistant_reply": answer,
            "metadata": meta,
        }
        yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

    def list_conversations(self, *, user_id: str | None = None, device_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.list_conversations(user_id=user_id, device_id=device_id)
        return [
            {
                "conversation_id": row["id"],
                "user_id": row["user_id"],
                "device_id": row["device_id"],
                "title": row["title"],
                "message_count": int(row["message_count"] or 0),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        item = self.store.get_conversation(conversation_id)
        if not item:
            return None
        return {
            "conversation_id": item["id"],
            "user_id": item["user_id"],
            "device_id": item["device_id"],
            "title": item["title"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "messages": [
                {
                    "message_id": msg["id"],
                    "role": msg["role"],
                    "content": msg["content"],
                    "created_at": msg["created_at"],
                    "metadata": msg.get("metadata", {}),
                }
                for msg in item.get("messages", [])
            ],
        }

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.store.delete_conversation(conversation_id)

    def _adaptive_memory(self):
        return self.core.get_adaptive_memory()

    def memory_overview(self) -> dict[str, Any]:
        from modules.context_manager import load_user_profile_summary

        adaptive = self._adaptive_memory()
        return {
            "summary": load_user_profile_summary(),
            "adaptive": adaptive.get_memory_overview() if adaptive else {"unavailable": True, "reason": "Adaptive memory module unavailable"},
        }

    def remember_fact(self, text: str) -> dict[str, Any]:
        from modules.context_manager import remember_user_fact

        payload = remember_user_fact(text)
        return {
            "success": bool(payload.get("success")),
            "action": "remember",
            "message": str(payload.get("message", "")),
            "payload": payload,
        }

    def forget_fact(self, query: str) -> dict[str, Any]:
        from modules.context_manager import forget_user_fact

        payload = forget_user_fact(query)
        return {
            "success": bool(payload.get("success")),
            "action": "forget",
            "message": str(payload.get("message", "")),
            "payload": payload,
        }

    def clear_memory(self) -> dict[str, Any]:
        from modules.context_manager import load_user_profile, save_user_profile

        adaptive = self._adaptive_memory()
        if adaptive:
            adaptive.clear_all()
        profile = load_user_profile()
        profile["facts"] = []
        profile["preferences"] = {}
        profile["patterns"] = {}
        profile["recurring_topics"] = {}
        profile["recent_feedback"] = []
        save_user_profile(profile)
        return {"success": True, "action": "clear_all", "message": "Cleared saved memory data.", "payload": {"adaptive_cleared": bool(adaptive)}}

    def record_feedback(self, *, turn_id: str, rating: str, correction: str) -> dict[str, Any]:
        adaptive = self._adaptive_memory()
        if not adaptive:
            return {"success": False, "event": None, "unavailable_reason": "Adaptive memory module unavailable"}
        event = adaptive.record_feedback(turn_id=turn_id, rating=rating, correction=correction)
        return {"success": True, "event": event.to_dict(), "unavailable_reason": None}

    def run_research(self, *, query: str, depth: str, max_sources: int, follow_links: bool, save_to_memory: bool, use_ai_summary: bool) -> dict[str, Any]:
        from modules.reality_research_agent import ResearchRequest

        settings = self._runtime_settings()
        request = ResearchRequest(
            query=query,
            depth=depth,
            max_sources=max_sources,
            follow_links=follow_links,
            save_to_memory=save_to_memory,
            use_ai_summary=use_ai_summary,
            save_report=True,
            show_weak_matches=True,
        )
        report = self.core.run_reality_research(request, settings)
        return {"success": True, "report": report.to_dict()}

    def research_history(self, limit: int = 50) -> list[dict[str, Any]]:
        reports_dir = self.data_dir / "research_reports"
        if not reports_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows.append(
                {
                    "id": path.stem,
                    "query": payload.get("query", ""),
                    "timestamp": payload.get("timestamp", ""),
                    "verdict": payload.get("verdict", ""),
                    "verdict_confidence": payload.get("verdict_confidence", 0.0),
                    "path": str(path),
                }
            )
        return rows

    def research_url(self, *, url: str) -> dict[str, Any]:
        from modules.research import process_url

        module = self.core.get_research_module()
        result = process_url(module, url)
        return {"success": result.get("status") == "success", "result": result}

    def generate_image(self, *, prompt: str, mode: str, provider: str | None, style: str, negative_prompt: str, width: int, height: int, steps: int, cfg_scale: float, seed: int | None, num_images: int) -> dict[str, Any]:
        from modules.image_gen import ImageGenerationRequest

        mode_provider = {
            "local_private": "diffusers_local",
            "hosted_budget": "automatic1111",
            "hosted_premium": "comfyui",
        }
        chosen_provider = (provider or mode_provider.get(mode) or "auto").strip()
        request = ImageGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            num_images=num_images,
            provider=chosen_provider,
            style=style,
            save_outputs=True,
        )
        result = self.core.generate_image(request)
        normalized_provider = str(result.get("provider") or chosen_provider)
        return {"success": bool(result.get("success")), "provider": normalized_provider, "result": result}

    def image_history(self, limit: int = 100) -> list[dict[str, Any]]:
        from modules.image_gen import list_generated_images

        images = list_generated_images(limit=limit)
        rows: list[dict[str, Any]] = []
        for item in images:
            path = item.get("path")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            image_id = metadata.get("filename") or item.get("name")
            rows.append(
                {
                    "image_id": image_id,
                    "name": item.get("name"),
                    "path": str(path) if path else "",
                    "size": item.get("size", 0),
                    "modified": item.get("modified", 0),
                    "metadata": metadata,
                }
            )
        return rows

    def delete_image(self, image_id: str) -> bool:
        history = self.image_history(limit=1000)
        match = next((item for item in history if item.get("image_id") == image_id or item.get("name") == image_id), None)
        if not match:
            return False
        image_path = Path(str(match.get("path")))
        if image_path.exists():
            image_path.unlink()
        metadata_path = image_path.with_suffix(".json")
        if metadata_path.exists():
            metadata_path.unlink()
        return True

    def providers(self) -> dict[str, Any]:
        from modules.image_gen import detect_image_providers

        return {
            "text_providers": self.core.status_snapshot().get("providers", []),
            "image_providers": detect_image_providers(),
        }

    def settings(self) -> dict[str, Any]:
        from modules.chat_profile import load_chat_profile

        config = dict(self.core.config)
        for key in list(config):
            if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                config.pop(key, None)
        return {
            "runtime_config": config,
            "chat_profile": asdict(load_chat_profile()),
            "non_secret_keys_only": True,
        }
