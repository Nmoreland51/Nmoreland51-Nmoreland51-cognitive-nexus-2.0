"""Values NexusCore and its service classes share.

Moved out of modules/nexus_core.py unchanged (audit item 121).
"""

from __future__ import annotations

import time



# Model options for web research summaries. The brief (chat) answer uses the same 2048 context
# as normal chat, so Ollama keeps one loaded copy of the model (~6s reload otherwise on CPU), and
# temperature 0 so a short answer copied from sources doesn't vary run to run (e.g. which date).
BRIEF_WEB_SUMMARY_OPTIONS = {"temperature": 0.0, "num_predict": 160, "num_ctx": 2048}


FULL_WEB_SUMMARY_OPTIONS = {"temperature": 0.25, "num_predict": 480, "num_ctx": 4096}


def _elapsed_ms(started: float, ended: float | None = None) -> float:
    """Return elapsed milliseconds rounded for diagnostics."""

    return round(((ended or time.perf_counter()) - started) * 1000, 1)
