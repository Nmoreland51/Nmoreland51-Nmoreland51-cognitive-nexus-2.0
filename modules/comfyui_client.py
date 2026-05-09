"""ComfyUI workflow API integration for Cognitive Nexus."""

from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from modules.nexus_config import load_runtime_config


BASE_DIR = Path("data/comfyui")
WORKFLOW_DIR = BASE_DIR / "workflows"
OUTPUT_DIR = BASE_DIR / "outputs"
METADATA_DIR = BASE_DIR / "metadata"


@dataclass
class ComfyUIStatus:
    """ComfyUI availability status."""

    available: bool
    message: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComfyUIResult:
    """Result returned after running a ComfyUI workflow."""

    success: bool
    prompt_id: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    metadata_path: str = ""
    error: str = ""
    raw_history: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_comfy_dirs() -> None:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)


def _slug(text: str, max_len: int = 60) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "workflow").strip().lower()).strip("_")
    return (slug or "workflow")[:max_len]


class ComfyUIClient:
    """Small HTTP client for local ComfyUI workflows."""

    def __init__(self, base_url: str | None = None, timeout: float = 5.0) -> None:
        config = load_runtime_config()
        self.base_url = (base_url or str(config.get("comfyui_url", "http://127.0.0.1:8188"))).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        ensure_comfy_dirs()

    def detect(self) -> ComfyUIStatus:
        """Detect whether the ComfyUI server is reachable."""

        try:
            response = self.session.get(f"{self.base_url}/system_stats", timeout=1.5)
            if response.ok:
                return ComfyUIStatus(True, "ComfyUI is reachable.", self.base_url)
            root = self.session.get(self.base_url, timeout=1.5)
            if root.ok or root.status_code in {200, 404}:
                return ComfyUIStatus(True, "ComfyUI server responded.", self.base_url)
            return ComfyUIStatus(False, f"ComfyUI returned HTTP {root.status_code}.", self.base_url)
        except Exception as exc:
            return ComfyUIStatus(False, f"ComfyUI is not reachable: {exc}", self.base_url)

    def list_workflows(self) -> list[Path]:
        """List saved ComfyUI API workflow JSON files."""

        ensure_comfy_dirs()
        return sorted(WORKFLOW_DIR.glob("*.json"))

    def save_workflow(self, payload: dict[str, Any], name: str = "") -> Path:
        """Save an uploaded workflow JSON file."""

        ensure_comfy_dirs()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = WORKFLOW_DIR / f"{timestamp}_{_slug(name or 'workflow')}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_workflow(self, path: Path) -> dict[str, Any]:
        """Load a saved workflow JSON file."""

        return json.loads(path.read_text(encoding="utf-8"))

    def patch_workflow_text(self, workflow: dict[str, Any], prompt: str, negative_prompt: str = "") -> dict[str, Any]:
        """Patch common CLIPTextEncode text inputs in an API workflow."""

        patched = copy.deepcopy(workflow)
        text_nodes: list[tuple[str, dict[str, Any]]] = []
        for node_id, node in patched.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", "")).lower()
            inputs = node.get("inputs", {})
            if "cliptextencode" in class_type and isinstance(inputs, dict) and "text" in inputs:
                text_nodes.append((node_id, node))

        if not text_nodes:
            return patched

        positive_set = False
        negative_set = False
        for node_id, node in text_nodes:
            title = str(node.get("_meta", {}).get("title", "")).lower()
            inputs = node["inputs"]
            if negative_prompt and ("negative" in title or "neg" in title):
                inputs["text"] = negative_prompt
                negative_set = True
            elif not positive_set:
                inputs["text"] = prompt
                positive_set = True

        if negative_prompt and not negative_set and len(text_nodes) > 1:
            text_nodes[-1][1]["inputs"]["text"] = negative_prompt
        return patched

    def queue_workflow(self, workflow: dict[str, Any]) -> str:
        """Submit a workflow to ComfyUI and return the prompt_id."""

        payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
        response = self.session.post(f"{self.base_url}/prompt", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("node_errors"):
            raise RuntimeError(f"ComfyUI validation failed: {data['node_errors']}")
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt_id.")
        return prompt_id

    def poll_history(self, prompt_id: str, timeout: float = 240.0, interval: float = 1.5) -> dict[str, Any]:
        """Poll /history/{prompt_id} until outputs are available or timeout expires."""

        deadline = time.time() + timeout
        last_payload: dict[str, Any] = {}
        while time.time() < deadline:
            response = self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            last_payload = payload
            entry = payload.get(prompt_id) if isinstance(payload, dict) else None
            if isinstance(entry, dict) and entry.get("outputs"):
                return entry
            time.sleep(interval)
        raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}. Last response: {last_payload}")

    def _image_refs_from_history(self, history: dict[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for output in (history.get("outputs") or {}).values():
            if not isinstance(output, dict):
                continue
            for image in output.get("images", []) or []:
                if not isinstance(image, dict) or not image.get("filename"):
                    continue
                refs.append(
                    {
                        "filename": str(image.get("filename", "")),
                        "subfolder": str(image.get("subfolder", "")),
                        "type": str(image.get("type", "output")),
                    }
                )
        return refs

    def download_image(self, image_ref: dict[str, str], prompt_id: str, index: int) -> Path:
        """Download one image from ComfyUI /view."""

        ensure_comfy_dirs()
        response = self.session.get(f"{self.base_url}/view", params=image_ref, timeout=60)
        response.raise_for_status()
        suffix = Path(image_ref["filename"]).suffix or ".png"
        path = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{prompt_id}_{index:03d}{suffix}"
        path.write_bytes(response.content)
        return path

    def run_workflow(
        self,
        *,
        workflow: dict[str, Any],
        prompt: str,
        negative_prompt: str = "",
        timeout: float = 240.0,
    ) -> ComfyUIResult:
        """Patch prompt text, run the workflow, poll status, and save images/metadata."""

        status = self.detect()
        if not status.available:
            return ComfyUIResult(success=False, error=status.message)

        try:
            patched = self.patch_workflow_text(workflow, prompt, negative_prompt)
            prompt_id = self.queue_workflow(patched)
            history = self.poll_history(prompt_id, timeout=timeout)
            refs = self._image_refs_from_history(history)
            saved_images = []
            for index, ref in enumerate(refs, start=1):
                path = self.download_image(ref, prompt_id, index)
                saved_images.append({"path": str(path), **ref})

            metadata = {
                "timestamp": datetime.now().isoformat(),
                "prompt_id": prompt_id,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "base_url": self.base_url,
                "images": saved_images,
            }
            metadata_path = METADATA_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{prompt_id}.json"
            metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

            return ComfyUIResult(
                success=True,
                prompt_id=prompt_id,
                images=saved_images,
                metadata_path=str(metadata_path),
                raw_history=history,
            )
        except Exception as exc:
            return ComfyUIResult(success=False, error=str(exc))
