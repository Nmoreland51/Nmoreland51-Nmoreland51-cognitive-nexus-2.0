"""Image generation providers, storage, and gallery helpers."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import logging
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

BASE_IMAGE_DIR = Path("data/images")
GENERATED_DIR = BASE_IMAGE_DIR / "generated"
METADATA_DIR = BASE_IMAGE_DIR / "metadata"
LEGACY_IMAGE_DIRS = [
    Path("ai_system/knowledge_bank/images"),
    Path("generated_images"),
]
IMAGE_DIRS = [GENERATED_DIR, *LEGACY_IMAGE_DIRS]

AUTOMATIC1111_URL = "http://127.0.0.1:7860"
COMFYUI_URL = "http://127.0.0.1:8188"
PROVIDER_DETECTION_TIMEOUT = 0.75

STYLE_MODIFIERS = {
    "realistic": "photorealistic, high quality, detailed",
    "artistic": "artistic, painting style, creative",
    "cartoon": "cartoon style, animated, colorful",
    "abstract": "abstract art, modern, creative",
    "vintage": "vintage style, retro, classic",
    "futuristic": "futuristic, sci-fi, modern technology",
    "minimalist": "minimalist, clean, simple",
    "dramatic": "dramatic lighting, cinematic, high contrast",
}


@dataclass
class ImageBackendStatus:
    available: bool
    message: str
    device: str = "unknown"


@dataclass
class ImageGenerationRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 512
    steps: int = 25
    cfg_scale: float = 7.0
    seed: int | None = None
    num_images: int = 1
    provider: str = "auto"
    model: str = ""
    style: str = "realistic"
    save_outputs: bool = True


def ensure_image_dirs() -> dict[str, str]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    for directory in LEGACY_IMAGE_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "base": str(BASE_IMAGE_DIR),
        "generated": str(GENERATED_DIR),
        "metadata": str(METADATA_DIR),
    }


def slugify_text(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return slug[:max_len] or "image"


def enhance_prompt(prompt: str, style: str) -> str:
    modifier = STYLE_MODIFIERS.get(style, "")
    if not modifier:
        return prompt
    return f"{prompt}, {modifier}"


def _provider(
    name: str,
    label: str,
    available: bool,
    implemented: bool,
    message: str,
    url: str | None = None,
    model: str = "",
    device: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "available": available,
        "implemented": implemented,
        "message": message,
        "url": url,
        "model": model,
        "device": device,
    }


def check_local_image_backend() -> ImageBackendStatus:
    """Detect the optional local Diffusers backend used by the legacy app."""

    missing = [
        package
        for package in ("torch", "diffusers", "PIL")
        if importlib.util.find_spec(package) is None
    ]
    if missing:
        return ImageBackendStatus(
            available=False,
            message=f"Local Diffusers backend unavailable. Missing: {', '.join(missing)}",
        )

    return ImageBackendStatus(
        available=True,
        message="Local Diffusers Stable Diffusion packages are installed.",
        device="detected at generation time",
    )


def detect_image_providers() -> list[dict[str, Any]]:
    """Detect image-generation backends without loading heavy model weights."""

    providers: list[dict[str, Any]] = []

    try:
        response = requests.get(f"{AUTOMATIC1111_URL}/sdapi/v1/options", timeout=PROVIDER_DETECTION_TIMEOUT)
        if response.ok:
            data = response.json()
            providers.append(
                _provider(
                    name="automatic1111",
                    label="Automatic1111 API",
                    available=True,
                    implemented=True,
                    message="Automatic1111 Stable Diffusion API is available.",
                    url=AUTOMATIC1111_URL,
                    model=str(data.get("sd_model_checkpoint", "")),
                )
            )
        else:
            providers.append(
                _provider(
                    name="automatic1111",
                    label="Automatic1111 API",
                    available=False,
                    implemented=True,
                    message=f"Automatic1111 returned HTTP {response.status_code}.",
                    url=AUTOMATIC1111_URL,
                )
            )
    except Exception as exc:
        providers.append(
            _provider(
                name="automatic1111",
                label="Automatic1111 API",
                available=False,
                implemented=True,
                message=f"Automatic1111 is not reachable: {exc}",
                url=AUTOMATIC1111_URL,
            )
        )

    try:
        response = requests.get(COMFYUI_URL, timeout=PROVIDER_DETECTION_TIMEOUT)
        if response.ok or response.status_code in (200, 404):
            providers.append(
                _provider(
                    name="comfyui",
                    label="ComfyUI API",
                    available=True,
                    implemented=False,
                    message="ComfyUI is reachable, but no workflow integration is configured yet.",
                    url=COMFYUI_URL,
                )
            )
        else:
            providers.append(
                _provider(
                    name="comfyui",
                    label="ComfyUI API",
                    available=False,
                    implemented=False,
                    message=f"ComfyUI returned HTTP {response.status_code}.",
                    url=COMFYUI_URL,
                )
            )
    except Exception as exc:
        providers.append(
            _provider(
                name="comfyui",
                label="ComfyUI API",
                available=False,
                implemented=False,
                message=f"ComfyUI is not reachable: {exc}",
                url=COMFYUI_URL,
            )
        )

    local_status = check_local_image_backend()
    providers.append(
        _provider(
            name="diffusers_local",
            label="Local Diffusers",
            available=local_status.available,
            implemented=True,
            message=local_status.message,
            model="runwayml/stable-diffusion-v1-5",
            device=local_status.device,
        )
    )

    return providers


def detect_image_provider() -> dict[str, Any]:
    """Return the best currently usable provider."""

    for provider in detect_image_providers():
        if provider.get("available") and provider.get("implemented"):
            return provider
    return _provider(
        name="none",
        label="No image provider",
        available=False,
        implemented=False,
        message=(
            "No image generation provider is available. Start Automatic1111 at "
            "http://127.0.0.1:7860 or install the optional Diffusers backend."
        ),
    )


def _validate_request(req: ImageGenerationRequest) -> None:
    if not req.prompt.strip():
        raise ValueError("Image prompt is required.")
    if req.width < 128 or req.height < 128:
        raise ValueError("Width and height must be at least 128 pixels.")
    if req.width > 2048 or req.height > 2048:
        raise ValueError("Width and height must be 2048 pixels or less.")
    if req.steps < 1 or req.steps > 150:
        raise ValueError("Steps must be between 1 and 150.")
    if req.num_images < 1 or req.num_images > 4:
        raise ValueError("Number of images must be between 1 and 4.")


def generate_with_automatic1111(req: ImageGenerationRequest) -> list[Any]:
    from PIL import Image

    payload = {
        "prompt": enhance_prompt(req.prompt, req.style),
        "negative_prompt": req.negative_prompt,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "width": req.width,
        "height": req.height,
        "seed": req.seed if req.seed is not None else -1,
        "batch_size": req.num_images,
    }
    if req.model:
        payload["override_settings"] = {"sd_model_checkpoint": req.model}

    response = requests.post(
        f"{AUTOMATIC1111_URL}/sdapi/v1/txt2img",
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()

    images = []
    for encoded in data.get("images", []):
        raw = base64.b64decode(encoded.split(",", 1)[-1])
        images.append(Image.open(io.BytesIO(raw)).convert("RGB"))

    if not images:
        raise RuntimeError("Automatic1111 returned no images.")

    return images


class LocalStableDiffusionGenerator:
    """Lazy local image generator based on Diffusers."""

    def __init__(self, model_id: str = "runwayml/stable-diffusion-v1-5") -> None:
        ensure_image_dirs()
        self.model_id = model_id
        self.pipe = None
        self.device = "unknown"
        self._initialized = False

    def _ensure_initialized(self, model_id: str | None = None) -> None:
        requested_model = model_id or self.model_id
        if self._initialized and requested_model == self.model_id:
            return

        status = check_local_image_backend()
        if not status.available:
            raise RuntimeError(status.message)

        import torch
        from diffusers import StableDiffusionPipeline

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = requested_model

        if self.device == "cuda":
            self.pipe = StableDiffusionPipeline.from_pretrained(
                self.model_id,
                torch_dtype=torch.float16,
                safety_checker=None,
                requires_safety_checker=False,
            ).to(self.device)
            self.pipe.enable_attention_slicing()
        else:
            self.pipe = StableDiffusionPipeline.from_pretrained(
                self.model_id,
                safety_checker=None,
                requires_safety_checker=False,
            )

        self._initialized = True

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        width: int = 512,
        height: int = 512,
        style: str = "realistic",
        seed: Optional[int] = None,
        steps: int = 20,
        guidance_scale: float = 7.5,
        num_images: int = 1,
        model: str = "",
        save_outputs: bool = True,
    ) -> Dict[str, Any]:
        req = ImageGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=guidance_scale,
            seed=seed,
            num_images=num_images,
            provider="diffusers_local",
            model=model or self.model_id,
            style=style,
            save_outputs=save_outputs,
        )
        result = generate_with_diffusers(req, generator=self)
        if not result["success"]:
            raise RuntimeError(result["error"])
        first_saved = result["saved"][0] if result["saved"] else {}
        return {
            "image": result["images"][0],
            "metadata": first_saved,
            "filepath": first_saved.get("file_path"),
            "images": result["images"],
            "saved": result["saved"],
        }


def generate_with_diffusers(
    req: ImageGenerationRequest,
    generator: LocalStableDiffusionGenerator | None = None,
) -> dict[str, Any]:
    import torch

    generator = generator or LocalStableDiffusionGenerator(model_id=req.model or "runwayml/stable-diffusion-v1-5")
    generator._ensure_initialized(req.model or None)
    if generator.pipe is None:
        raise RuntimeError("Diffusers pipeline did not initialize.")

    images = []
    for index in range(req.num_images):
        seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
        if req.seed is not None and req.num_images > 1:
            seed = req.seed + index
        torch_generator = torch.Generator(device=generator.device).manual_seed(seed)
        result = generator.pipe(
            enhance_prompt(req.prompt, req.style),
            negative_prompt=req.negative_prompt or None,
            width=req.width,
            height=req.height,
            num_inference_steps=req.steps,
            guidance_scale=req.cfg_scale,
            generator=torch_generator,
        )
        images.append(result.images[0])

    return _package_generation_result(req, images, "diffusers_local", generator.model_id, generator.device)


def _base_filename(metadata: dict[str, Any], index: int) -> str:
    timestamp = metadata.get("timestamp_file") or datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify_text(metadata.get("prompt", "image"))
    return f"{timestamp}_{slug}_{index:03d}"


def save_generated_image(image: Any, metadata: dict[str, Any], index: int = 1) -> str:
    ensure_image_dirs()
    path = GENERATED_DIR / f"{_base_filename(metadata, index)}.png"
    image.save(path, "PNG")
    return str(path)


def save_generation_metadata(metadata: dict[str, Any], index: int = 1) -> str:
    ensure_image_dirs()
    path = METADATA_DIR / f"{_base_filename(metadata, index)}.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _package_generation_result(
    req: ImageGenerationRequest,
    images: list[Any],
    provider_name: str,
    model_name: str = "",
    device: str = "",
) -> dict[str, Any]:
    timestamp = datetime.now()
    timestamp_file = timestamp.strftime("%Y%m%d_%H%M%S")
    saved = []

    for index, image in enumerate(images, start=1):
        metadata = {
            **asdict(req),
            "timestamp": timestamp.isoformat(),
            "timestamp_file": timestamp_file,
            "provider": provider_name,
            "model": model_name or req.model,
            "device": device,
            "index": index,
            "status": "success",
            "error": None,
        }
        if req.save_outputs:
            image_path = save_generated_image(image, metadata, index)
            metadata["file_path"] = image_path
            metadata["filename"] = Path(image_path).name
            metadata_path = str(METADATA_DIR / f"{_base_filename(metadata, index)}.json")
            metadata["metadata_path"] = metadata_path
            Path(metadata_path).write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            metadata["file_path"] = None
            metadata["filename"] = None
            metadata["metadata_path"] = None
        saved.append(metadata)

    return {
        "success": True,
        "provider": provider_name,
        "images": images,
        "saved": saved,
        "error": None,
    }


def generate_images(req: ImageGenerationRequest) -> dict[str, Any]:
    """Generate images with the selected provider and save outputs when enabled."""

    ensure_image_dirs()
    try:
        _validate_request(req)
    except Exception as exc:
        return {"success": False, "provider": req.provider, "images": [], "saved": [], "error": str(exc)}

    providers = detect_image_providers()
    provider_name = req.provider

    if provider_name == "auto":
        selected = next(
            (provider for provider in providers if provider.get("available") and provider.get("implemented")),
            None,
        )
    else:
        selected = next((provider for provider in providers if provider.get("name") == provider_name), None)

    if not selected or not selected.get("available"):
        return {
            "success": False,
            "provider": provider_name,
            "images": [],
            "saved": [],
            "error": (
                "No image generation provider is available. Start Automatic1111 with its API "
                "enabled, or install the optional local Diffusers dependencies."
            ),
        }

    if not selected.get("implemented"):
        return {
            "success": False,
            "provider": selected.get("name"),
            "images": [],
            "saved": [],
            "error": selected.get("message") or f"Provider {selected.get('label')} is not implemented.",
        }

    try:
        if selected["name"] == "automatic1111":
            images = generate_with_automatic1111(req)
            return _package_generation_result(
                req,
                images,
                "automatic1111",
                req.model or selected.get("model", ""),
            )
        if selected["name"] == "diffusers_local":
            return generate_with_diffusers(req)
    except Exception as exc:
        logger.exception("Image generation failed with provider %s", selected.get("name"))
        return {
            "success": False,
            "provider": selected.get("name"),
            "images": [],
            "saved": [],
            "error": str(exc),
        }

    return {
        "success": False,
        "provider": selected.get("name"),
        "images": [],
        "saved": [],
        "error": f"Provider {selected.get('label')} is not supported yet.",
    }


def load_image_metadata(image_path: Path) -> Dict[str, Any]:
    metadata_path = image_path.with_suffix(".json")
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_generated_images(limit: int = 50) -> list[dict[str, Any]]:
    return list_generated_images(limit=limit)


def _gallery_item_from_metadata(metadata_path: Path) -> dict[str, Any] | None:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load image metadata %s: %s", metadata_path, exc)
        return None

    raw_path = metadata.get("file_path")
    image_path = Path(raw_path) if raw_path else GENERATED_DIR / metadata_path.with_suffix(".png").name
    if not image_path.exists():
        return None

    stat = image_path.stat()
    return {
        "path": image_path,
        "name": image_path.name,
        "modified": stat.st_mtime,
        "size": stat.st_size,
        "metadata": metadata,
    }


def list_generated_images(limit: int = 100) -> List[Dict[str, Any]]:
    """List generated images from new and legacy output folders."""

    ensure_image_dirs()
    images: list[dict[str, Any]] = []
    seen: set[str] = set()

    for metadata_path in sorted(METADATA_DIR.glob("*.json"), reverse=True):
        item = _gallery_item_from_metadata(metadata_path)
        if item is None:
            continue
        key = str(item["path"].resolve())
        seen.add(key)
        images.append(item)

    for directory in IMAGE_DIRS:
        if not directory.exists():
            continue
        for path in directory.glob("*.png"):
            key = str(path.resolve())
            if key in seen:
                continue
            stat = path.stat()
            images.append(
                {
                    "path": path,
                    "name": path.name,
                    "modified": stat.st_mtime,
                    "size": stat.st_size,
                    "metadata": load_image_metadata(path),
                }
            )
            seen.add(key)

    images.sort(key=lambda item: item["modified"], reverse=True)
    return images[:limit]
