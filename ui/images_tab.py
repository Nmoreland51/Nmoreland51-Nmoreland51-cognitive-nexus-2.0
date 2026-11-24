"""The Image Generation tab, ComfyUI workflows and the Gallery.

Moved out of app.py unchanged (audit item 120).
"""

from __future__ import annotations

import base64
import html
import json
import time
from pathlib import Path
from typing import Any
import streamlit as st

from modules import heavy_work
from modules.image_gen import (
    IMAGE_STYLE_OPTIONS,
    ImageGenerationRequest,
)
from modules.behavior_policy import ContentRuleBlocked
from ui.shared import format_bytes, get_cached_gallery, get_cached_image_provider, get_cached_image_providers, get_cached_image_summary, get_nexus_core, is_demo_safe, record_perf, sanitize_demo_rows, sanitize_demo_text


def image_provider_status_rows(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider in providers:
        available = bool(provider.get("available"))
        implemented = bool(provider.get("implemented"))
        if available and implemented:
            status = "Ready"
        elif available:
            status = "Workflow only"
        else:
            status = "Offline"
        rows.append(
            {
                "Provider": provider.get("label") or provider.get("name", "unknown"),
                "Status": status,
                "Direct generation": "Yes" if implemented else "No",
                "Endpoint": provider.get("url") or "",
                "Model": provider.get("model") or "",
                "Message": provider.get("message") or "",
            }
        )
    return rows


def image_generation_ready(provider_name: str, providers: list[dict[str, Any]]) -> tuple[bool, str]:
    usable = [provider for provider in providers if provider.get("available") and provider.get("implemented")]
    if provider_name == "auto":
        if usable:
            return True, f"Auto will use {usable[0].get('label', usable[0].get('name', 'provider'))}."
        return (
            False,
            "No direct image provider is ready. Start Automatic1111 with API enabled or install the local Diffusers backend.",
        )

    selected = next((provider for provider in providers if provider.get("name") == provider_name), None)
    if not selected:
        return False, "Selected image provider was not detected."
    if not selected.get("available"):
        return False, selected.get("message") or "Selected image provider is offline."
    if not selected.get("implemented"):
        return (
            False,
            selected.get("message")
            or "This provider is reachable, but direct txt2img generation is not implemented here.",
        )
    return True, f"{selected.get('label', provider_name)} is ready."


def sanitize_image_generation_result(result: dict[str, Any]) -> dict[str, Any]:
    saved = result.get("saved") or []
    return {
        "success": bool(result.get("success")),
        "provider": result.get("provider"),
        "saved_count": len(saved),
        "error": result.get("error"),
        "saved": saved,
    }


def image_generation_notes(result: dict[str, Any]) -> list[str]:
    """What making the picture involved besides the picture: a wait for another one, room made in memory."""

    notes = []
    waited = float(result.get("waited_seconds") or 0)
    if waited >= 1:
        notes.append(f"Waited {waited:.0f} s for another picture to finish first: this computer makes one at a time.")
    note = (result.get("memory") or {}).get("note")
    if note:
        notes.append(str(note))
    return notes


def render_image_tab(settings: dict[str, Any] | None = None) -> None:
    st.subheader("Image Generation")
    demo_safe = is_demo_safe(settings)
    providers = get_cached_image_providers()
    image_summary = get_cached_image_summary()
    usable_providers = [provider for provider in providers if provider.get("available") and provider.get("implemented")]
    provider_names = ["auto"] + [provider["name"] for provider in providers]
    provider_labels = {"auto": "Auto"}
    provider_labels.update({provider["name"]: provider.get("label", provider["name"]) for provider in providers})

    status_cols = st.columns(4)
    status_cols[0].metric(
        "Direct provider",
        usable_providers[0].get("label", "Ready") if usable_providers else "Offline",
    )
    status_cols[1].metric("Saved images", int(image_summary.get("image_files", 0) or 0))
    status_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    status_cols[3].metric("Gallery size", format_bytes(image_summary.get("total_bytes", 0)))

    refresh_cols = st.columns([1, 3])
    with refresh_cols[0]:
        if st.button("Refresh image providers", key="refresh_image_providers", width="stretch"):
            get_cached_image_provider.clear()
            get_cached_image_providers.clear()
            get_nexus_core().comfyui.forget_status()
            get_cached_image_summary.clear()
            st.rerun()
    with refresh_cols[1]:
        if usable_providers:
            st.caption(f"Ready for direct generation: {', '.join(str(item.get('label', item.get('name'))) for item in usable_providers)}")
        else:
            st.warning("Direct image generation is offline. ComfyUI workflows can still run when ComfyUI is reachable below.")

    with st.expander("Image provider status", expanded=not bool(usable_providers)):
        st.dataframe(sanitize_demo_rows(image_provider_status_rows(providers), enabled=demo_safe), width="stretch", hide_index=True)

    prompt = st.text_area("Prompt", height=120, placeholder="Describe the image you want to generate.")
    negative_prompt = st.text_area("Negative prompt", height=80, placeholder="Optional things to avoid.")
    col1, col2, col3 = st.columns(3)
    with col1:
        provider = st.selectbox("Provider", provider_names, format_func=lambda value: provider_labels.get(value, value))
        width = st.slider("Width", 256, 1536, 512, step=64)
        steps = st.slider("Steps", 1, 80, 25)
    with col2:
        model = st.text_input("Model name", value="")
        height = st.slider("Height", 256, 1536, 512, step=64)
        cfg_scale = st.slider("CFG scale", 1.0, 20.0, 7.0, step=0.5)
    with col3:
        style = st.selectbox("Style", list(IMAGE_STYLE_OPTIONS))
        seed_text = st.text_input("Seed", value="", placeholder="Blank = random")
        num_images = st.number_input("Number of images", min_value=1, max_value=4, value=1, step=1)
    save_outputs = st.checkbox("Save outputs", value=True)
    configured_memory = str(get_nexus_core().config.get("picture_memory") or heavy_work.DEFAULT_POLICY)
    picture_memory = st.radio(
        "When memory is short for a picture made on this computer",
        heavy_work.POLICIES,
        index=heavy_work.POLICIES.index(configured_memory) if configured_memory in heavy_work.POLICIES else 0,
        format_func=lambda value: heavy_work.POLICY_LABELS.get(value, value),
        key="picture_memory",
        help=(
            f"A {width}x{height} picture needs about {heavy_work.picture_need_gb(width, height):.1f} GB of memory while it is made here. "
            "One picture is made at a time; it stops after the time limit in the settings."
        ),
    )
    generation_ready, readiness_message = image_generation_ready(provider, providers)
    if generation_ready:
        st.caption(readiness_message)
    else:
        st.info(readiness_message)

    if st.button("Generate Images", type="primary", disabled=not generation_ready):
        if not prompt.strip():
            st.warning("Enter an image prompt first.")
            return
        try:
            seed = int(seed_text) if seed_text.strip() else None
        except ValueError:
            st.warning("Seed must be a whole number or blank.")
            return
        req = ImageGenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            num_images=int(num_images),
            provider=provider,
            model=model,
            style=style,
            save_outputs=save_outputs,
        )
        with st.spinner("Generating image..."):
            started = time.perf_counter()
            try:
                result = get_nexus_core().generate_image(req, {**(settings or {}), "picture_memory": picture_memory})
            except ContentRuleBlocked as stopped:
                result = {"success": False, "error": stopped.reply, "images": [], "saved": []}
            record_perf("image.generate", time.perf_counter() - started)
            get_cached_gallery.clear()
            get_cached_image_summary.clear()
        st.session_state.last_image_generation_result = sanitize_image_generation_result(result)
        for note in image_generation_notes(result):
            st.caption(note)
        if not result.get("success"):
            st.error(result.get("error") or "Image generation failed.")
        else:
            st.success("Image generation complete.")
            result_images = result.get("images") or []
            for index, item in enumerate(result.get("saved", [])):
                image_path = item.get("file_path")
                if image_path:
                    st.image(image_path, caption=item.get("prompt", prompt), width="stretch")
                elif index < len(result_images):
                    st.image(result_images[index], caption=item.get("prompt", prompt), width="stretch")
                if demo_safe:
                    st.caption("Image metadata path hidden in Demo Safe Mode.")
                else:
                    with st.expander("Metadata", expanded=False):
                        st.json(item)
            st.divider()
            render_gallery(settings, limit=24)

    st.divider()
    render_comfyui_workflow_section(settings)


def render_comfyui_workflow_section(settings: dict[str, Any] | None = None) -> None:
    st.subheader("ComfyUI Workflows")
    demo_safe = is_demo_safe(settings)
    core = get_nexus_core()
    status = core.comfyui.detect()
    if status.available:
        st.success(sanitize_demo_text(status.message) if demo_safe else status.message)
    else:
        status_message = sanitize_demo_text(status.message) if demo_safe else status.message
        st.info(f"{status_message} Start ComfyUI and confirm the URL in Settings.")

    uploaded = st.file_uploader("Upload ComfyUI API workflow JSON", type=["json"], key="comfyui_workflow_upload")
    if uploaded and st.button("Save uploaded workflow", key="save_comfy_workflow"):
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            path = core.comfyui.save_workflow(payload, uploaded.name)
            st.success("Workflow saved locally." if demo_safe else f"Saved workflow: {path}")
        except Exception as exc:
            st.error(f"Could not save workflow: {exc}")

    workflows = core.comfyui.list_workflows()
    selected_workflow = None
    if workflows:
        selected_workflow = st.selectbox("Saved workflow", workflows, format_func=lambda path: path.name)
    else:
        st.caption("No saved workflows yet. Export an API-format workflow from ComfyUI and upload it here.")

    prompt = st.text_area("Workflow prompt", height=90, key="comfy_prompt")
    negative_prompt = st.text_area("Workflow negative prompt", height=60, key="comfy_negative_prompt")
    timeout = st.slider("Workflow timeout seconds", 30, 600, 240, step=30)

    disabled = not status.available or selected_workflow is None
    if st.button("Run ComfyUI Workflow", type="primary", disabled=disabled):
        try:
            workflow = core.comfyui.load_workflow(Path(selected_workflow))
            with st.status("Running ComfyUI workflow...", expanded=True) as run_status:
                result = core.run_comfyui_workflow(
                    workflow=workflow,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    timeout=float(timeout),
                )
                run_status.update(label="ComfyUI workflow complete", state="complete" if result.success else "error")
            if not result.success:
                st.error(result.error or "ComfyUI workflow failed.")
                return
            st.success(f"ComfyUI prompt id: {result.prompt_id}")
            for image in result.images:
                path = image.get("path")
                if path and Path(path).exists():
                    st.image(path, caption=Path(path).name, width="stretch")
            if result.metadata_path:
                st.caption("Metadata saved locally." if demo_safe else f"Metadata saved: {result.metadata_path}")
        except ContentRuleBlocked as stopped:
            st.warning(stopped.reply)
        except Exception as exc:
            st.error(f"ComfyUI workflow failed: {exc}")


def local_image_data_uri(path: Path) -> str:
    try:
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "image/png")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


def gallery_card_html(
    *,
    data_uri: str,
    prompt: str,
    provider: str,
    timestamp: str,
    file_name: str,
    details: str,
) -> str:
    safe_prompt = html.escape(prompt.strip() or file_name)
    safe_provider = html.escape(provider.strip() or "unknown provider")
    safe_time = html.escape(timestamp.strip())
    safe_name = html.escape(file_name)
    safe_details = html.escape(details.strip())
    return f"""
<div style="border:1px solid #e6e8ef;border-radius:8px;padding:10px;margin-bottom:18px;background:#fff;">
  <img src="{data_uri}" alt="{safe_name}" style="width:100%;height:180px;object-fit:contain;border-radius:6px;display:block;background:#f2f4f7;" />
  <div style="font-weight:600;margin-top:8px;line-height:1.25;">{safe_prompt}</div>
  <div style="color:#667085;font-size:0.82rem;margin-top:6px;">{safe_provider}</div>
  <div style="color:#98a2b3;font-size:0.78rem;margin-top:3px;">{safe_time}</div>
  <div style="color:#98a2b3;font-size:0.78rem;margin-top:3px;">{safe_details}</div>
</div>
"""


def render_gallery(settings: dict[str, Any] | None = None, limit: int = 50) -> None:
    st.subheader("Gallery")
    demo_safe = is_demo_safe(settings)
    items = get_cached_gallery(limit)
    if not items:
        st.info("No generated images found yet.")
        return

    image_summary = get_cached_image_summary()
    gallery_cols = st.columns(4)
    gallery_cols[0].metric("Showing", len(items))
    gallery_cols[1].metric("PNG artifacts", int(image_summary.get("image_files", 0) or 0))
    gallery_cols[2].metric("Metadata JSON", int(image_summary.get("metadata_files", 0) or 0))
    gallery_cols[3].metric("Storage", format_bytes(image_summary.get("total_bytes", 0)))
    missing_records = int(image_summary.get("missing_image_records", 0) or 0)
    invalid_metadata = int(image_summary.get("invalid_metadata", 0) or 0)
    if missing_records or invalid_metadata:
        st.warning(f"Gallery integrity: {missing_records} metadata records point to missing images; {invalid_metadata} metadata files could not be read.")

    st.caption("Recent generated images and legacy outputs. Broken or missing files are skipped cleanly.")
    cols = st.columns(3)
    for index, item in enumerate(items):
        with cols[index % 3]:
            path = item.get("file_path") or item.get("path")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if not path:
                st.warning("Image record is missing a file path.")
                continue

            image_path = Path(path)
            if not image_path.exists():
                st.warning(f"Missing image file: {image_path.name}")
                continue

            prompt = (
                metadata.get("prompt")
                or item.get("prompt")
                or item.get("name")
                or image_path.name
            )
            provider = metadata.get("provider") or item.get("provider") or "unknown provider"
            timestamp = metadata.get("timestamp") or item.get("timestamp") or item.get("created_at") or ""
            details = f"{image_path.name} | {format_bytes(item.get('size', 0))}"
            data_uri = local_image_data_uri(image_path)
            if not data_uri:
                st.warning(f"Could not load image: {image_path.name}")
                continue
            st.markdown(
                gallery_card_html(
                    data_uri=data_uri,
                    prompt=str(prompt),
                    provider=str(provider),
                    timestamp=str(timestamp),
                    file_name=image_path.name,
                    details=details,
                ),
                unsafe_allow_html=True,
            )
            with st.expander("Artifact metadata", expanded=False):
                if demo_safe:
                    st.caption("Local artifact path and raw metadata hidden in Demo Safe Mode.")
                elif metadata:
                    st.caption(str(image_path))
                    st.json(metadata)
                else:
                    st.caption("No JSON metadata was found for this legacy image.")
