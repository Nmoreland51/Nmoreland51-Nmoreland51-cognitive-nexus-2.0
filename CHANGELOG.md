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

### Known limitations
See `docs/STATUS.md`.

## 2.0.0

The state of the `main` branch on 2026-07-02, before the changes above.
