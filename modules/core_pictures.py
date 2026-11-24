"""NexusCore's pictures: local generation and ComfyUI workflows, both under the one content rule.

Moved out of NexusCore (modules/nexus_core.py) unchanged; NexusCore is built from this class
(audit item 121). The methods use the attributes NexusCore.__init__ sets.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from modules.comfyui_client import ComfyUIResult
from modules import heavy_work
from modules.image_gen import ImageGenerationRequest, generate_images

logger = logging.getLogger("modules.nexus_core")  # the same name as before the move


class PictureServices:
    def generate_image(self, request: ImageGenerationRequest, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Generate images through the existing image provider module.

        The content rule is applied to what is asked for (the prompt). The negative prompt lists
        what to leave out and is not part of the request. How memory is made for a picture made
        here, and how long it may take, come from the settings (picture_memory and the config's
        picture_time_limit_seconds and picture_wait_seconds; see modules/heavy_work.py).
        """

        self._require_content_rule(str(request.prompt or ""), kind="image")
        settings = settings or {}
        return generate_images(
            request,
            memory_policy=str(settings.get("picture_memory") or self.config.get("picture_memory") or heavy_work.DEFAULT_POLICY),
            ollama_url=str(settings.get("base_url") or self.config.get("ollama_url") or ""),
            time_limit_seconds=float(self.config.get("picture_time_limit_seconds") or heavy_work.DEFAULT_TIME_LIMIT_SECONDS),
            wait_seconds=float(self.config.get("picture_wait_seconds") or heavy_work.DEFAULT_WAIT_SECONDS),
        )

    def run_comfyui_workflow(
        self,
        *,
        workflow: dict[str, Any],
        prompt: str,
        negative_prompt: str = "",
        timeout: float = 240.0,
    ):
        """Run a ComfyUI workflow through the central client.

        It takes the machine's one picture slot like any picture made here (modules/heavy_work.py),
        so a workflow and a local picture are never made at once."""

        self._require_content_rule(str(prompt or ""), kind="image")
        try:
            with heavy_work.picture_slot(float(self.config.get("picture_wait_seconds") or heavy_work.DEFAULT_WAIT_SECONDS)):
                return self.comfyui.run_workflow(
                    workflow=workflow,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    timeout=timeout,
                )
        except heavy_work.MachineBusy as busy:
            return ComfyUIResult(success=False, error=str(busy))
