"""Canonical launch helpers for developer and packaged entrypoints."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

from cognitive_nexus.config import CognitiveNexusSettings, get_settings


def get_edge_path() -> Optional[str]:
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in edge_paths:
        if os.path.exists(path):
            return path
    return None


def open_browser(url: str) -> bool:
    edge_path = get_edge_path()
    if edge_path:
        try:
            subprocess.Popen([edge_path, url])
            return True
        except Exception:
            pass

    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def streamlit_args(app_path: Path, settings: Optional[CognitiveNexusSettings] = None) -> list[str]:
    settings = settings or get_settings()
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(settings.port),
        "--server.address",
        settings.host,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]


def launch_streamlit_app(
    app_path: Path,
    *,
    wait_before_open: float = 3.0,
    open_browser_after_start: bool = True,
    settings: Optional[CognitiveNexusSettings] = None,
) -> int:
    settings = settings or get_settings()
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    process = subprocess.Popen(streamlit_args(app_path, settings))
    try:
        time.sleep(wait_before_open)
        if open_browser_after_start:
            open_browser(settings.app_url)
        process.wait()
        return process.returncode or 0
    except KeyboardInterrupt:
        process.terminate()
        return 0

