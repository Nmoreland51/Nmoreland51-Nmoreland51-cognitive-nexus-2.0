"""Where a refusal, a redirect or a shortened answer comes from: the model, the app's prompt, or the app's handling of the answer.

    python tools/answer_attribution.py --model dolphin3:8b --save docs/benchmarks/attribution_dolphin3-8b.json --texts answers.json

For each request in tests/fixtures/attribution_check.json the same model is asked three ways, with the
same temperature and a fixed seed, so that the only difference is what the app does:

  direct     the request alone, posted straight to Ollama (/api/generate, as `ollama run` would: the
             model's own built-in system line applies, nothing of the app's)
  nexus      the exact request the app posted for this message (prompt, options, everything), posted
             again straight to Ollama
  displayed  what the app showed: its own chat path (NexusCore.stream_chat_response), joined the way the
             chat tab joins it. `stored` is the copy the chat tab saves (normalize_assistant_response)

While the app runs, its request and the text Ollama streams back (`received`) are recorded. With a
fixed seed `nexus` should equal `received`; the row says whether it did, so a hidden difference
between what the app says it sends and what it sends cannot go unseen.

Reading a row:
  direct  vs nexus      what the app's prompt changed: the length, the form, a refusal
  received vs displayed what the app changed after the model wrote it
  stopped_by_app        the app answered or stopped the request itself (its one content rule, or a built-in reply)

The refusal columns use modules.behavior_policy.looks_like_model_refusal, the same check that writes the
note under an answer in the app. How often that check is right is measured separately, against
labels made by reading the answers (docs/benchmarks/README.md).

Saved: openings of each answer (not for explicit writing), word counts, why each answer ended, and the
checks. The full texts go only to --texts, a local file for reading; they are not meant for the repository.
Real generations on a CPU: about three minutes per request.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "attribution_check.json"
SEED = 7
DIRECT_GUARD_TOKENS = 2048  # only so a runaway answer cannot run for an hour; reaching it is recorded


def load_prompts(path: Path = FIXTURE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["prompts"]


class _RecordedResponse:
    """A streamed Ollama response that keeps a copy of the text it yields and of its last line."""

    def __init__(self, response: Any, call: dict[str, Any]) -> None:
        self._response, self._call = response, call

    def iter_lines(self, *args: Any, **kwargs: Any):
        for line in self._response.iter_lines(*args, **kwargs):
            if line:
                try:
                    data = json.loads(line)
                except ValueError:
                    data = {}
                self._call["received"] += str(data.get("response", ""))
                if data.get("done"):
                    self._call["done_reason"] = str(data.get("done_reason") or "")
                    self._call["eval_count"] = int(data.get("eval_count") or 0)
            yield line

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


class Recorder:
    """Wraps the session the app posts to Ollama with: records each request as sent and the text that came back.

    The only change made to a request is a fixed seed added to its options, so that the replay can be compared.
    """

    def __init__(self, session: Any, seed: int = SEED) -> None:
        self.session, self.seed = session, seed
        self.calls: list[dict[str, Any]] = []
        self._post = session.post

    def __enter__(self) -> Recorder:
        self.session.post = self._record
        return self

    def __exit__(self, *exc: Any) -> None:
        self.session.post = self._post

    def _record(self, url: str, *args: Any, **kwargs: Any) -> Any:
        payload = kwargs.get("json")
        if isinstance(payload, dict) and str(url).endswith("/api/generate"):
            payload.setdefault("options", {}).setdefault("seed", self.seed)
            call = {"url": str(url), "payload": copy.deepcopy(payload), "received": "", "done_reason": "", "eval_count": 0}
            self.calls.append(call)
            response = self._post(url, *args, **kwargs)
            return _RecordedResponse(response, call) if payload.get("stream") else response
        return self._post(url, *args, **kwargs)

    def chat_call(self) -> dict[str, Any] | None:
        """The request that produced the answer: the streamed one with the most text (checks before it ask for a few tokens)."""

        streamed = [call for call in self.calls if call["payload"].get("stream")]
        return max(streamed, key=lambda call: len(call["received"])) if streamed else None


def generate(base_url: str, payload: dict[str, Any], timeout: float = 1800.0, session: Any = None) -> dict[str, Any]:
    """One non-streamed /api/generate call: the text, why it ended, how many tokens, and how long it took."""

    body = dict(payload, stream=False)
    started = time.perf_counter()
    answer = (session or requests).post(f"{base_url}/api/generate", json=body, timeout=(10.0, timeout))
    answer.raise_for_status()
    data = answer.json()
    return {
        "text": str(data.get("response") or ""),
        "done_reason": str(data.get("done_reason") or ""),
        "eval_count": int(data.get("eval_count") or 0),
        "seconds": round(time.perf_counter() - started, 1),
    }


def direct_payload(model: str, text: str, app_payload: dict[str, Any] | None, seed: int = SEED) -> dict[str, Any]:
    """The request alone, with the app's temperature and context window (so the model is not reloaded) and the same seed."""

    app_options = dict((app_payload or {}).get("options") or {})
    options: dict[str, Any] = {"seed": seed, "num_predict": DIRECT_GUARD_TOKENS}
    for key in ("temperature", "num_ctx", "top_p", "top_k", "repeat_penalty"):
        if key in app_options:
            options[key] = app_options[key]
    payload: dict[str, Any] = {"model": model, "prompt": text, "options": options}
    if app_payload and app_payload.get("keep_alive"):
        payload["keep_alive"] = app_payload["keep_alive"]
    return payload


def _words(text: str) -> int:
    return len((text or "").split())


def _opening(text: str, keep: bool) -> str:
    return " ".join((text or "").split())[:160] if keep else "[not stored: explicit writing was asked for]"


def describe(text: str, done_reason: str, keep: bool) -> dict[str, Any]:
    from modules.behavior_policy import looks_like_model_refusal

    return {
        "words": _words(text),
        "ended": done_reason or "",
        "cut_by_length_limit": done_reason == "length",
        "reads_like_refusal": bool(text.strip()) and looks_like_model_refusal(text),
        "opening": _opening(text, keep),
    }


def check_one(core: Any, prompt: dict[str, Any], settings: dict[str, Any], *, model: str, base_url: str, session: Any, replay: bool = True, direct: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """One request three ways. Returns the row to save and the full texts (for the local file only)."""

    from ui.chat_tab import normalize_assistant_response

    keep = bool(prompt.get("store_opening", True))
    with Recorder(session) as recorder:
        started = time.perf_counter()
        displayed = "".join(core.stream_chat_response(prompt["text"], [], dict(settings))).strip()
        app_seconds = round(time.perf_counter() - started, 1)
    stored = normalize_assistant_response(displayed)
    chat = recorder.chat_call()
    result = dict(core.last_provider_result or {})
    provider = str(result.get("provider") or "")
    texts: dict[str, Any] = {"id": prompt["id"], "displayed": displayed, "stored": stored}
    row: dict[str, Any] = {
        "id": prompt["id"],
        "group": prompt["group"],
        "held_out": bool(prompt.get("held_out")),
        "app": {
            "provider": provider,
            "model": str(result.get("model") or ""),
            "seconds": app_seconds,
            "content_rule_stage": str((getattr(core, "last_content_rule", None) or {}).get("stage") or ""),
            "model_calls": len(recorder.calls),
            "stopped_by_app": chat is None or provider == "content_rule",
        },
        "displayed": describe(displayed, (chat or {}).get("done_reason", ""), keep),
        "stored_equals_displayed": stored == displayed,
    }
    if chat is None:
        return row, texts
    options = dict(chat["payload"].get("options") or {})
    row["app"]["request"] = {
        "prompt_characters": len(str(chat["payload"].get("prompt") or "")),
        "system_field": "system" in chat["payload"],
        "num_predict": options.get("num_predict"),
        "num_ctx": options.get("num_ctx"),
        "temperature": options.get("temperature"),
        "seed": options.get("seed"),
    }
    row["received"] = describe(chat["received"], chat["done_reason"], keep)
    row["displayed_equals_received"] = displayed == chat["received"].strip()
    texts.update(received=chat["received"], request=chat["payload"])
    if replay:
        again = generate(base_url, chat["payload"], session=session)
        row["nexus"] = describe(again["text"], again["done_reason"], keep)
        row["nexus"]["seconds"] = again["seconds"]
        row["nexus_equals_received"] = again["text"].strip() == chat["received"].strip()
        texts["nexus"] = again["text"]
    if direct is None:
        alone = generate(base_url, direct_payload(model, prompt["text"], chat["payload"]), session=session)
        direct = describe(alone["text"], alone["done_reason"], keep)
        direct["seconds"] = alone["seconds"]
        texts["direct"] = alone["text"]
    row["direct"] = direct
    return row, texts


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(key: str, test) -> list[str]:
        return [row["id"] for row in rows if key in row and test(row[key])]

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row["group"], {"asked": 0, "words_direct": [], "words_displayed": []})
        group["asked"] += 1
        if "direct" in row:
            group["words_direct"].append(row["direct"]["words"])
        group["words_displayed"].append(row["displayed"]["words"])
    for group in groups.values():
        for key in ("words_direct", "words_displayed"):
            values = group.pop(key)
            group[f"median_{key}"] = sorted(values)[len(values) // 2] if values else None
    return {
        "asked": len(rows),
        "stopped_by_app": [row["id"] for row in rows if row["app"]["stopped_by_app"]],
        "reads_like_refusal": {
            "direct": count("direct", lambda part: part["reads_like_refusal"]),
            "nexus": count("nexus", lambda part: part["reads_like_refusal"]),
            "displayed": count("displayed", lambda part: part["reads_like_refusal"]),
        },
        "cut_by_length_limit": {
            "direct": count("direct", lambda part: part["cut_by_length_limit"]),
            "displayed": count("displayed", lambda part: part["cut_by_length_limit"]),
        },
        "changed_after_the_model": [row["id"] for row in rows if row.get("displayed_equals_received") is False],
        "stored_differs_from_displayed": [row["id"] for row in rows if not row["stored_equals_displayed"]],
        "replay_differs_from_what_the_app_received": [row["id"] for row in rows if row.get("nexus_equals_received") is False],
        "by_group": groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="dolphin3:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--no-replay", action="store_true", help="skip posting the app's request again")
    parser.add_argument("--direct-from", type=Path, help="reuse the direct answers of an earlier run (same model, seed and fixture)")
    parser.add_argument("--save", type=Path)
    parser.add_argument("--texts", type=Path, help="local file for the full answers and requests (not for the repository)")
    parser.add_argument("--label", default="", help="a name for this run, saved with it")
    args = parser.parse_args(argv)

    from behavior_check import chat_settings  # tools/behavior_check.py, next to this file: the same chat settings
    from modules import provider_router
    from modules.nexus_core import NexusCore

    earlier: dict[str, Any] = {}
    if args.direct_from:
        earlier = {row["id"]: row["direct"] for row in json.loads(args.direct_from.read_text(encoding="utf-8"))["rows"] if "direct" in row}
    prompts = [prompt for prompt in load_prompts() if not args.only or prompt["id"] in args.only]
    core, settings = NexusCore(), chat_settings(args.model, args.base_url)
    rows, texts = [], []
    for prompt in prompts:
        try:
            row, text = check_one(
                core, prompt, settings, model=args.model, base_url=args.base_url, session=provider_router.OLLAMA_SESSION,
                replay=not args.no_replay, direct=earlier.get(prompt["id"]),
            )
        except Exception as exc:  # one failed request is recorded, not fatal
            row, text = {"id": prompt["id"], "group": prompt["group"], "error": f"{type(exc).__name__}: {exc}", "app": {"stopped_by_app": False}, "displayed": {"words": 0}, "stored_equals_displayed": True}, {"id": prompt["id"]}
        rows.append(row)
        texts.append(text)
        shown = row.get("displayed", {})
        print(
            f"{row['id']:<9} direct {row.get('direct', {}).get('words', '-'):>5}w {row.get('direct', {}).get('ended', ''):<6} "
            f"app {shown.get('words', '-'):>5}w {shown.get('ended', ''):<6} cap {row.get('app', {}).get('request', {}).get('num_predict', '-'):>5} "
            f"same-as-replay {row.get('nexus_equals_received', '-')!s:<5} refusal d/a {row.get('direct', {}).get('reads_like_refusal', '-')!s:<5}/{shown.get('reads_like_refusal', '-')!s:<5} "
            f"{row.get('error', '')}",
            flush=True,
        )
        if args.texts:  # written after every request, so a stopped run keeps what it had
            args.texts.parent.mkdir(parents=True, exist_ok=True)
            args.texts.write_text(json.dumps(texts, indent=1, ensure_ascii=False), encoding="utf-8")
    result = {"label": args.label, "model": args.model, "seed": SEED, "date": time.strftime("%Y-%m-%d"), "summary": summarize(rows), "rows": rows}
    print(json.dumps(result["summary"], indent=1))
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes((json.dumps(result, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"saved {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
