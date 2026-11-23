# Changelog

Notable changes to the engine and desktop app. Versions follow `cognitive_nexus/version.py`.

## 2.1.0 (unreleased)

### Fixed
- Chat no longer falls back after 12 seconds on CPU-only machines; Ollama gets at least 120 seconds for the first token and stays loaded between requests.
- Chat web search now runs when asked, answers in under a minute on CPU with sources, and says so when search finds nothing instead of inventing an answer.
- Research verdicts are based on passages that address the claim. "TRUE at 0.8 confidence" from unrelated trusted sites is gone.
- "forget it" no longer deletes unrelated memories; fact ids are stable across launches.
- Deep-mode answers get their intended 780-token budget (a misplaced branch capped them at 420).
- The fallback reply names the provider that failed and why.
- A failed model is no longer saved or shown as an answer: research summaries, knowledge answers and reports show a plain failure notice and store nothing as a "summary". An answer cut off part-way is marked as cut off.
- If the local model fails, the prompt is no longer sent to OpenAI or Anthropic just because a key is configured. Cloud providers are used only when placed first in the provider order or when "Allow cloud fallback" is turned on.
- The Anthropic provider would have failed on every request: its default model (`claude-sonnet-4-20250514`) was retired in June 2026. The default is now `claude-sonnet-5-5`, retired model names in saved settings are replaced automatically, and the request follows the current API. Not yet run against the live API (no key was available).
- A local model whose name starts with "o" (for example `orca-mini`) is no longer sent to OpenAI as a model name.
- Long prompts are no longer cut by the model server. A normal 2,147-token chat prompt was being sent with a 2,048-token window, and Ollama silently kept 1,026 tokens, dropping the instructions. The prompt is now sized in tokens against the model's real window and trimmed in a fixed order, least important first.
- The adaptive memory no longer erases facts saved by "remember ...": it kept its own copy of the profile and wrote it back whole. Its "forget" no longer matches parts of words ("forget it" could erase every memory containing "it").
- Saved memory no longer drops old facts silently at 25 or 60 items; the limit is 500 and reaching it is reported.
- Two programs or tabs saving at the same time no longer overwrite each other's changes (measured before the fix: 22 of 80 concurrent updates survived).

### Added
- Search sources with automatic switching (SearXNG, Brave Search API, search pages, Wikipedia).
- Refusal to fetch local and private-network addresses during research.
- Crash-safe (atomic) saves for memory, settings and the knowledge index.
- Local image generation downloads 2.0 GB instead of 5.1 GB.
- Continuous integration: tests on Windows and Ubuntu, lint, type check, secret scan, dependency audit.
- `docs/STATUS.md`, the audit ledger (`docs/AUDIT_146_PROGRESS.md`) and pinned dependencies (`requirements/constraints.txt`).
- Every reply is labelled with who wrote it (provider and model, or no model), whether the prompt stayed on this machine, the time taken, the cost when a cloud provider reports usage, and the tools that ran.
- The chat model is checked with a real test prompt at start; Diagnostics can send a test prompt to any provider and shows a provider as working only after it has produced text.
- Diagnostics counts model failures, fallback notices, search-source failures and tool failures separately (also written to `logs/events.jsonl`).
- Cloud calls retry rate limits and dropped connections and report the provider's own error message.
- Saved facts record how each is known (instruction, preference, stated fact, or inferred by the app), when it was first said and last confirmed. A new value replaces the old one and keeps it as history ("remember also:" keeps both); "remember for 3 days that ..." expires; "forget ..." also removes earlier values, related preferences and the copies in local snapshots.
- "Your data" in the Memory tab, and `python tools/data_tool.py`: export, passphrase-encrypted backup, verified restore with undo, daily local snapshots, repair of a damaged file from a snapshot, and permanent selective wipe. `docs/DATA_STORES.md` lists everything the app saves.
- `COGNITIVE_NEXUS_HOME` keeps all saved data outside the project folder.
- The summary of older chat turns covers the whole conversation and keeps decisions, numbers and file names rather than the last 18 messages.
- Diagnostics shows how the last prompt was fitted to the model's context window.

### Known limitations
See `docs/STATUS.md`.

## 2.0.0

The state of the `main` branch on 2026-07-02, before the changes above.
