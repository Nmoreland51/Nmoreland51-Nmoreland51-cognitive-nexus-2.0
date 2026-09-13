from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from mobile_api.main import create_app


class FakeService:
    fail_stream = False

    def health(self):
        return {
            "status": "degraded",
            "generated_at": datetime.now(timezone.utc),
            "summary": {"summary": {"status": "degraded"}},
            "providers": [],
            "image_providers": [],
        }

    def chat(self, **_kwargs):
        return {
            "conversation_id": "conv_1",
            "message_id": "msg_2",
            "user_message_id": "msg_1",
            "assistant_reply": "hello",
            "metadata": {"provider": "fallback", "model": "", "route": {}, "verification": {}, "grounding": {}, "memory": {}, "retrieval": {}, "research": {}},
            "created_at": datetime.now(timezone.utc),
        }

    def stream_chat(self, **_kwargs):
        yield "data: " + json.dumps({"type": "chunk", "delta": "hel"}) + "\n\n"
        if self.fail_stream:
            raise RuntimeError("simulated stream failure")
        yield "data: " + json.dumps({"type": "done", "assistant_reply": "hello"}) + "\n\n"

    def list_conversations(self, **_kwargs):
        return [{"conversation_id": "conv_1", "user_id": "u", "device_id": "d", "title": "t", "message_count": 2, "updated_at": datetime.now(timezone.utc)}]

    def get_conversation(self, conversation_id: str, user_id: str, device_id: str):
        if conversation_id != "conv_1":
            return None
        now = datetime.now(timezone.utc)
        return {
            "conversation_id": "conv_1",
            "user_id": "u",
            "device_id": "d",
            "title": "t",
            "created_at": now,
            "updated_at": now,
            "messages": [{"message_id": "msg_1", "role": "user", "content": "hi", "created_at": now, "metadata": {}}],
        }

    def delete_conversation(self, conversation_id: str, user_id: str, device_id: str):
        return conversation_id == "conv_1" and user_id == "u" and device_id == "d"

    def memory_overview(self):
        return {"summary": {"fact_count": 0}, "adaptive": {"unavailable": True}}

    def remember_fact(self, text: str):
        return {"success": True, "action": "remember", "message": text, "payload": {}}

    def forget_fact(self, query: str):
        return {"success": True, "action": "forget", "message": query, "payload": {}}

    def clear_memory(self):
        return {"success": True, "action": "clear_all", "message": "ok", "payload": {}}

    def record_feedback(self, **_kwargs):
        return {"success": True, "event": {"rating": "up"}, "unavailable_reason": None}

    def run_research(self, **_kwargs):
        return {"success": True, "report": {"query": "q"}}

    def research_history(self):
        return [{"id": "r1", "query": "q"}]

    def research_url(self, *, url: str):
        return {"success": True, "result": {"url": url}}

    def generate_image(self, **_kwargs):
        return {"success": False, "provider": "comfyui", "result": {"error": "unavailable"}}

    def image_history(self):
        return [{"image_id": "img1"}]

    def delete_image(self, image_id: str):
        return image_id == "img1"

    def providers(self):
        return {"text_providers": [], "image_providers": []}

    def settings(self):
        return {"runtime_config": {}, "chat_profile": {}, "non_secret_keys_only": True}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        from mobile_api.main import get_service

        self.app.dependency_overrides[get_service] = lambda: FakeService()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def test_health_endpoint(self):
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        self.assertIn("status", res.json())

    def test_chat_and_conversation_endpoints(self):
        res = self.client.post("/api/v1/chat", json={"message": "hello"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["conversation_id"], "conv_1")

        listing = self.client.get("/api/v1/conversations")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()), 1)

        detail = self.client.get("/api/v1/conversations/conv_1", params={"user_id": "u", "device_id": "d"})
        self.assertEqual(detail.status_code, 200)

        missing = self.client.get("/api/v1/conversations/missing", params={"user_id": "u", "device_id": "d"})
        self.assertEqual(missing.status_code, 404)

        deletion = self.client.delete("/api/v1/conversations/conv_1", params={"user_id": "u", "device_id": "d"})
        self.assertEqual(deletion.status_code, 200)

    def test_stream_endpoint(self):
        with self.client.stream("POST", "/api/v1/chat/stream", json={"message": "hello"}) as response:
            self.assertEqual(response.status_code, 200)
            body = "".join(response.iter_text())
        self.assertIn('"type": "chunk"', body)
        self.assertIn('"type": "done"', body)

    def test_stream_error_event(self):
        fake = FakeService()
        fake.fail_stream = True
        from mobile_api.main import get_service

        self.app.dependency_overrides[get_service] = lambda: fake
        with self.client.stream("POST", "/api/v1/chat/stream", json={"message": "hello"}) as response:
            self.assertEqual(response.status_code, 200)
            body = "".join(response.iter_text())
        self.assertIn('"type": "error"', body)


if __name__ == "__main__":
    unittest.main()
