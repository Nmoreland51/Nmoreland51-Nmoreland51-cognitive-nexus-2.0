"""Shared image generation mode helpers."""

from __future__ import annotations

import base64
from typing import Any, Dict


LOCAL_IMAGE_MODEL_ID = "runwayml/stable-diffusion-v1-5"
LOCAL_PRIVATE_MODE = "local_private"
HOSTED_BUDGET_MODE = "hosted_budget"
HOSTED_PREMIUM_MODE = "hosted_premium"

IMAGE_GENERATION_MODE_ORDER = [
    LOCAL_PRIVATE_MODE,
    HOSTED_BUDGET_MODE,
    HOSTED_PREMIUM_MODE,
]

_BASE_MODE_PROFILES: Dict[str, Dict[str, Any]] = {
    LOCAL_PRIVATE_MODE: {
        "label": "Local (Private)",
        "provider": "local",
        "description": "Runs entirely on this machine. Best for privacy, but more artifact-prone than hosted models.",
        "supported_sizes": ["512x512", "768x768", "1024x1024"],
        "default_size": "512x512",
        "supports_seed": True,
        "uses_local_quality_selector": True,
        "hosted_quality": None,
    },
    HOSTED_BUDGET_MODE: {
        "label": "Hosted Budget",
        "provider": "openai",
        "description": "Uses OpenAI's lighter image model for better polish at lower cost. Prompts and generated images leave this device.",
        "supported_sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "default_size": "1024x1024",
        "supports_seed": False,
        "uses_local_quality_selector": False,
        "hosted_quality": None,
    },
    HOSTED_PREMIUM_MODE: {
        "label": "Hosted Premium",
        "provider": "openai",
        "description": "Uses OpenAI's strongest hosted image profile for the best artifact resistance. Prompts and generated images leave this device.",
        "supported_sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "default_size": "1024x1024",
        "supports_seed": False,
        "uses_local_quality_selector": False,
        "hosted_quality": "high",
    },
}


def get_image_generation_mode_profile(
    mode: str,
    *,
    hosted_budget_model: str = "gpt-image-1-mini",
    hosted_premium_model: str = "gpt-image-1.5",
) -> Dict[str, Any]:
    if mode not in _BASE_MODE_PROFILES:
        raise ValueError(f"Unknown image generation mode: {mode}")

    profile = dict(_BASE_MODE_PROFILES[mode])
    if mode == LOCAL_PRIVATE_MODE:
        profile["model"] = LOCAL_IMAGE_MODEL_ID
    elif mode == HOSTED_BUDGET_MODE:
        profile["model"] = hosted_budget_model
    else:
        profile["model"] = hosted_premium_model
    profile["mode"] = mode
    return profile


def build_hosted_image_request(profile: Dict[str, Any], *, prompt: str, size: str) -> Dict[str, Any]:
    if profile.get("provider") != "openai":
        raise ValueError("Hosted image requests can only be built for hosted profiles.")

    request = {
        "model": profile["model"],
        "prompt": prompt,
        "size": size,
        "output_format": "png",
    }
    hosted_quality = profile.get("hosted_quality")
    if hosted_quality:
        request["quality"] = hosted_quality
    return request


def extract_hosted_image_response_payload(response: Any) -> Dict[str, Any]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        raise ValueError("Hosted image response did not include image data.")

    image_item = data[0]

    def get_attr_or_key(item: Any, key: str) -> Any:
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    b64_json = get_attr_or_key(image_item, "b64_json")
    image_url = get_attr_or_key(image_item, "url")
    revised_prompt = get_attr_or_key(image_item, "revised_prompt")

    if not b64_json and not image_url:
        raise ValueError("Hosted image response did not include image bytes or a URL.")

    request_id = (
        getattr(response, "_request_id", None)
        or getattr(response, "request_id", None)
        or (response.get("_request_id") if isinstance(response, dict) else None)
    )

    return {
        "image_bytes": base64.b64decode(b64_json) if b64_json else None,
        "image_url": image_url,
        "revised_prompt": revised_prompt,
        "request_id": request_id,
    }
