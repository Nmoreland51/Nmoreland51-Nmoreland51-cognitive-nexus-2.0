"""One prompt through several configurations, to find where a bad answer comes from.

    python tools/configuration_compare.py --prompt "..." --configs direct nexus research --save out.json --texts texts.json
    python tools/configuration_compare.py --prompt "..." --configs nexus --model qwen2.5-coder:7b

Configurations (all on this machine, the same seed):

  direct    the model alone, straight through Ollama: the prompt as typed, the model's own settings and its
            own built-in system line, as `ollama run` would
  nexus     Cognitive Nexus's chat path with its default settings (no web search), as the chat tab uses it
  research  the same, with web search for this message: the chat's own search, reading and summary

--model picks the model for every configuration (default dolphin3:8b), so the same configurations can be
run with another model. For each run: how long it took, the reply, the exact request the app posted (for
nexus and research) and why the model stopped. Nothing is judged automatically: the replies are for reading.

Real generations on a CPU: one to four minutes per configuration.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from answer_attribution import SEED, Recorder, generate  # noqa: E402  (tools/answer_attribution.py, next to this file)

DIRECT_GUARD_TOKENS = 2048


def run_direct(prompt: str, model: str, base_url: str) -> dict[str, Any]:
    reply = generate(base_url, {"model": model, "prompt": prompt, "options": {"seed": SEED, "num_predict": DIRECT_GUARD_TOKENS}})
    return {"config": "direct", "model": model, "seconds": reply["seconds"], "ended": reply["done_reason"], "reply": reply["text"], "request": None}


def _forced_web_route(route_message):
    """route_message, with every message routed as a web question (the research configuration).

    The category has to be web_research, as the router sets it for one: Auto Precision switches web search
    off for any other category, whatever the "needs a search" flag says.
    """

    def routed(*args: Any, **kwargs: Any):
        decision = route_message(*args, **kwargs)
        message = args[0] if args else kwargs.get("user_message", "")
        return dataclasses.replace(decision, category="web_research", requires_web_search=True, search_query=decision.search_query or message)

    return routed


def run_nexus(prompt: str, model: str, base_url: str, *, research: bool) -> dict[str, Any]:
    from behavior_check import chat_settings  # tools/behavior_check.py: the app's chat defaults, network tools off

    from modules import nexus_core, provider_router
    from ui.chat_tab import normalize_assistant_response

    core = nexus_core.NexusCore()
    settings = chat_settings(model, base_url)
    original_route = nexus_core.route_message
    if research:
        settings["use_web_for_chat"] = True
        nexus_core.route_message = _forced_web_route(original_route)
    try:
        with Recorder(provider_router.OLLAMA_SESSION) as recorder:
            started = time.perf_counter()
            displayed = "".join(core.stream_chat_response(prompt, [], settings)).strip()
            seconds = round(time.perf_counter() - started, 1)
    finally:
        nexus_core.route_message = original_route
    chat = recorder.chat_call()
    result = dict(core.last_provider_result or {})
    return {
        "config": "research" if research else "nexus",
        "model": model,
        "seconds": seconds,
        "ended": (chat or {}).get("done_reason", ""),
        "reply": normalize_assistant_response(displayed),
        "provider": str(result.get("provider") or ""),
        "model_calls": [
            {"num_predict": (call["payload"].get("options") or {}).get("num_predict"), "system_field": "system" in call["payload"], "received_characters": len(call["received"])}
            for call in recorder.calls
        ],
        "searches": list((result.get("searches") or [])),
        "sources": result.get("sources"),
        "plan": {key: (core.last_response_plan or {}).get(key) for key in ("intent", "mode", "context_policy")},
        "request": (chat or {}).get("payload"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--configs", nargs="+", default=["direct", "nexus", "research"], choices=["direct", "nexus", "research"])
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--save", type=Path, help="the runs without the requests")
    parser.add_argument("--texts", type=Path, help="local file with everything, the requests included (not for the repository)")
    args = parser.parse_args(argv)

    runs = []
    for config in args.configs:
        try:
            run = run_direct(args.prompt, args.model, args.base_url) if config == "direct" else run_nexus(args.prompt, args.model, args.base_url, research=config == "research")
        except Exception as exc:  # one failed configuration is recorded, not fatal
            run = {"config": config, "model": args.model, "error": f"{type(exc).__name__}: {exc}"}
        runs.append(run)
        print(f"===== {config} ({args.model}): {run.get('seconds', '-')} s, ended {run.get('ended', '')!r} {run.get('error', '')}", flush=True)
        print(str(run.get("reply", ""))[:1500], flush=True)
        if args.texts:  # after every run, so a stopped comparison keeps what it had
            args.texts.parent.mkdir(parents=True, exist_ok=True)
            args.texts.write_text(json.dumps({"prompt": args.prompt, "runs": runs}, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        kept = [{key: value for key, value in run.items() if key != "request"} for run in runs]
        args.save.write_bytes((json.dumps({"prompt": args.prompt, "date": time.strftime("%Y-%m-%d"), "seed": SEED, "runs": kept}, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
