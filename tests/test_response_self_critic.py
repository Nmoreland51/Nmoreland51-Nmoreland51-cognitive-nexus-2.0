import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from modules.response_self_critic import (
    build_self_critic_prompt_hints,
    evaluate_response_self_critic,
    store_self_critic_observation,
)


class ResponseSelfCriticTests(unittest.TestCase):
    def test_detects_customer_support_tone_without_storing_text(self):
        result = evaluate_response_self_critic(
            user_message="it's going good",
            answer="It's great to hear that things are going well for you! What's been a highlight of your day?",
            plan=SimpleNamespace(intent="conversation_followup"),
        )

        self.assertIn("customer_support_tone", result.observations)
        self.assertLess(result.scores["naturalness"], 1.0)
        self.assertFalse(result.stored_response_text)

    def test_store_keeps_only_abstract_observations_and_builds_hints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "response_preferences.json"
            path.write_text(json.dumps({"weights": {"brevity": 0.2}, "samples": 3}), encoding="utf-8")
            result = evaluate_response_self_critic(
                user_message="it's going good",
                answer="It's great to hear that things are going well for you! What's been a highlight of your day?",
                plan=SimpleNamespace(intent="conversation_followup"),
            )

            critic = store_self_critic_observation(result, path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload).lower()

            self.assertEqual(payload["weights"]["brevity"], 0.2)
            self.assertEqual(critic["samples"], 1)
            self.assertFalse(critic["stores_response_text"])
            self.assertIn("customer_support_tone", critic["observation_counts"])
            self.assertNotIn("great to hear", serialized)
            self.assertNotIn("highlight of your day", serialized)
            self.assertTrue(build_self_critic_prompt_hints(intent="conversation_followup", path=path))


if __name__ == "__main__":
    unittest.main()
