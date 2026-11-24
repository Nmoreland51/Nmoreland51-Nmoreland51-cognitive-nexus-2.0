"""Check with the real model that the app does not stop legitimate questions, and see what the model itself does.

    python tools/behavior_check.py --model dolphin3:8b
    python tools/behavior_check.py --model dolphin3:8b --save docs/benchmarks/behavior_dolphin3-8b.json

tests/fixtures/behavior_check.json holds questions the owner asked not to have refused: adult
subjects, drugs, money, controversial subjects, ordinary questions with alarming words, the
owner's own style instructions ("from now on you are ..."), and ordinary questions about minors.
Each goes through the real chat path (NexusCore.generate_chat_response) to the real model.

Two different things are recorded and kept apart:

  * stopped by the app: the reply was one of the app's own texts. This has to be zero. Apart
    from its one content rule the app has nothing that could stop a question, and this run shows
    the rule's check leaving these alone.
  * declined by the model: the answer opens like a refusal. That is the model's own behaviour,
    which the app passes on unchanged and labels as the model's.

The opening of each answer is saved as evidence that a real answer came back, except where the
question asks for explicit writing. This runs real generations: about a minute per question on a
CPU-only machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.behavior_policy import (  # noqa: E402
    CONTENT_RULE_PICTURE_REPLY,
    CONTENT_RULE_REPLY,
    CONTENT_RULE_UNCHECKED_REPLY,
    looks_like_model_refusal,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "behavior_check.json"
APP_TEXTS = (CONTENT_RULE_REPLY, CONTENT_RULE_PICTURE_REPLY, CONTENT_RULE_UNCHECKED_REPLY)
# Providers that mean "the app answered or stopped this itself"; a model's answer has the provider's own name.
APP_PROVIDERS = {"content_rule"}


def load_prompts(path: Path = FIXTURE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["prompts"]


def chat_settings(model: str, base_url: str) -> dict[str, Any]:
    """The app's defaults for a chat turn, with the tools that need the network switched off."""

    from modules.chat_profile import ChatProfile
    from nexus_router import RouterConfig

    return {
        "chat_profile": ChatProfile(enabled=False),
        "router_config": RouterConfig(default_model=model, enabled=True),
        "provider_order": ["ollama", "fallback"],
        "selected_model": model,
        "base_url": base_url,
        "use_memory": False,
        "use_knowledge_for_chat": False,
        "use_web_for_chat": False,
        "enable_reality_research_agent": False,
        "enable_bloodhound_search": False,
        "generation_timeout": 600.0,
        "auto_precision_mode": True,
        "staged_streaming": False,
        "enable_response_self_critic": False,
    }


def check_one(core: Any, prompt: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    answer = core.generate_chat_response(prompt["text"], [], dict(settings))
    seconds = time.perf_counter() - started
    result = dict(core.last_provider_result or {})
    provider = str(result.get("provider") or "")
    stopped = provider in APP_PROVIDERS or answer.strip() in APP_TEXTS
    answered = bool(answer.strip()) and not stopped and provider not in {"fallback", ""} and not answer.startswith("Fallback:")
    row = {
        "id": prompt["id"],
        "group": prompt["group"],
        "stopped_by_app": stopped,
        "answered_by_model": answered,
        "declined_by_model": bool(answered and looks_like_model_refusal(answer)),
        "provider": provider,
        "model": str(result.get("model") or ""),
        "content_rule_stage": str((getattr(core, "last_content_rule", None) or {}).get("stage") or ""),
        "the_message_reached_the_model_unchanged": prompt["text"] in str((getattr(core, "last_prompt", None) or {}).get("prompt") or ""),
        "fenced_or_scanned": "UNTRUSTED" in str((getattr(core, "last_prompt", None) or {}).get("prompt") or ""),
        "characters": len(answer),
        "seconds": round(seconds, 1),
        "opening": " ".join(answer.split())[:140] if prompt.get("store_opening", True) else "[not stored: explicit writing was asked for]",
    }
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    for row in rows:
        group = groups.setdefault(row["group"], {"asked": 0, "stopped_by_app": 0, "answered_by_model": 0, "declined_by_model": 0})
        group["asked"] += 1
        group["stopped_by_app"] += row["stopped_by_app"]
        group["answered_by_model"] += row["answered_by_model"]
        group["declined_by_model"] += row["declined_by_model"]
    return {
        "asked": len(rows),
        "stopped_by_app": [row["id"] for row in rows if row["stopped_by_app"]],
        "not_answered": [row["id"] for row in rows if not row["answered_by_model"] and not row["stopped_by_app"]],
        "declined_by_model": [row["id"] for row in rows if row["declined_by_model"]],
        "message_changed_or_fenced": [row["id"] for row in rows if row["fenced_or_scanned"] or not row["the_message_reached_the_model_unchanged"]],
        "by_group": groups,
    }


def run(core: Any, settings: dict[str, Any], prompts: list[dict[str, Any]], progress: bool = False) -> dict[str, Any]:
    rows = []
    for prompt in prompts:
        row = check_one(core, prompt, settings)
        rows.append(row)
        if progress:
            state = "STOPPED BY THE APP" if row["stopped_by_app"] else ("declined by the model" if row["declined_by_model"] else ("answered" if row["answered_by_model"] else "NO ANSWER"))
            print(f"{row['id']:<10} {state:<22} {row['seconds']:>6}s  {row['opening'][:70]}", flush=True)
    return {"summary": summarize(rows), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--save", type=Path)
    args = parser.parse_args(argv)

    from modules.nexus_core import NexusCore

    prompts = [prompt for prompt in load_prompts() if not args.only or prompt["id"] in args.only]
    result = run(NexusCore(), chat_settings(args.model, args.base_url), prompts, progress=True)
    result["model"] = args.model
    result["date"] = time.strftime("%Y-%m-%d")
    summary = result["summary"]
    print(
        f"\nasked {summary['asked']}; stopped by the app: {summary['stopped_by_app'] or 'none'}; "
        f"declined by the model: {summary['declined_by_model'] or 'none'}; no answer: {summary['not_answered'] or 'none'}; "
        f"message changed or fenced: {summary['message_changed_or_fenced'] or 'none'}"
    )
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(result, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 1 if summary["stopped_by_app"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
