"""Each tab of the app is a unit of its own under ui/ and can be drawn alone (item 120).

The whole page is run by tests/test_app_controls.py. Here every tab is drawn on its own, after the
sidebar that supplies its settings, through Streamlit's own test runner and with the real
NexusCore (the suite's model address is a closed port, so no model answers).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]

TABS = [
    ("ui.overview_tab", "render_overview_tab", "Home / Overview"),
    ("ui.chat_tab", "render_chat_tab", "Chat"),
    ("ui.research_tabs", "render_reality_research_tab", "Reality-First Research Agent"),
    ("ui.research_tabs", "render_web_research_tab", "Web Research"),
    ("ui.knowledge_tabs", "render_files_knowledge_tab", "Files / Knowledge"),
    ("ui.knowledge_tabs", "render_memory_tab", "Memory"),
    ("ui.images_tab", "render_image_tab", "Image Generation"),
    ("ui.images_tab", "render_gallery", "Gallery"),
    ("ui.diagnostics_tab", "render_diagnostics_tab", "Diagnostics"),
    ("ui.settings_tab", "render_settings_tab", ""),
    ("ui.knowledge_tabs", "render_tools_tab", "Tools / Utilities"),
    ("ui.settings_tab", "render_agent_tab", ""),
]


def _one_tab(module_name: str, function_name: str) -> None:
    import importlib

    from modules.chat_profile import load_chat_profile
    from ui import shared
    from ui.sidebar import render_sidebar

    core = shared.get_nexus_core()
    status = shared.get_cached_ollama_status()
    inventory = shared.get_cached_project_inventory()
    image_status = shared.get_cached_image_provider()
    core_status = shared.get_cached_core_status(tuple(core.config.get("provider_order", ["ollama", "fallback"])))
    settings = render_sidebar(status, inventory, image_status, load_chat_profile(), core_status)
    render = getattr(importlib.import_module(module_name), function_name)
    if function_name in {"render_overview_tab", "render_diagnostics_tab"}:
        render(status, inventory, image_status, core_status, settings)
    else:
        render(settings)


@pytest.mark.parametrize("module_name, function_name, heading", TABS, ids=[name for _module, name, _heading in TABS])
def test_each_tab_draws_on_its_own(module_name, function_name, heading):
    page = AppTest.from_function(_one_tab, args=(module_name, function_name), default_timeout=90).run()
    assert not page.exception, [item.value for item in page.exception]
    assert len(page.main) > 0
    if heading:
        assert heading in [item.value for item in page.subheader]


def test_app_py_only_starts_the_app_and_lays_out_the_tabs():
    tree = ast.parse((REPO_ROOT / "app.py").read_text(encoding="utf-8"))
    functions = sorted(node.name for node in tree.body if isinstance(node, ast.FunctionDef))
    assert functions == ["main", "restore_persisted_chat", "run_startup_tasks"]


def test_every_tab_in_the_layout_is_drawn_by_a_ui_module():
    import app

    drawn = {name for _module, name, _heading in TABS}
    for name in drawn:
        assert getattr(app, name).__module__.startswith("ui."), name
