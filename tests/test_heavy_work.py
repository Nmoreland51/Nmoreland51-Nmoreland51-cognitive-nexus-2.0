"""One picture at a time, room in memory for it, and a picture that can be stopped (items 098, 105).

Everything here runs without a model or an image pipeline: Ollama and the memory reading are
stand-ins. What the real pipeline and the real chat model do on this machine is measured by
tools/picture_memory_check.py (docs/benchmarks/picture_memory*.json).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from modules import heavy_work, image_gen
from modules.image_gen import ImageGenerationRequest
from modules.provider_router import ProviderInfo, ProviderRequest, ProviderRouter

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_MODEL = {"name": "dolphin3:8b", "size_gb": 4.95}


def memory_readings(*values):
    """A stand-in for available_gb() that returns the given values in turn (the last one repeats)."""

    readings = list(values)

    def read():
        return readings.pop(0) if len(readings) > 1 else readings[0]

    return read


# ---- how much a picture needs ----------------------------------------------------------------


def test_the_need_is_the_measured_figure_at_the_measured_sizes_and_grows_beyond():
    assert heavy_work.picture_need_gb(512, 512) == pytest.approx(heavy_work.PICTURE_MEMORY_512_GB)
    assert heavy_work.picture_need_gb(768, 768) == pytest.approx(heavy_work.PICTURE_MEMORY_768_GB)
    assert heavy_work.picture_need_gb(1024, 1024) > heavy_work.PICTURE_MEMORY_768_GB
    assert heavy_work.picture_need_gb(1536, 1536) > heavy_work.picture_need_gb(1024, 1024)
    # Smaller pictures still need the pipeline itself.
    assert heavy_work.picture_need_gb(256, 256) >= 0.8 * heavy_work.PICTURE_MEMORY_512_GB


# ---- making room ----------------------------------------------------------------------------


def test_with_enough_memory_nothing_is_done_and_ollama_is_not_asked():
    def never(*_args):
        raise AssertionError("Ollama should not be asked when memory is enough")

    report = heavy_work.make_room(7.1, memory=memory_readings(20.0), loaded=never, unload=never)
    assert report["short"] is False and report["action"] == "none" and report["note"] == ""


def test_when_memory_is_short_the_chat_model_is_taken_out_and_the_person_is_told():
    unloaded = []
    report = heavy_work.make_room(
        7.1,
        memory=memory_readings(8.4, 13.3),
        loaded=lambda url: [CHAT_MODEL],
        unload=lambda name, url: unloaded.append(name) or True,
    )
    assert unloaded == ["dolphin3:8b"]
    assert report["action"] == "unloaded" and report["unloaded"] == ["dolphin3:8b"]
    assert report["available_after_gb"] == 13.3
    assert "taken out of memory" in report["note"] and "loads again" in report["note"]


def test_the_owner_can_keep_the_chat_model_loaded():
    def never(*_args):
        raise AssertionError("the setting says keep the chat model")

    report = heavy_work.make_room(7.1, policy="keep_chat_model", memory=memory_readings(3.0), loaded=lambda url: [CHAT_MODEL], unload=never)
    assert report["action"] == "kept" and "may be slow" in report["note"]


def test_short_memory_with_no_chat_model_loaded_still_makes_the_picture():
    report = heavy_work.make_room(7.1, memory=memory_readings(3.0), loaded=lambda url: [], unload=lambda *a: True)
    assert report["action"] == "nothing to free" and "made anyway" in report["note"]


def test_when_ollama_does_not_unload_the_note_says_so():
    report = heavy_work.make_room(7.1, memory=memory_readings(3.0), loaded=lambda url: [CHAT_MODEL], unload=lambda *a: False)
    assert report["action"] == "could not free" and "did not take" in report["note"]


def test_an_unknown_setting_means_the_default():
    report = heavy_work.make_room(1.0, policy="something else", memory=memory_readings(50.0))
    assert report["policy"] == heavy_work.DEFAULT_POLICY


# ---- one picture at a time --------------------------------------------------------------------


def test_a_second_picture_waits_for_the_first():
    order = []
    first_in = threading.Event()

    def first():
        with heavy_work.picture_slot(wait_seconds=5):
            first_in.set()
            order.append("first starts")
            time.sleep(0.4)
            order.append("first ends")

    thread = threading.Thread(target=first)
    thread.start()
    first_in.wait(5)
    assert heavy_work.picture_in_progress()
    with heavy_work.picture_slot(wait_seconds=5) as waited:
        order.append("second starts")
    thread.join()
    assert order == ["first starts", "first ends", "second starts"]
    assert waited >= 0.2
    assert not heavy_work.picture_in_progress()


def test_beyond_the_waiting_limit_a_request_is_turned_down_at_once():
    holding, release, waiting_started = threading.Event(), threading.Event(), threading.Event()

    def hold():
        with heavy_work.picture_slot(wait_seconds=5):
            holding.set()
            release.wait(5)

    def wait_in_turn():
        waiting_started.set()
        with heavy_work.picture_slot(wait_seconds=5, max_waiting=1):
            pass

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(5)
    waiter = threading.Thread(target=wait_in_turn)
    waiter.start()
    waiting_started.wait(5)
    time.sleep(0.2)  # the waiter is now counted
    started = time.monotonic()
    with pytest.raises(heavy_work.MachineBusy, match="waiting"):
        with heavy_work.picture_slot(wait_seconds=5, max_waiting=1):
            pass
    assert time.monotonic() - started < 1.0
    release.set()
    holder.join()
    waiter.join()


def test_a_request_that_waits_too_long_is_told_the_machine_is_busy():
    holding, release = threading.Event(), threading.Event()

    def hold():
        with heavy_work.picture_slot(wait_seconds=5):
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(5)
    with pytest.raises(heavy_work.MachineBusy, match="over"):
        with heavy_work.picture_slot(wait_seconds=0.3):
            pass
    release.set()
    holder.join()


def test_a_picture_made_by_another_program_on_this_machine_counts():
    marker = Path(os.environ["COGNITIVE_NEXUS_HOME"]) / "picture-held.txt"
    marker.unlink(missing_ok=True)
    code = (
        "import sys, time; from pathlib import Path; sys.path.insert(0, sys.argv[3]);"
        "from modules import heavy_work\n"
        "with heavy_work.picture_slot(wait_seconds=5):\n"
        "    Path(sys.argv[1]).write_text('held')\n"
        "    time.sleep(float(sys.argv[2]))\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code, str(marker), "2.5", str(REPO_ROOT)], cwd=str(REPO_ROOT))
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.05)
        assert marker.exists(), "the other process never took the slot"
        assert heavy_work.picture_in_progress()
        with pytest.raises(heavy_work.MachineBusy, match="Another program"):
            with heavy_work.picture_slot(wait_seconds=0.3):
                pass
    finally:
        child.wait(30)
    assert child.returncode == 0
    assert not heavy_work.picture_in_progress()
    with heavy_work.picture_slot(wait_seconds=2):
        pass


# ---- chat while a picture is being made -------------------------------------------------------


def test_chat_does_not_wait_when_no_picture_is_being_made():
    def never(*_args):
        raise AssertionError("nothing should be looked up when no picture is being made")

    report = heavy_work.wait_for_room("dolphin3:8b", in_progress=lambda: False, loaded=never, model_size=never, memory=never)
    assert report == {"waited_seconds": 0.0, "reason": ""}


def test_chat_waits_for_the_picture_when_the_model_does_not_fit_beside_it():
    states = [True, True, True, False]
    report = heavy_work.wait_for_room(
        "dolphin3:8b",
        in_progress=lambda: states.pop(0) if len(states) > 1 else states[0],
        memory=memory_readings(2.0),
        loaded=lambda url: [],
        model_size=lambda name, url: 4.6,
        poll_seconds=0.01,
    )
    assert report["reason"] and "waited for the picture" in report["reason"]


@pytest.mark.parametrize(
    "loaded, memory",
    [([CHAT_MODEL], 0.5), ([], 30.0)],
    ids=["model already in memory", "enough memory for both"],
)
def test_chat_goes_ahead_when_it_adds_little(loaded, memory):
    report = heavy_work.wait_for_room(
        "dolphin3:8b", in_progress=lambda: True, memory=memory_readings(memory), loaded=lambda url: loaded, model_size=lambda name, url: 4.6
    )
    assert report["waited_seconds"] == 0.0 and report["reason"] == ""


def test_the_router_records_a_wait_for_a_picture_and_the_load_time(monkeypatch):
    monkeypatch.setattr(heavy_work, "wait_for_room", lambda model, url, **kw: {"waited_seconds": 3.0, "reason": "a picture"})
    router = ProviderRouter({"provider_order": ["ollama"]})
    info = ProviderInfo(name="ollama", available=True, message="ok", models=["llama3.2:3b"], base_url="http://localhost:11434")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield '{"response":"Yo","done":false}'
            yield '{"response":"","done":true,"eval_count":12,"eval_duration":2000000000,"load_duration":4200000000}'

        def json(self):
            return {}

    with patch("modules.provider_router.OLLAMA_SESSION.post", return_value=FakeResponse()):
        text = "".join(router._stream_ollama(ProviderRequest(prompt="hello", model="llama3.2:3b"), info, "llama3.2:3b"))
    assert text == "Yo"
    assert router._last_ollama_throughput["waited_for_picture_seconds"] == 3.0
    assert router._last_ollama_throughput["load_duration_ns"] == 4_200_000_000


def test_loading_the_chat_model_ahead_of_time_is_skipped_while_a_picture_is_made(monkeypatch):
    monkeypatch.setattr(heavy_work, "picture_in_progress", lambda: True)
    router = ProviderRouter({"provider_order": ["ollama"]})
    with patch("modules.provider_router.OLLAMA_SESSION.post", side_effect=AssertionError("no load while a picture is made")):
        assert router.warm_ollama("dolphin3:8b") is False


# ---- stopping a picture -------------------------------------------------------------------------


class FakePipe:
    """Behaves like a diffusers pipeline: steps call callback_on_step_end, and _interrupt skips the rest."""

    def __init__(self):
        self.calls = []
        self._interrupt = False

    def __call__(self, prompt, *, num_inference_steps, callback_on_step_end=None, **kwargs):
        self._interrupt = False
        done = 0
        for step in range(num_inference_steps):
            if self._interrupt:
                continue
            done += 1
            if callback_on_step_end is not None:
                callback_on_step_end(self, step, step, {})
        self.calls.append({"steps_done": done, "callback": callback_on_step_end is not None})
        return types.SimpleNamespace(images=[f"picture {len(self.calls)}"])


class FakeGenerator:
    model_id = "fake-model"
    device = "cpu"

    def __init__(self):
        self.pipe = FakePipe()

    def _ensure_initialized(self, model_id=None):
        return None


@pytest.fixture
def fake_torch(monkeypatch):
    generator = types.SimpleNamespace(manual_seed=lambda seed: None)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(Generator=lambda device: generator))


def test_a_cancelled_picture_stops_between_steps_and_nothing_is_kept(fake_torch):
    cancel = threading.Event()
    stop = heavy_work.PictureStop(cancel=cancel)
    generator = FakeGenerator()
    original = stop.on_step_end

    def cancel_at_step_three(pipe, step, timestep, kwargs):
        if step == 2:
            cancel.set()
        return original(pipe, step, timestep, kwargs)

    stop.on_step_end = cancel_at_step_three  # type: ignore[method-assign]
    request = ImageGenerationRequest(prompt="a lighthouse", steps=20, num_images=2, save_outputs=False)
    with pytest.raises(heavy_work.PictureStopped, match="cancelled"):
        image_gen.generate_with_diffusers(request, generator=generator, stop=stop)
    assert generator.pipe.calls == [{"steps_done": 3, "callback": True}]  # the second picture was never started


def test_a_picture_over_its_time_limit_is_stopped(fake_torch):
    stop = heavy_work.PictureStop(time_limit_seconds=0.0)
    request = ImageGenerationRequest(prompt="a lighthouse", steps=10, save_outputs=False)
    with pytest.raises(heavy_work.PictureStopped, match="time limit"):
        image_gen.generate_with_diffusers(request, generator=FakeGenerator(), stop=stop)


def test_without_a_stop_the_pipeline_is_called_as_before(fake_torch):
    generator = FakeGenerator()
    result = image_gen.generate_with_diffusers(ImageGenerationRequest(prompt="a lighthouse", steps=5, save_outputs=False), generator=generator)
    assert result["success"] and generator.pipe.calls == [{"steps_done": 5, "callback": False}]


# ---- the whole request -------------------------------------------------------------------------


LOCAL_PIPELINE = [{"name": "diffusers_local", "label": "Local Diffusers", "available": True, "implemented": True, "message": "ok"}]


def test_a_local_picture_makes_room_first_and_says_what_it_did(monkeypatch):
    seen = {}
    monkeypatch.setattr(image_gen, "detect_image_providers", lambda: LOCAL_PIPELINE)

    def room(need_gb, *, policy, base_url):
        seen.update(need_gb=need_gb, policy=policy, base_url=base_url)
        return {"action": "unloaded", "note": "Made room first."}

    def make(req, stop=None):
        seen["stop"] = stop
        return {"success": True, "provider": "diffusers_local", "images": [], "saved": [], "error": None}

    monkeypatch.setattr(heavy_work, "make_room", room)
    monkeypatch.setattr(image_gen, "generate_with_diffusers", make)
    result = image_gen.generate_images(
        ImageGenerationRequest(prompt="a lighthouse", width=768, height=768, provider="diffusers_local"),
        memory_policy="keep_chat_model",
        ollama_url="http://ollama.example",
        time_limit_seconds=90,
    )
    assert result["success"] and result["memory"]["note"] == "Made room first."
    assert result["waited_seconds"] == pytest.approx(0.0, abs=0.5)
    assert seen["need_gb"] == heavy_work.picture_need_gb(768, 768)
    assert seen["policy"] == "keep_chat_model" and seen["base_url"] == "http://ollama.example"
    assert isinstance(seen["stop"], heavy_work.PictureStop) and seen["stop"].time_limit_seconds == 90


def test_a_busy_machine_is_said_as_such_not_as_a_failure_of_the_pipeline(monkeypatch):
    monkeypatch.setattr(image_gen, "detect_image_providers", lambda: LOCAL_PIPELINE)
    monkeypatch.setattr(image_gen, "generate_with_diffusers", lambda req, stop=None: pytest.fail("must not start while another picture is made"))
    holding, release = threading.Event(), threading.Event()

    def hold():
        with heavy_work.picture_slot(wait_seconds=5):
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(5)
    try:
        result = image_gen.generate_images(ImageGenerationRequest(prompt="a lighthouse", provider="diffusers_local"), wait_seconds=0.3)
    finally:
        release.set()
        holder.join()
    assert result["success"] is False and result["busy"] is True and "picture" in result["error"]


def test_a_comfyui_workflow_takes_the_same_slot(monkeypatch):
    from modules.nexus_core import NexusCore

    core = NexusCore()
    monkeypatch.setitem(core.config, "picture_wait_seconds", 0.3)
    monkeypatch.setattr(core, "_require_content_rule", lambda *args, **kwargs: None)
    ran = []
    monkeypatch.setattr(core.comfyui, "run_workflow", lambda **kwargs: ran.append(kwargs) or "made")
    holding, release = threading.Event(), threading.Event()

    def hold():
        with heavy_work.picture_slot(wait_seconds=5):
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait(5)
    try:
        busy = core.run_comfyui_workflow(workflow={}, prompt="a lighthouse")
    finally:
        release.set()
        holder.join()
    assert busy.success is False and "picture" in busy.error and ran == []
    assert core.run_comfyui_workflow(workflow={}, prompt="a lighthouse") == "made"


def test_the_images_tab_shows_the_wait_and_the_memory_note():
    from app import image_generation_notes

    notes = image_generation_notes({"waited_seconds": 42.4, "memory": {"note": "Made room first."}})
    assert notes == ["Waited 42 s for another picture to finish first: this computer makes one at a time.", "Made room first."]
    assert image_generation_notes({"success": True}) == []
