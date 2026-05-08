import base64

from cognitive_nexus.image_generation_profiles import (
    HOSTED_BUDGET_MODE,
    HOSTED_PREMIUM_MODE,
    LOCAL_PRIVATE_MODE,
    build_hosted_image_request,
    extract_hosted_image_response_payload,
    get_image_generation_mode_profile,
)


class FakeImageItem:
    def __init__(self, *, b64_json=None, revised_prompt=None, url=None):
        self.b64_json = b64_json
        self.revised_prompt = revised_prompt
        self.url = url


class FakeImageResponse:
    def __init__(self, data, request_id="req_test"):
        self.data = data
        self._request_id = request_id


def test_local_profile_keeps_local_model():
    profile = get_image_generation_mode_profile(LOCAL_PRIVATE_MODE)
    assert profile["provider"] == "local"
    assert profile["model"] == "runwayml/stable-diffusion-v1-5"
    assert profile["supports_seed"] is True


def test_hosted_profiles_use_configured_models():
    budget_profile = get_image_generation_mode_profile(
        HOSTED_BUDGET_MODE,
        hosted_budget_model="budget-model",
        hosted_premium_model="premium-model",
    )
    premium_profile = get_image_generation_mode_profile(
        HOSTED_PREMIUM_MODE,
        hosted_budget_model="budget-model",
        hosted_premium_model="premium-model",
    )

    assert budget_profile["model"] == "budget-model"
    assert premium_profile["model"] == "premium-model"
    assert premium_profile["hosted_quality"] == "high"


def test_build_hosted_request_adds_quality_only_when_needed():
    budget_profile = get_image_generation_mode_profile(HOSTED_BUDGET_MODE)
    premium_profile = get_image_generation_mode_profile(HOSTED_PREMIUM_MODE)

    budget_request = build_hosted_image_request(budget_profile, prompt="city skyline", size="1024x1024")
    premium_request = build_hosted_image_request(premium_profile, prompt="city skyline", size="1024x1024")

    assert "quality" not in budget_request
    assert premium_request["quality"] == "high"


def test_extract_hosted_payload_decodes_base64_and_request_id():
    raw_bytes = b"fake-image-bytes"
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    response = FakeImageResponse(
        [FakeImageItem(b64_json=encoded, revised_prompt="better prompt")],
        request_id="req_123",
    )

    payload = extract_hosted_image_response_payload(response)

    assert payload["image_bytes"] == raw_bytes
    assert payload["revised_prompt"] == "better prompt"
    assert payload["request_id"] == "req_123"
