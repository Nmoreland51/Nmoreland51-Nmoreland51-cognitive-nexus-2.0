import unittest

from response_speed_eval import evaluate_prompt, target_for


class ResponseSpeedEvalTests(unittest.TestCase):
    def test_dry_run_speed_eval_returns_rows_without_model_call(self):
        row = evaluate_prompt("sup", dry_run=True)

        self.assertEqual(row["request_type"], "casual_chat")
        self.assertEqual(row["mode"], "short")
        self.assertEqual(row["provider"], "dry_run")
        self.assertEqual(row["check"], "PASS")

    def test_speed_targets_match_normal_chat_budget(self):
        self.assertEqual(target_for("casual_chat", "short").seconds, 9.0)
        self.assertEqual(target_for("simple_fact", "short").seconds, 9.0)
        self.assertEqual(target_for("debugging", "surgeon").seconds, 15.0)


if __name__ == "__main__":
    unittest.main()
