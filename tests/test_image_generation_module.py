import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from modules import image_gen
from modules.image_gen import (
    ImageGenerationRequest,
    detect_image_provider,
    ensure_image_dirs,
    list_generated_images,
    save_generated_image,
    save_generation_metadata,
    slugify_text,
)


class ImageGenerationModuleTests(unittest.TestCase):
    def test_slugify_text(self):
        self.assertEqual(slugify_text("Cyberpunk Wolf!!"), "cyberpunk_wolf")
        self.assertEqual(slugify_text(""), "image")

    def test_detect_image_provider_returns_status_dict(self):
        status = detect_image_provider()
        self.assertIn("available", status)
        self.assertIn("message", status)
        self.assertIn("label", status)

    def test_save_generated_image_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_base = image_gen.BASE_IMAGE_DIR
            original_generated = image_gen.GENERATED_DIR
            original_metadata = image_gen.METADATA_DIR
            original_dirs = image_gen.IMAGE_DIRS
            try:
                image_gen.BASE_IMAGE_DIR = Path(temp_dir) / "images"
                image_gen.GENERATED_DIR = image_gen.BASE_IMAGE_DIR / "generated"
                image_gen.METADATA_DIR = image_gen.BASE_IMAGE_DIR / "metadata"
                image_gen.IMAGE_DIRS = [image_gen.GENERATED_DIR]

                dirs = ensure_image_dirs()
                self.assertTrue(Path(dirs["generated"]).exists())
                self.assertTrue(Path(dirs["metadata"]).exists())

                metadata = {
                    "timestamp_file": "20260508_120000",
                    "prompt": "test prompt",
                    "provider": "unit",
                    "status": "success",
                }
                image = Image.new("RGB", (32, 32), color="white")
                image_path = save_generated_image(image, metadata, index=1)
                metadata["file_path"] = image_path
                metadata_path = save_generation_metadata(metadata, index=1)

                self.assertTrue(Path(image_path).exists())
                self.assertTrue(Path(metadata_path).exists())
                self.assertEqual(json.loads(Path(metadata_path).read_text())["prompt"], "test prompt")
                self.assertEqual(len(list_generated_images(limit=5)), 1)
            finally:
                image_gen.BASE_IMAGE_DIR = original_base
                image_gen.GENERATED_DIR = original_generated
                image_gen.METADATA_DIR = original_metadata
                image_gen.IMAGE_DIRS = original_dirs

    def test_request_defaults(self):
        req = ImageGenerationRequest(prompt="hello")
        self.assertEqual(req.provider, "auto")
        self.assertEqual(req.num_images, 1)
        self.assertTrue(req.save_outputs)


if __name__ == "__main__":
    unittest.main()
