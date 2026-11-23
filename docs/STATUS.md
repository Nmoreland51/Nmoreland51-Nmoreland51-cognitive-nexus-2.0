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
| Image generation with local Diffusers | Mocked | Yes | About 3 minutes per 512x512 image on CPU |
| Reality-First Research and claim check | Yes | Partly | The claim check's judgement was measured with the real model on labelled passages (about 4 in 5 right, see `docs/benchmarks`). A whole run on live search results with model synthesis was not observed |
| Web text cannot instruct the model | Yes | Yes | 12 pages carrying planted instructions, answered by the real model: obeyed 6 before, 0 now (`docs/benchmarks`) |
| Chat web answers stay within their sources | Yes | Yes | Frozen pages, real model: 9 of 9 right, nothing invented in 12; but it said "the results do not say" for only 1 of 3 questions the pages could not answer |
| Web Research tab (full report) | Yes | Partly | Ran, but search was rate-limited each time, so a report with sources was not observed |
| Bloodhound search | Mocked | No | |
| Files / Knowledge storage and retrieval | Yes | Yes | Search by meaning with the `all-minilm` embedding model through Ollama: right document first for 91% of reworded questions, about 20 ms each. Without an embedding model it matches words only and says so |
| Agent tools: sandbox, Git workspaces, approvals, action history | Yes | Yes | On Windows the sandbox was seen refusing writes outside the task folder and ending runaway process trees. Not containers: reading and network access are not confined (see below) |
| Image generation through Automatic1111 or ComfyUI | Mocked | No | Neither was installed on the test machine |
| OpenAI and Anthropic providers | Mocked | No | No API keys were available, so neither has answered a real request. The Anthropic request was rewritten for the current API and its retired default model replaced (`claude-sonnet-5-5`). OpenAI's default `gpt-4.1-mini` works until 2027-01-14 according to OpenAI's deprecation page |
| Cloud fallback stays off unless chosen | Yes | Partly | Tested with stand-in cloud providers. Live, only the no-key case could be run: with the local model unreachable, the reply said what failed |
| "Who answered" label and provider test prompt | Yes | Yes | Seen on a real reply: "Answered by Ollama / dolphin3:8b, stayed on this machine, 31.4 s" |
| Hugging Face local provider | Detection only | No | |
| Onion search | No | No | Off by default |
| Android app | n/a | No | Separate repository. It needs this engine running on a computer; it does not run models on the phone |

## Known limits

- **Web search** scrapes free search pages by default, and they rate-limit often. Set `SEARXNG_URL` or `BRAVE_SEARCH_API_KEY` for a dependable source. Wikipedia is the last fallback and cannot answer "latest version" questions.
- **Research verdicts** come from rules about wording, with the model re-reading the passages counted as support. Measured on passages the rules were not written for: about four in five judged correctly, and one passage in ten wrongly counted as supporting a claim. They quote every passage with the reason it was counted, never say more than "LIKELY", and are not calibrated probabilities. A passage that says the same thing in other words is missed.
- **Hidden instructions in web pages**: sentences aimed at an AI model are removed and the rest is fenced as untrusted before the model sees it. That stopped all twelve test attacks on the local model; it is a layer, not a guarantee.
- **When pages do not contain the answer**, the small local model tends to recite what they do contain instead of saying so. It does not invent an answer.
- **Answers from a small local model** can state outdated facts. Web answers flag version numbers and years that are not in their sources, but other errors can get through.
- **Saved data** is in JSON files changed under a lock and, for the knowledge index and the agent's records, SQLite databases, so two programs writing at once do not overwrite each other.
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

- `FINAL_PROJECT_AUDIT.md` and `COGNITIVE_NEXUS_UPGRADE_SUMMARY.md` say the project is ready for commercial release and that 2 of 2 tests pass. The suite now has about 500 tests, and the limits above still apply.
- `QUICK_START.md` describes a packaged `.exe` build. The scripts it names (`build_executable.bat`, `launch_cognitive_nexus.bat`) are not in this repository. Use the Install and Run sections of `README.md`.
