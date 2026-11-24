# Cognitive Nexus 2.0: what works, and how we know

Last verified: **2026-11-23**, on Windows 11 with a 6-core laptop CPU, integrated graphics (no NVIDIA GPU), 32 GB RAM, Python 3.13 and Ollama running `dolphin3:8b`.

This page replaces the readiness claims in the older reports in this repository (see [Older documents](#older-documents)). Update it when a feature is tested again or its status changes.

## How to read the table

- **Tests**: covered by the automated suite (`python -m pytest`, run by CI on every push). "Mocked" means the tests replace the outside service, so they show the code path works, not the service.
- **Live**: someone ran it for real on the date above and looked at the result.
- A feature with neither is written but unverified.

| Feature | Tests | Live | Notes |
|---|---|---|---|
| Chat with a local Ollama model | Yes | Yes | 17-27 s per reply on CPU |
| Web search in chat, with sources | Yes | Yes | 35-55 s on CPU. Needs a search source to answer; see below |
| Remember / recall / forget commands | Yes | Yes | Facts record how they are known; a new value replaces the old one; "forget" reaches history and snapshots |
| Export, encrypted backup, restore, wipe | Yes | Partly | The command-line tool was run through a full backup, wipe and restore. In the browser only the panel's display was checked |
| Prompt sized to the model's window | Yes | Yes | A conversation that used to be cut to 1,026 tokens is read whole (1,690) |
| Image generation with local Diffusers | Mocked | Yes | About 3 minutes per 512x512 image on CPU. One picture at a time; when it would not fit in memory beside the chat model, the chat model is taken out first (measured 2026-11-24: lowest free memory for a 768x768 picture 0.35-1.8 GB before, 8.8 GB after; the next chat answer then takes about 12 s longer) |
| Reality-First Research and claim check | Yes | Partly | The claim check's judgement was measured with the real model on labelled passages (about 4 in 5 right, see `docs/benchmarks`). A whole run on live search results with model synthesis was not observed |
| Web text cannot instruct the model | Yes | Yes | 12 pages carrying planted instructions, answered by the real model: obeyed 6 before, 0 now (`docs/benchmarks`) |
| Chat web answers stay within their sources | Yes | Yes | Frozen pages, real model: 9 of 9 right, nothing invented in 12; but it said "the results do not say" for only 1 of 3 questions the pages could not answer |
| Web Research tab (full report) | Yes | Partly | Ran, but search was rate-limited each time, so a report with sources was not observed |
| Bloodhound search | Mocked | No | |
| Files / Knowledge storage and retrieval | Yes | Yes | Search by meaning with the `all-minilm` embedding model through Ollama: right document first for 91% of reworded questions, about 20 ms each. Without an embedding model it matches words only and says so |
| Agent tools: sandbox, Git workspaces, approvals, action history | Yes | Yes | On Windows the sandbox was seen refusing writes outside the task folder and ending runaway process trees. Not containers: reading and network access are not confined (see below) |
| Coding agent: reproduce a failing test, edit, test, review, commit | Yes | Yes | Real model on small seeded bugs it was never tuned on: 4 of 9 fixed, the unsolvable one handed to a person, no failure reported as a success, the planted instruction ignored. (7 of 9 on the first set, which the harness was improved against.) All five misses were the 8B model's own wrong fixes (`docs/benchmarks`) |
| Agent tab in the app: give a task, see every action, approve, accept | Yes | Yes | Driven through the real interface in tests, with the real loop behind it and a scripted model. Not yet clicked through by hand in a browser with the real model |
| Agent environments: a virtual environment per task, packages from the repository's own requirement files | Yes | Yes | A real install from PyPI inside the sandbox was run once (9 s); the tests use a local package folder. Python only; packages are wheels only by default (no build scripts run) |
| Answers get the length asked for; a cut-off or a length the model did not keep to is said under the answer | Yes | Yes | Real model, seven requests with a stated length: none cut off after the change (three before), see docs/GENERATION_RELIABILITY_REPORT.md. The model itself is not exact about length |
| Arithmetic worked out by the app; word problems set up by the model and computed by the app | Yes | Yes | Real model: 27 of 27 on the owner's set (24 before), 15 of 18 on six unseen word problems, 7 of 18 without the change (docs/FACTUAL_RELIABILITY_REPORT.md) |
| Web research works out what is meant, has the model judge doubtful results, refines, searches legal and availability context, flags unsupported names | Yes | Yes | Real model over fixed pools of results in three rounds, each measured on questions written before it ran, and live on the owner's question (docs/WEB_RESEARCH_QUALITY_REPORT.md) |
| The app's own time: first visit, each click, a chat turn | Yes | Yes | Measured with a stand-in model: first visit 4.95 s (16.0 s before), each click 0.42 s (1.81 s), a chat turn's own part 0.58 s (1.97 s). Servers on this computer are addressed as 127.0.0.1 (a new connection to "localhost" waited 2 s on Windows) |
| Which page states each sentence of a web answer | Yes | Partly | In Diagnostics. Measured on labelled sentences: the local model's own sentences matched to the right page 27 of 27, paraphrases 8 of 12, 4 of 22 unsupported sentences let through. Not yet seen in the running app on a live question |
| Diagnostics: how the last answer was made | Yes | Yes | Shows limits, lengths, stop reason, timings, content-rule stage, calculation, search plan, what was searched, judged and left out. Not clicked through by hand after the change |
| One list of what it can do: tools with their shapes and needs, apps found, linked accounts | Yes | Yes | Looked for on this machine for real (Git, Ollama and its models, search sources, image backends). In the Agent tab and `python -m agent tools` |
| What a model can do: context length, tool calls, structured output, vision | Yes | Yes | Local models: asked from the Ollama server (checked live for the installed model). Cloud models: the provider's published figures, not checked against the live service |
| Tool calls for the local model, one JSON step at a time held to a schema | Yes | Yes | Real model, requests it was not tuned on: right tool with fitting arguments in 11 of 12, every reply usable. Used by `python -m agent ask`; the chat tab still decides by rules |
| A change to the app is measured against what it replaces | Yes | Yes | Model-free evaluations on two versions; run for real on a copy of this repository, where a planted regression was reported as worse. It shows that the mechanisms still work, not that answers got better |
| Linked accounts: stored credentials, a permission per use, renewal, unlinking | Yes | Yes | Windows encryption checked for real on this machine. Renewal, sign-in with a code and cancelling at the service were run against a stand-in on this machine that follows the published OAuth rules: no real service has been contacted |
| Agent publishing: push its own branch, open a draft pull request | Yes | No | A real push to a local Git remote and real HTTP to a local stand-in for the GitHub API. github.com was not called: no token |
| Background jobs, schedules, reminders, page watching | Yes | No | Tested with a real database across simulated restarts; not left running for days |
| One content rule (no sexual content involving minors), no topic filters | Yes | Yes | Real model as the judge: on requests the check was never adjusted on, 36 of 36 forbidden requests stopped, 43 of 44 ordinary ones answered. See `docs/OWNER_CONTROL.md` for what it does not catch |
| Legitimate questions are not stopped by the app | Yes | Yes | Real model, 20 questions on adult subjects, drugs, money, controversial subjects, the owner's own style instructions and ordinary questions about minors: 0 stopped by the app, 0 declined by the model, every message delivered unchanged (`docs/benchmarks`) |
| Your own messages are never scanned or fenced; handling of outside text is a setting | Yes | Yes | Real model, 12 pages with planted instructions: obeyed 0 with the default, 6 with marking only, 7 with no handling |
| Behaviour settings: saved, shown word for word, used on the next message | Yes | Yes | In the running app: text and settings saved, app stopped and started, the saved text was in the prompt of the next chat message |
| Image generation through Automatic1111 or ComfyUI | Mocked | No | Neither was installed on the test machine |
| OpenAI and Anthropic providers | Mocked | No | No API keys were available, so neither has answered a real request. The Anthropic request was rewritten for the current API and its retired default model replaced (`claude-sonnet-5-5`). OpenAI's default `gpt-4.1-mini` works until 2027-01-14 according to OpenAI's deprecation page |
| Cloud fallback stays off unless chosen | Yes | Partly | Tested with stand-in cloud providers. Live, only the no-key case could be run: with the local model unreachable, the reply said what failed |
| "Who answered" label and provider test prompt | Yes | Yes | Seen on a real reply: "Answered by Ollama / dolphin3:8b, stayed on this machine, 31.4 s" |
| Hugging Face local provider | Detection only | No | |
| Onion search | No | No | Off by default |
| Android app | n/a | No | Separate repository. It needs this engine running on a computer; it does not run models on the phone |

## Known limits

- **What the assistant may say** is set by the owner (Settings, Behaviour). The app has one content rule and no topic filters; a model can still decline something on its own, and the line under the answer then says it was the model. A small local model follows a style instruction unevenly: "talk like a pirate" was followed 4 times in 5, "call me skipper" once.
- **The one content rule's check** picks requests out with a list of English words before asking the model. A request in another language, or in unusual wording that also asks for nothing to be written, is not checked. It reads the request and the last four turns, never what the model wrote. Its numbers are for `dolphin3:8b`.
- **Pictures** are held to a stricter line than the owner's rule: none that would show anyone under 18 nude or undressed, whatever the scene. An innocent picture of a child can be refused (1 of 21 in the measurement). The check reads the request, not the picture.
- **Web search** scrapes free search pages by default, and they rate-limit often. Set `SEARXNG_URL` or `BRAVE_SEARCH_API_KEY` for a dependable source. Wikipedia is the last fallback and cannot answer "latest version" questions.
- **Research verdicts** come from rules about wording, with the model re-reading the passages counted as support. Measured on passages the rules were not written for: about four in five judged correctly, and one passage in ten wrongly counted as supporting a claim. They quote every passage with the reason it was counted, never say more than "LIKELY", and are not calibrated probabilities. A passage that says the same thing in other words is missed.
- **Hidden instructions in web pages**: by default, sentences aimed at an AI model are removed and the rest is fenced as untrusted before the model sees it. That stopped all twelve test attacks on the local model; it is a layer, not a guarantee. The handling is a setting; with marking only, 6 of the 12 were obeyed.
- **When pages do not contain the answer**, the small local model tends to recite what they do contain instead of saying so. It does not invent an answer.
- **Answers from a small local model** can state outdated facts. Web answers flag version numbers and years that are not in their sources, but other errors can get through.
- **Saved data** is in JSON files changed under a lock and, for the knowledge index and the agent's records, SQLite databases, so two programs writing at once do not overwrite each other.
- **Pictures and memory**: what a picture needs is measured at 512x512 and 768x768 on one machine and estimated for other sizes (above 768x768 the estimate is a lower bound). A picture cannot be cancelled from the Images tab while it is being made; it stops at its time limit (30 minutes).
- **Live data is not encrypted.** Backups can be; the files the app works on are plain files. Use full-disk encryption if the computer is shared or portable.
- **History in chat prompts.** On the default settings many simple turns are answered without earlier messages, which keeps a CPU-only machine responsive but means the model does not always see the conversation.
- **Knowledge search** needs an embedding model in Ollama (for example `ollama pull all-minilm`, 45 MB) to search by meaning. The app does not download one itself; without it, search matches words and says so.
- **Agent sandbox**: programs the agent runs get a clean environment, memory and time limits and, on Windows, cannot write outside the task's folder (the operating system refuses). They can still read your files and use the network. On Linux and macOS writes are not confined either. Do not point the agent at a repository whose code you would not run yourself.
- **URL fetching** refuses local and private addresses, but does not pin DNS between the check and the connection.
- **Cloud providers** have never been run against the real services from this repository. Use "Send a test prompt" in Diagnostics after adding a key.
- **Cost figures** for cloud answers are estimates from published prices; the provider's bill is the real number.

## Repositories

- **This repository** is the engine and the desktop (Streamlit) app. It is the one under active development.
- `Nmoreland51-Nmoreland51-cognitive-nexus` is an earlier snapshot from March 2026.
- `cognitive-nexus-android` is the Android client. It talks to a backend running on a computer.

## Older documents

These files describe the project as it was in mid-2026 and are kept for history. Where they disagree with this page, this page is current.

- `FINAL_PROJECT_AUDIT.md` and `COGNITIVE_NEXUS_UPGRADE_SUMMARY.md` say the project is ready for commercial release and that 2 of 2 tests pass. The suite now has more than 1,100 tests, and the limits above still apply.
- `QUICK_START.md` describes a packaged `.exe` build. The scripts it names (`build_executable.bat`, `launch_cognitive_nexus.bat`) are not in this repository. Use the Install and Run sections of `README.md`.
