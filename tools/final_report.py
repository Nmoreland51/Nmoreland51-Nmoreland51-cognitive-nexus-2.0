"""Write docs/FINAL_VERIFICATION_REPORT.md from the ledger, the restriction register and the saved measurements.

    python tools/final_report.py          write the report
    python tools/final_report.py check    exit 1 when the report on disk is not what would be written now

The counts, the item tables, the list of limits the owner did not ask for and the measurement
table are read from the files they come from (docs/backlog/status.json, docs/backlog/items.json,
docs/backlog/restrictions.json, docs/benchmarks/*.json), so the report cannot say something else
than they do. The sentences around them are written here by hand.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "FINAL_VERIFICATION_REPORT.md"
BENCHMARKS = ROOT / "docs" / "benchmarks"

# Why an item that is not complete is not complete. Everything not listed here simply has not
# been finished: nothing outside this machine or this work is missing for it.
NEEDS_THE_OWNER = {"001", "003", "004", "023", "072", "094", "095", "096", "097", "113", "129", "135", "136", "145", "146"}
NEEDS_WHAT_THIS_MACHINE_LACKS = {
    "014": "an OpenAI or Anthropic API key",
    "051": "an OCR engine",
    "057": "Docker or WSL",
    "062": "a GitHub token",
    "065": "a GitHub token",
    "077": "Docker or WSL",
    "079": "a real account to try it against",
    "081": "an Android phone, or an emulator and a JDK",
    "085": "a phone and a private network",
    "086": "an Android phone, or an emulator and a JDK",
    "090": "an Android phone, or an emulator and a JDK",
    "092": "an Android phone, or an emulator and a JDK",
    "093": "ComfyUI or Automatic1111 running, and a phone",
    "109": "Docker or WSL",
    "128": "an Android phone, or an emulator and a JDK",
    "126": "an OpenAI or Anthropic key for the cloud half",
    "134": "code-signing certificates and Android signing keys",
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cell(text: str, limit: int = 0) -> str:
    text = " ".join(str(text).replace("|", "/").split())
    return text if not limit or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def ledger() -> tuple[dict[str, Any], dict[str, Any], dict[int, str]]:
    items = _json(ROOT / "docs" / "backlog" / "items.json")
    return items["items"], _json(ROOT / "docs" / "backlog" / "status.json"), {section["number"]: section["title"] for section in items["sections"]}


def why_open(item_id: str, entry: dict[str, Any]) -> str:
    if entry["status"] in {"COMPLETE", "NOT APPLICABLE"}:
        return ""
    if item_id in NEEDS_THE_OWNER:
        return "your decision"
    if item_id in NEEDS_WHAT_THIS_MACHINE_LACKS:
        return f"needs {NEEDS_WHAT_THIS_MACHINE_LACKS[item_id]}"
    return "not finished"


def measurements() -> list[tuple[str, str, str]]:
    """(what was measured, the result, the file) for every saved measurement that exists."""

    rows: list[tuple[str, str, str]] = []

    def add(name: str, make: Any, title: str) -> None:
        path = BENCHMARKS / name
        if not path.exists():
            return
        try:
            rows.append((title, make(_json(path)), name))
        except (KeyError, IndexError, TypeError, ValueError):
            rows.append((title, "see the file", name))

    def content_rule(data: dict[str, Any]) -> str:
        unseen = [data["sets"][name]["summary"] for name in ("heldout", "heldout2", "heldout3")]
        stop, stopped = sum(s["should_stop"] for s in unseen), sum(s["stopped"] for s in unseen)
        answer, answered = sum(s["should_answer"] for s in unseen), sum(s["answered"] for s in unseen)
        return f"On requests it was never adjusted on: {stopped} of {stop} forbidden requests stopped, {answered} of {answer} ordinary ones answered"

    def behaviour(data: dict[str, Any]) -> str:
        s = data["summary"]
        return f"{s['asked']} legitimate questions on sensitive subjects: {len(s['stopped_by_app'])} stopped by the app, {len(s['declined_by_model'])} declined by the model"

    def injection(data: dict[str, Any]) -> str:
        s = data["summary"]
        return f"Planted instructions obeyed: {s['attacks_obeyed_now']} of {s['attacks']} (it was {s['attacks_obeyed_before']} before); the real fact still answered in {s['facts_kept_now']} of {s['cases']}"

    def research(data: dict[str, Any]) -> str:
        chat = data["chat_answers"]
        outside = chat["answers_with_something_outside_their_sources"]
        return (
            f"Questions the sources answer: {chat['correct']} of {chat['answerable']} right, "
            + ("nothing added from outside the sources. " if not outside else f"{outside} of {chat['answerable'] + chat['unanswerable']} with something from outside the sources. ")
            + f"Questions they do not answer: it said so in {chat['said_so']} of {chat['unanswerable']}"
        )

    def quality(data: dict[str, Any]) -> str:
        s = data["summary"]
        length, unseen, content = s["length"], s["arithmetic_heldout"], s["content"]
        return (
            f"Ordinary requests wrongly stopped by the content rule {content['ordinary_wrongly_stopped']} of {content['ordinary']}; "
            f"answers cut off {length['stopped_at_the_token_limit']} of {length['requests']}, within the asked length {length['within_range']} of {length['requests']}; "
            f"word problems written afterwards {unseen['right']} of {unseen['answers']} right"
        )

    def relevance(data: dict[str, Any]) -> str:
        unseen = data["summary"]["heldout3"]
        dropped = unseen["new"]["relevant_results_dropped"]
        return (
            f"Unseen ambiguous questions: {unseen['new']['results_about_another_meaning']} results about another meaning reached the model "
            f"({unseen['old']['results_about_another_meaning']} when searched as typed); {dropped} relevant result{'' if dropped == 1 else 's'} wrongly dropped"
        )

    def stance(data: dict[str, Any]) -> str:
        rules, both = data["rules"]["held_out"], data["rules_and_model"]["held_out"]["supporting_passages_only"]
        return (
            f"Unseen passages: rules alone {rules['correct']} of {rules['items']} right with {rules['false_supports']} wrongly counted as support; "
            f"with the model re-reading, {both['correct']} of {both['items']} and {both['false_supports']}"
        )

    def retrieval(data: dict[str, Any]) -> str:
        modes = data["runs"][0]["modes"]
        return (
            f"Questions worded differently from the text: right passage first in {modes['hybrid']['paraphrase']['hit@1']:.0%} "
            f"(keywords alone: {modes['keyword']['paraphrase']['hit@1']:.0%})"
        )

    def agent(data: dict[str, Any]) -> str:
        s = data["summary"]
        return f"{s['solved']} of {s['solvable']} seeded bugs fixed; {s['false_successes']} failures reported as successes; planted instruction obeyed {s['planted_instruction_obeyed']} times"

    def tool_choice(data: dict[str, Any]) -> str:
        s = data["summary"]["heldout"]
        return f"Unseen requests: right tool with fitting arguments in {s['right_tool_and_arguments']} of {s['requests']}; {s['valid_steps']} of {s['requests']} replies usable"

    def speed(data: dict[str, Any]) -> str:
        s, machine = data["summary"], data["hardware"]
        return (
            f"Writes {s['output_tokens_per_second']} tokens a second, reads {s['prompt_tokens_per_second']}; first word after {s['first_word_seconds_new_prompt']} s on a new prompt, "
            f"{s['first_word_seconds_follow_up']} s on a follow-up; {s['peak_ollama_memory_gb']} GB of memory ({machine['cores']} cores, {machine['ram_gb']} GB, graphics card: {machine['gpu']})"
        )

    add("content_rule_dolphin3-8b.json", content_rule, "The one content rule")
    add("behavior_dolphin3-8b.json", behaviour, "Legitimate questions are not stopped")
    add("injection_dolphin3-8b.json", injection, "Instructions hidden in web pages")
    add("research_dolphin3-8b.json", research, "Research answers from fixed sources")
    add("research_relevance_dolphin3-8b.json", relevance, "Which web results reach the model")
    add("quality_after.json", quality, "Your live findings of 2026-11-23, after the corrective phase")
    add("stance.json", stance, "Claim check: what a passage says about a claim")
    add("retrieval_all-minilm.json", retrieval, "Search in your own documents")
    add("agent_heldout_dolphin3-8b.json", agent, "Coding agent, tasks it was never tuned on")
    add("agent_dolphin3-8b.json", agent, "Coding agent, tasks the harness was improved against")
    add("tool_choice_dolphin3-8b.json", tool_choice, "Picking a tool")
    add("speed_dolphin3-8b.json", speed, "Speed on this machine")
    return rows


def limits_not_asked_for() -> list[tuple[str, str, str]]:
    """Active mechanisms whose decision is still the owner's to make: (id, name, can it be changed)."""

    register = _json(ROOT / "docs" / "backlog" / "restrictions.json")
    return [
        (entry["id"], entry["name"], entry.get("configurable", ""))
        for entry in register["entries"]
        if entry.get("status") == "active" and str(entry.get("owner_decision", "")).startswith("Pending")
    ]


HOW_CHECKED = """\
| How it was checked | What that means | What was checked this way |
|---|---|---|
| Run for real with the real model | The app's own code, the local model `dolphin3:8b`, on this computer, results saved in `docs/benchmarks` | Everything in the table below |
| Run for real without a model | The real code on real files, processes, Git repositories and Windows itself | Saved data under two programs at once, backups and restore, the knowledge index, the agent's sandbox, Git checkouts, a package install from the public index, the Windows encryption of stored credentials |
| Automated tests | Tests that run on every push, on Linux and on Windows | Almost everything else. A model, where one is needed, is played by fixed replies, so these show that the app's own logic is right, not what a model will say |
| Against a stand-in only | The other side was a small program on this machine that follows the published rules | GitHub (pushes, pull requests, CI results), sign-in and renewal of credentials, OpenAI and Anthropic requests |
| Not checked | Could not be run at all here | Anything on a phone; any real outside service; the app clicked through by hand in a browser after the latest changes |
"""

NEEDS_YOU = """\
- **The picture rule is stricter than yours.** You asked for one content rule. For pictures the app also refuses anything that would show a person under 18 nude or undressed, whatever the scene (a baby in a bath, for example). That line is mine, not yours; it is marked as mine wherever it appears (`docs/OWNER_CONTROL.md`, D7). One ordinary request in the tests is wrongly refused because of it.
- **Two defaults were chosen without your answer:** the coding agent works alone but asks before it publishes anything (D5), and impossible things are answered in full and labelled rather than held back (D6). Both are settings in Settings, Behaviour.
- **Sixteen private files are still in the repository and its history** (chat history, a profile, images), from before this work. Removing them for good means rewriting history and a forced push. I have not done it: it needs your go-ahead.
- **Nothing is merged.** The audit work is on the branch `fix/chat-speed-web-search-images`; the corrective quality phase is on `quality/corrective-phase`, offered to it as a draft pull request. Merging either, merging into `main`, tagging a release and changing branch protection are yours.
- **The phone repository has one new branch,** `owner-control-content-rule`, with one fix. Its open pull requests and branches are untouched and still need your decision.
- **I installed one thing into Ollama:** the 45 MB search model `all-minilm`. `ollama rm all-minilm` removes it; search in your documents then falls back to keywords.
- **Decisions the audit leaves to you:** which repository is the main one; whether the default product is an assistant, a research tool, a coding agent or all three; whether you want voice, picture input or several agents; whether you want the assistant to drive a browser.
- **The rules listed under "Limits you did not ask for" below** are in force until you say otherwise.
"""

NOT_TO_OVERTRUST = """\
- **The coding agent fixes under half of small bugs with this model.** Four of nine on tasks it was never tuned on. An earlier figure of seven of nine was measured on the tasks the harness had been improved against and overstated it. What does hold whatever the model does: it never reported a failure as a success and never edited the tests.
- **The model is not exact about length.** With the app no longer cutting answers short, a requested length is passed on and nothing is cut off, but the model itself overshoots short pieces and undershoots long ones (see docs/GENERATION_RELIABILITY_REPORT.md).
- **Word problems depend on the model setting them up.** The app works the arithmetic out exactly and shows the expression, but a wrong setup gives a wrong answer (one of six unseen problems, docs/FACTUAL_RELIABILITY_REPORT.md).
- **Web answers to "the best ..." questions are thin.** The search now finds what you mean (no lawn care for your Omaha question), but the model still answers such a question in one sentence, that the results do not say which is best, without saying what they do offer. The search for legal or availability context is built and never runs with this model: it always leaves it empty (docs/WEB_RESEARCH_QUALITY_REPORT.md).
- **The model's judgement of search results is sometimes wrong.** On questions it was never tuned on it threw out 7 of 51 relevant results and let 1 of 33 off-topic ones through.
- **The model guesses when it cannot check.** In one tool run the web search was refused by a data rule and the model still stated the answer as fact. The rules control where your data goes; they do not make an 8B model careful.
- **When the sources do not answer a question, the model usually answers anyway.** It said "the sources do not say" in one of three such questions.
- **The claim check wrongly counts some passages as support.** Two of 47 unseen passages with the model re-reading, five without.
- **The sandbox is not a container.** Programs the agent runs cannot write outside the task's folder on Windows, but they can read your files and use the network. Do not point the agent at code you would not run yourself.
- **Stored credentials are encrypted only on Windows.** Elsewhere they are in a file only your user can read, and the app says so.
- **Cloud models were never called.** The requests for OpenAI and Anthropic follow the current published formats and are tested with the service played by a stand-in; no key was available to try them.
- **The speeds are this machine's.** No graphics card was found; sizes other than the installed model's are arithmetic, not measurements.
- **Chat still decides by rules when to search the web.** The tool-calling loop is used by `python -m agent ask`, not by the chat tab.
"""

HOW_TO_CHECK = """\
```
python tools/run_checks.py                         # lint, types, secrets, ledger, register, the whole test suite
python tools/audit_ledger.py check                 # every one of the 146 items has a status and evidence
python tools/restriction_register.py check         # every limit in the code is in the register, and the other way round
python tools/final_report.py check                 # this report says what the ledger and the saved results say
python tools/evaluation_gate.py compare --base main            # is this branch worse than main on the fixed evaluations
python tools/speed_benchmark.py --model dolphin3:8b --compare docs/benchmarks/speed_dolphin3-8b.json
```

The measurements with the model are repeated with the tools named in `docs/benchmarks/README.md`. Each saved result is tied to the code it was made with: when a prompt changes, a test fails until the measurement is run again.
"""


def build() -> str:
    items, status, sections = ledger()
    counts = Counter(status[item_id]["status"] for item_id in items)
    open_items = [item_id for item_id in items if status[item_id]["status"] in {"PARTIAL", "MISSING"}]
    reasons = Counter(why_open(item_id, status[item_id]).split(" ")[0] for item_id in open_items)
    owner_groups = {key: item.get("group", "") for key, item in _json(ROOT / "docs" / "backlog" / "owner_control.json")["items"].items()}
    owner_points = {key: value for key, value in status.items() if not key[:1].isdigit() and owner_groups.get(key) != "quality"}
    owner_counts = Counter(value["status"] for value in owner_points.values())
    quality_counts = Counter(value["status"] for key, value in status.items() if owner_groups.get(key) == "quality")
    lines = [
        "# Final verification report",
        "",
        "Generated by `python tools/final_report.py` from the audit ledger, the restriction register and the saved measurements. Do not edit by hand.",
        "",
        "## The short version",
        "",
        f"The audit has 146 items. **{counts['COMPLETE']} are complete, {counts['PARTIAL']} are partly done, {counts['MISSING']} are not done** and {counts['NOT APPLICABLE']} does not apply. The audit is not finished.",
        "",
        f"Of the {len(open_items)} items that are not complete:",
        "",
        f"- **{reasons['your']} wait for you**: a decision or an approval only you can give.",
        f"- **{reasons['needs']} need something this computer does not have**: a phone, an API key or token, Docker, an OCR engine, signing certificates.",
        f"- **{reasons['not']} are simply not finished.** Nothing outside is missing for them; there was not time.",
        "",
        f"Your own instructions on control of the assistant ({len(owner_points)} points, in `docs/owner/`): {owner_counts['COMPLETE']} complete, {owner_counts['PARTIAL']} partly done.",
        "",
        f"Your seven live findings of 2026-11-23 (CN-QA-001 to 007, `docs/QUALITY_FINAL_VERIFICATION.md`): {quality_counts['COMPLETE']} fixed and verified, {quality_counts['PARTIAL']} improved but not fully met, {quality_counts['MISSING']} not done.",
        "",
        "\"Complete\" means built, run, and covered by a test or a saved measurement, with its limits written next to it in the ledger. It does not mean perfect: several complete items carry limits, listed under \"Things not to over-trust\".",
        "",
        "Nothing in this work was ever run against a real outside service (GitHub, OpenAI, Anthropic, Brave) or on a phone.",
        "",
        "## How each claim was checked",
        "",
        HOW_CHECKED,
        "## What was measured with the real model",
        "",
        "All with `dolphin3:8b` on this computer, processor only. Where a prompt or rule was improved against one set of examples, the figure given is from a second set it was never adjusted on.",
        "",
        "| What | Result | Saved in `docs/benchmarks/` |",
        "|---|---|---|",
    ]
    lines += [f"| {_cell(title)} | {_cell(result)} | `{name}` |" for title, result, name in measurements()]
    lines += [
        "",
        "How each was measured, and the history of the ones that started out worse, is in `docs/benchmarks/README.md`.",
        "",
        "## What needs you",
        "",
        NEEDS_YOU,
        "## Things not to over-trust",
        "",
        NOT_TO_OVERTRUST,
        "## Limits you did not ask for",
        "",
        "You asked to be told about every limit the app has that you did not request. These are in force and waiting for your decision. None of them is a rule about what may be said; they are permissions for tools and protections for your data and accounts. Each is described in full, with what turning it off would mean, in `docs/OWNER_CONTROL_RESTRICTIONS.md`.",
        "",
        "| | Limit | Can you change it |",
        "|---|---|---|",
    ]
    lines += [f"| {entry_id} | {_cell(name)} | {_cell(configurable, 150)} |" for entry_id, name, configurable in limits_not_asked_for()]
    lines += ["", "## Not finished, with nothing outside missing", "", "These could have been done here and were not.", "", "| Item | State | What the audit asked for |", "|---|---|---|"]
    lines += [f"| {item_id} | {status[item_id]['status'].lower()} | {_cell(items[item_id]['text'])} |" for item_id in open_items if why_open(item_id, status[item_id]) == "not finished"]
    lines += ["", "## Waiting for you", "", "| Item | State | What the audit asked for | What is needed |", "|---|---|---|---|"]
    lines += [f"| {item_id} | {status[item_id]['status'].lower()} | {_cell(items[item_id]['text'])} | {_cell(status[item_id].get('needs', ''), 220)} |" for item_id in open_items if item_id in NEEDS_THE_OWNER]
    lines += ["", "## Needs something this computer does not have", "", "| Item | State | What the audit asked for | What is missing |", "|---|---|---|---|"]
    lines += [f"| {item_id} | {status[item_id]['status'].lower()} | {_cell(items[item_id]['text'])} | {NEEDS_WHAT_THIS_MACHINE_LACKS[item_id]} |" for item_id in open_items if item_id in NEEDS_WHAT_THIS_MACHINE_LACKS]
    lines += ["", "## Every item, by part of the audit", ""]
    for number in sorted(sections):
        mine = [item_id for item_id in items if items[item_id]["section"] == number]
        tally = Counter(status[item_id]["status"] for item_id in mine)
        lines += [f"### {number}. {sections[number]}", "", f"{tally['COMPLETE']} complete, {tally['PARTIAL']} partly done, {tally['MISSING']} not done" + (f", {tally['NOT APPLICABLE']} not applicable" if tally["NOT APPLICABLE"] else "") + ".", "", "| Item | State | What the audit asked for | Why it is open |", "|---|---|---|---|"]
        lines += [f"| {item_id} | {status[item_id]['status'].lower()} | {_cell(items[item_id]['text'])} | {why_open(item_id, status[item_id])} |" for item_id in mine]
        lines.append("")
    lines += ["The evidence, tests and commits for every item are in `docs/AUDIT_146_PROGRESS.md`.", "", "## How to check this yourself", "", HOW_TO_CHECK]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    text = build()
    if arguments[:1] == ["check"]:
        current = REPORT.read_text(encoding="utf-8").replace("\r\n", "\n") if REPORT.exists() else ""
        if current != text:
            print("docs/FINAL_VERIFICATION_REPORT.md is out of date; run: python tools/final_report.py", file=sys.stderr)
            return 1
        return 0
    REPORT.write_bytes(text.encode("utf-8"))
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
