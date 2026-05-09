import tempfile
import unittest
from pathlib import Path

from modules import comfyui_client
from modules.comfyui_client import ComfyUIClient


class ComfyUIClientTests(unittest.TestCase):
    def test_unavailable_status_is_clean(self):
        client = ComfyUIClient("http://127.0.0.1:9")
        status = client.detect()

        self.assertFalse(status.available)
        self.assertIn("ComfyUI", status.message)

    def test_workflow_prompt_patch(self):
        client = ComfyUIClient("http://127.0.0.1:9")
        workflow = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}, "_meta": {"title": "Positive"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}, "_meta": {"title": "Negative"}},
        }
        patched = client.patch_workflow_text(workflow, "new positive", "new negative")

        self.assertEqual(patched["1"]["inputs"]["text"], "new positive")
        self.assertEqual(patched["2"]["inputs"]["text"], "new negative")

    def test_save_and_list_workflow(self):
        original_dir = comfyui_client.WORKFLOW_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            comfyui_client.WORKFLOW_DIR = Path(tmpdir)
            try:
                client = ComfyUIClient("http://127.0.0.1:9")
                path = client.save_workflow({"1": {"class_type": "Test"}}, "unit")
                self.assertTrue(path.exists())
                self.assertEqual(len(client.list_workflows()), 1)
            finally:
                comfyui_client.WORKFLOW_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
