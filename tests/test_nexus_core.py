import unittest

from modules.chat_profile import ChatProfile
from modules.nexus_core import NexusCore
from nexus_router import RouterConfig


class NexusCoreTests(unittest.TestCase):
    def test_core_fallback_chat_response(self):
        core = NexusCore()
        settings = {
            "chat_profile": ChatProfile(enabled=False),
            "router_config": RouterConfig(default_model="", enabled=True),
            "provider_order": ["fallback"],
            "selected_model": "",
            "base_url": "",
            "use_memory": False,
            "use_knowledge_for_chat": False,
            "use_web_for_chat": False,
            "show_sources": True,
            "generation_timeout": 5.0,
            "max_context_chars": 4000,
            "recent_message_limit": 4,
        }
        answer = core.generate_chat_response("hello", [], settings)

        self.assertIn("Fallback:", answer)
        self.assertIn("provider", core.last_provider_result)

    def test_status_snapshot_contains_comfyui_and_providers(self):
        core = NexusCore()
        snapshot = core.status_snapshot(["fallback"])

        self.assertIn("providers", snapshot)
        self.assertIn("comfyui", snapshot)


if __name__ == "__main__":
    unittest.main()
