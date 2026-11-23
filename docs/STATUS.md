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
| Remember / recall / forget commands | Yes | Yes | |
| Image generation with local Diffusers | Mocked | Yes | About 3 minutes per 512x512 image on CPU |
| Reality-First Research and claim check | Yes | Partly | Claim check run on live search results without model synthesis. A full run with synthesis was not tested |
| Web Research tab (full report) | Yes | Partly | Ran, but search was rate-limited each time, so a report with sources was not observed |
| Bloodhound search | Mocked | No | |
| Files / Knowledge storage and retrieval | Yes | No | |
| Image generation through Automatic1111 or ComfyUI | Mocked | No | Neither was installed on the test machine |
| OpenAI and Anthropic providers | Detection only | No | No API keys were available. Default model names were not checked against the current APIs |
| Hugging Face local provider | Detection only | No | |
| Onion search | No | No | Off by default |
| Android app | n/a | No | Separate repository. It needs this engine running on a computer; it does not run models on the phone |

## Known limits

- **Web search** scrapes free search pages by default, and they rate-limit often. Set `SEARXNG_URL` or `BRAVE_SEARCH_API_KEY` for a dependable source. Wikipedia is the last fallback and cannot answer "latest version" questions.
- **Research verdicts** come from keyword-level passage matching. They quote the passages they relied on and never say more than "LIKELY". They are not calibrated probabilities.
- **Answers from a small local model** can state outdated facts. Web answers flag version numbers and years that are not in their sources, but other errors can get through.
- **Memory** is stored in JSON files. Saves are atomic, but two programs writing at once (desktop and phone backend) can still overwrite each other.
- **Knowledge search** uses hash-vector embeddings by default, which match shared words rather than meaning.
- **URL fetching** refuses local and private addresses, but does not pin DNS between the check and the connection.
- **Dependencies** are not pinned to exact versions.

## Repositories

- **This repository** is the engine and the desktop (Streamlit) app. It is the one under active development.
- `Nmoreland51-Nmoreland51-cognitive-nexus` is an earlier snapshot from March 2026.
- `cognitive-nexus-android` is the Android client. It talks to a backend running on a computer.

## Older documents

These files describe the project as it was in mid-2026 and are kept for history. Where they disagree with this page, this page is current.

- `FINAL_PROJECT_AUDIT.md` and `COGNITIVE_NEXUS_UPGRADE_SUMMARY.md` say the project is ready for commercial release and that 2 of 2 tests pass. The suite now has more than 270 tests, and the limits above still apply.
- `QUICK_START.md` describes a packaged `.exe` build. The scripts it names (`build_executable.bat`, `launch_cognitive_nexus.bat`) are not in this repository. Use the Install and Run sections of `README.md`.
