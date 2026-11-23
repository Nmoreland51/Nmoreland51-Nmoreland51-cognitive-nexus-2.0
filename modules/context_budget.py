"""How much prompt fits: the model's window, the reply held back, and how long the user will wait.

A local model reads a fixed number of tokens (its context window, `num_ctx` in Ollama). The
prompt and the reply share it. When the prompt alone is too long, Ollama drops its beginning
without any error, and the beginning is where the instructions are. Measured on 2026-11-23: a
2,147-token chat prompt sent with a 2,048-token window was cut to 1,026 tokens.

This module decides the window for a request and how many prompt tokens the packer may use, so
that the prompt is trimmed deliberately (least important parts first) instead of being cut by the
model server. It also limits the prompt by time on slow hardware: on a CPU that reads 32 tokens a
second, 2,000 prompt tokens are a minute of waiting before the first word.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

# Windows are requested in steps. Changing the window makes Ollama reload the model (6 to 15
# seconds on this hardware), so the router only ever steps up and then stays there.
WINDOW_STEPS = (2048, 4096, 8192, 16384, 32768)
# Held back for the chat template the server wraps around the prompt and its start/end markers.
RESERVE_TOKENS = 64
# The estimator's worst measured under-count is 7.4% (tests/fixtures/token_counts.json).
ESTIMATE_SAFETY = 1.08
# Used when the model server cannot say how large the model's window is.
UNKNOWN_MODEL_WINDOW = 4096
# Never plan for less prompt than this; below it the instructions themselves do not fit.
MIN_PROMPT_TOKENS = 384
# Seconds of prompt reading the user is asked to wait for, by throughput profile.
PROMPT_SECONDS = {"turbo": 12.0, "fast": 30.0, "balanced": 75.0}


@dataclass(frozen=True)
class ContextBudget:
    """The window to request and what the prompt may use of it."""

    num_ctx: int
    reply_tokens: int
    prompt_tokens: int
    model_window: int | None
    limited_by: str  # "window", "speed" or "model"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_max_window(total_ram_gb: float | None) -> int:
    """Largest window to use on this machine. A bigger window costs memory for the whole time
    the model is loaded, whether or not the prompt fills it."""

    if total_ram_gb is None:
        return 8192
    if total_ram_gb >= 24:
        return 16384
    if total_ram_gb >= 12:
        return 8192
    return 4096


def window_cap(model_window: int | None, max_window: int | None) -> int:
    cap = min(int(model_window or UNKNOWN_MODEL_WINDOW), int(max_window or WINDOW_STEPS[-1]))
    return max(cap, 512)


def step_for(tokens_needed: int, cap: int) -> int:
    """Smallest window step that holds `tokens_needed`, never above `cap`."""

    for step in WINDOW_STEPS:
        if step >= tokens_needed:
            return min(step, cap)
    return cap


def tokens_needed(prompt_tokens_estimate: int, reply_tokens: int) -> int:
    """Window a prompt of this estimated size needs, with the safety margin applied."""

    return int(prompt_tokens_estimate * ESTIMATE_SAFETY) + int(reply_tokens) + RESERVE_TOKENS


def window_for_prompt(
    prompt_tokens_estimate: int,
    reply_tokens: int,
    *,
    requested_ctx: int = 0,
    model_window: int | None = None,
    max_window: int | None = None,
    in_use: int = 0,
) -> tuple[int, bool]:
    """Window to request for a prompt that is already built. Returns (num_ctx, fits).

    `in_use` is the window the model is currently loaded with; the result is never smaller, so
    the model is not reloaded just to shrink the window. `fits` is False when even the largest
    allowed window is too small, which means the server will cut the prompt.
    """

    cap = window_cap(model_window, max_window)
    need = tokens_needed(prompt_tokens_estimate, reply_tokens)
    chosen = max(step_for(max(need, int(requested_ctx or 0), WINDOW_STEPS[0]), cap), min(int(in_use or 0), cap))
    return chosen, need <= chosen


def plan_budget(
    *,
    requested_ctx: int,
    reply_tokens: int,
    model_window: int | None = None,
    max_window: int | None = None,
    in_use: int = 0,
    prompt_tokens_per_second: float | None = None,
    max_prompt_seconds: float | None = None,
) -> ContextBudget:
    """Decide the window and the prompt allowance before the prompt is packed."""

    cap = window_cap(model_window, max_window)
    reply = max(16, int(reply_tokens))
    num_ctx = max(step_for(max(int(requested_ctx or 0), WINDOW_STEPS[0]), cap), min(int(in_use or 0), cap))
    least_prompt_room = math.ceil(MIN_PROMPT_TOKENS * ESTIMATE_SAFETY)
    # A reply allowance that leaves no room for the prompt: take the next step up if there is one.
    while num_ctx < cap and num_ctx - reply - RESERVE_TOKENS < least_prompt_room:
        num_ctx = step_for(num_ctx + 1, cap)
    limited_by = "window"
    available = num_ctx - reply - RESERVE_TOKENS
    if available < least_prompt_room:
        # The model itself is too small for this reply size: shorten the reply, keep the prompt.
        reply = max(16, num_ctx - RESERVE_TOKENS - least_prompt_room)
        available = num_ctx - reply - RESERVE_TOKENS
        limited_by = "model"
    prompt_tokens = max(1, int(available / ESTIMATE_SAFETY))
    if prompt_tokens_per_second and max_prompt_seconds:
        by_speed = max(MIN_PROMPT_TOKENS, int(prompt_tokens_per_second * max_prompt_seconds))
        if by_speed < prompt_tokens:
            prompt_tokens, limited_by = by_speed, "speed"
    return ContextBudget(
        num_ctx=num_ctx,
        reply_tokens=reply,
        prompt_tokens=prompt_tokens,
        model_window=model_window,
        limited_by=limited_by,
    )
