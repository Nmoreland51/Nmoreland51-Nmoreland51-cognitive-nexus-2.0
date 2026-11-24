"""Secrets are kept out of what the app writes down for itself (item 110).

Every key and token here is made up and assembled when the test runs, so that this file does not
itself look like it holds one (tools/check_repo_hygiene.py scans the repository for them).
"""

from __future__ import annotations

import json
import logging
import sys
import zipfile
from pathlib import Path

import pytest

from modules import event_log, redaction
from modules.redaction import redact, redact_data

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import check_repo_hygiene as hygiene  # noqa: E402

OPENAI = "sk-" + "Xa9" * 16
ANTHROPIC = "sk-ant-" + "Qz7_" * 8
GITHUB = "ghp_" + "Ab1Cd2Ef3Gh4" * 3
EXAMPLES = {
    "OpenAI API key": OPENAI,
    "Anthropic API key": ANTHROPIC,
    "GitHub token": GITHUB,
    "AWS access key": "AKIA" + "QWERTYUI12345678",
    "Google API key": "AIza" + "Sy" + "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6R",
    "Slack token": "xoxb-" + "1234567890-" + "abcdefghijklmnop",
    "Hugging Face token": "hf_" + "AbCdEfGhIjKl" * 3,
    "private key block": "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA " + "PRIVATE KEY-----",
    "hard-coded credential": 'api_key = "' + "Zr8Lw2Nx5Qp7Ts4Vy1Bm6Kc9" + '"',
}


@pytest.fixture(autouse=True)
def nothing_remembered(monkeypatch):
    monkeypatch.setattr(redaction, "_remembered", {})


# ---- what is taken out ----------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(EXAMPLES))
def test_everything_the_repository_check_looks_for_is_also_kept_out_of_records(label):
    example = EXAMPLES[label]
    assert hygiene.SECRET_PATTERNS[label].search(example), "the example has to be one the repository check finds"
    cleaned = redact(f"while calling the service: {example} (status 401)")
    assert "[redacted:" in cleaned
    assert not any(pattern.search(cleaned) for pattern in hygiene.SECRET_PATTERNS.values()), cleaned


@pytest.mark.parametrize(
    "text, kept, gone",
    [
        ("GET https://api.example.org/v1/search?q=bridges&api_key=Kq8mN2pL5xR7&page=2", "q=bridges", "Kq8mN2pL5xR7"),
        ("connecting to https://owner:Hunter22secret@searx.home.lan/search", "searx.home.lan", "Hunter22secret"),
        ("Authorization: Bearer " + OPENAI, "Authorization: Bearer", OPENAI),
        ("header Authorization: Basic eC1hY2Nlc3MtdG9rZW46dGVzdA==", "Basic", "eC1hY2Nlc3MtdG9rZW46dGVzdA=="),
        ("settings {'brave_api_key': 'BSAq7Lk2mNp9XyZ', 'model': 'dolphin3:8b'}", "dolphin3:8b", "BSAq7Lk2mNp9XyZ"),
        ("login failed: password=Tr0ub4dor&3 for owner", "for owner", "Tr0ub4dor"),
    ],
)
def test_keys_in_addresses_headers_and_named_values_are_taken_out(text, kept, gone):
    cleaned = redact(text)
    assert gone not in cleaned and kept in cleaned, cleaned


@pytest.mark.parametrize(
    "text",
    [
        "max_tokens: 1000000000",
        "token_count=123456789",
        "Basic understanding of the problem comes first.",
        "The token was not accepted: it may have expired or been revoked.",
        "password: abc",
        "tokens: 4096, num_ctx: 8192",
        "The bridge opened in 1962 after four years of construction.",
    ],
)
def test_ordinary_text_is_left_as_it_is(text):
    assert redact(text) == text


def test_this_machines_own_secrets_are_taken_out_by_value(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "BSAuNlikeAnyPattern42")
    monkeypatch.setenv("OLLAMA_MAX_TOKENS", "1000000000")  # a limit, not a secret
    cleaned = redact("search failed with key BSAuNlikeAnyPattern42 after 1000000000 tries")
    assert cleaned == "search failed with key [redacted: BRAVE_SEARCH_API_KEY] after 1000000000 tries"


def test_a_credential_the_app_has_read_is_taken_out_from_then_on():
    redaction.remember("plainlookingvalue123", "Example credential")
    assert redact("sent plainlookingvalue123") == "sent [redacted: Example credential]"


def test_the_account_store_remembers_what_it_hands_out(monkeypatch):
    from modules import accounts

    monkeypatch.setenv("OPENAI_API_KEY", "an-unshaped-but-real-key-123")
    try:
        accounts.credential("openai", "chat")
    except accounts.AccountError:
        pytest.skip("no OpenAI service is defined with that variable")
    assert "an-unshaped-but-real-key-123" not in redact("request with an-unshaped-but-real-key-123")


def test_structures_are_redacted_throughout_and_secret_named_fields_lose_their_value():
    cleaned = redact_data({"openai_api_key": "notashape12345", "max_tokens": 4096, "steps": ["ok", "Bearer " + OPENAI], "nested": {"token": "abcdefgh123"}})
    assert cleaned == {
        "openai_api_key": "[redacted: openai_api_key]",
        "max_tokens": 4096,
        "steps": ["ok", "Bearer [redacted: OpenAI API key]"],
        "nested": {"token": "[redacted: token]"},
    }


# ---- where it is applied ----------------------------------------------------------------------------


def test_the_log_file_never_receives_a_key_even_in_a_traceback(tmp_path):
    logger = logging.getLogger("test_redaction.file")
    logger.propagate = False
    handler = logging.FileHandler(tmp_path / "app.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        assert redaction.install_log_redaction(logger) == 1
        assert redaction.install_log_redaction(logger) == 0  # not wrapped twice
        logger.warning("calling with %s", GITHUB)
        try:
            raise RuntimeError(f"401 for https://api.example.org/?key={OPENAI}")
        except RuntimeError:
            logger.exception("request failed")
    finally:
        handler.close()
        logger.removeHandler(handler)
    written = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert GITHUB not in written and OPENAI not in written
    assert "WARNING calling with [redacted: GitHub token]" in written and "RuntimeError" in written


def test_the_core_turns_redaction_on_for_the_log(monkeypatch):
    from modules import nexus_core

    calls = []
    monkeypatch.setattr(nexus_core.redaction, "install_log_redaction", lambda *args: calls.append(args) or 0)
    nexus_core.NexusCore()
    assert calls == [()]


def test_the_event_log_never_receives_a_key():
    event_log.record_event("error", f"push failed for https://x-access-token:{GITHUB}@github.com/o/r.git", detail=f"Bearer {OPENAI}")
    last = json.loads(event_log.EVENT_LOG_FILE.read_text(encoding="utf-8").splitlines()[-1])
    assert GITHUB not in json.dumps(last) and OPENAI not in json.dumps(last)
    assert "github.com/o/r.git" in last["message"]


def test_the_answer_checks_never_receive_a_key():
    from modules.nexus_config import LOG_DIR
    from modules.response_verifier import VerificationResult, log_verification

    log_verification(VerificationResult(risk_level="medium", issues=[f"the answer quotes {ANTHROPIC}"]), "test")
    last = (LOG_DIR / "uncertainty.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    assert ANTHROPIC not in last and "[redacted: Anthropic API key]" in last


def test_picture_metadata_never_receives_a_key():
    from PIL import Image

    from modules import image_gen

    request = image_gen.ImageGenerationRequest(prompt=f"a lighthouse at dusk {OPENAI}", save_outputs=True)
    result = image_gen._package_generation_result(request, [Image.new("RGB", (8, 8))], "diffusers_local", "stand-in-model")
    saved = Path(result["saved"][0]["metadata_path"]).read_text(encoding="utf-8")
    assert OPENAI not in saved and "a lighthouse at dusk" in saved


def _png_with_text(path: Path, **texts: str) -> None:
    from PIL import Image, PngImagePlugin

    info = PngImagePlugin.PngInfo()
    for key, value in texts.items():
        info.add_text(key, value)
    Image.new("RGB", (8, 8), "navy").save(path, "PNG", pnginfo=info)


def test_a_comfyui_picture_loses_the_key_its_workflow_carried_and_keeps_the_workflow(tmp_path):
    from PIL import Image

    workflow = json.dumps({"3": {"class_type": "SomeApiNode", "inputs": {"api_key": OPENAI, "seed": 5}}})
    path = tmp_path / "ComfyUI_00001_.png"
    _png_with_text(path, prompt=workflow)
    assert redaction.redact_png_text(path) is True
    with Image.open(path) as image:
        kept = json.loads(image.text["prompt"])
    assert kept["3"]["inputs"] == {"api_key": "[redacted: OpenAI API key]", "seed": 5}


def test_a_picture_without_secrets_is_left_byte_for_byte(tmp_path):
    path = tmp_path / "clean.png"
    _png_with_text(path, prompt=json.dumps({"3": {"inputs": {"seed": 5}}}))
    before = path.read_bytes()
    assert redaction.redact_png_text(path) is False
    assert path.read_bytes() == before


def test_the_apps_own_keys_never_reach_the_model(monkeypatch):
    """The prompts the app builds hold no key or token of its own, whatever the settings carry."""

    from tests.test_owner_control import World

    secrets = {"OPENAI_API_KEY": OPENAI, "ANTHROPIC_API_KEY": ANTHROPIC, "COGNITIVE_NEXUS_GITHUB_TOKEN": GITHUB, "BRAVE_SEARCH_API_KEY": "BSAuNlikeAnyPattern42"}
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    world = World()
    world.ask("What should I call my new boat?", openai_api_key=OPENAI, anthropic_api_key=ANTHROPIC, github_token=GITHUB)
    sent = " ".join([world.requests[0].system_prompt, world.requests[0].prompt, *world.judge_prompts])
    assert not any(value in sent for value in secrets.values())


# ---- the scan for files outside the repository ----------------------------------------------------------


def test_a_phone_build_or_an_old_log_can_be_scanned(tmp_path):
    archive = tmp_path / "app-release.apk"
    with zipfile.ZipFile(archive, "w") as built:
        built.writestr("classes.dex", b"\x00\x01binary\x28" + GITHUB.encode() + b"\x00")  # a dex string follows its length
        built.writestr("res/values/strings.xml", "<string name='title'>Cognitive Nexus</string>")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "old.log").write_text(f"2026-11-01 INFO calling with {OPENAI}\n", encoding="utf-8")
    (logs / "clean.log").write_text("nothing to see\n", encoding="utf-8")

    problems, looked_at = hygiene.scan_paths([str(archive), str(logs), str(tmp_path / "missing")])
    assert looked_at == 4
    assert any("app-release.apk!classes.dex" in problem and "GitHub token" in problem for problem in problems)
    assert any("old.log:1: looks like a OpenAI API key" in problem for problem in problems)
    assert any(problem.endswith("missing: not found") for problem in problems)
    assert not any("clean.log" in problem or "strings.xml" in problem for problem in problems)
