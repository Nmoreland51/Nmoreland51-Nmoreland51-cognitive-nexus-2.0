"""The local picture model is downloaded at the revision it was tested with (item 117)."""

from __future__ import annotations

import sys
import types

from modules import image_gen


def _stand_ins(monkeypatch):
    calls = []

    class Pipeline:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls.append((model_id, kwargs))
            return cls()

    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False), float16="float16", float32="float32")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "diffusers", types.SimpleNamespace(StableDiffusionPipeline=Pipeline))
    monkeypatch.setattr(image_gen, "check_local_image_backend", lambda: image_gen.ImageBackendStatus(True, "ok"))
    return calls


def test_the_default_picture_model_is_fetched_at_the_tested_revision(monkeypatch):
    calls = _stand_ins(monkeypatch)
    image_gen.LocalStableDiffusionGenerator()._ensure_initialized()
    model_id, kwargs = calls[0]
    assert model_id == image_gen.DEFAULT_DIFFUSERS_MODEL
    assert kwargs["revision"] == image_gen.DEFAULT_DIFFUSERS_REVISION == "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
    assert kwargs["variant"] == "fp16" and kwargs["safety_checker"] is None


def test_another_model_is_not_held_to_that_revision(monkeypatch):
    calls = _stand_ins(monkeypatch)
    image_gen.LocalStableDiffusionGenerator(model_id="someone/another-model")._ensure_initialized()
    assert "revision" not in calls[0][1]
