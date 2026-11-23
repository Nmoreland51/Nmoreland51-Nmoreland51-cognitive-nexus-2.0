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

### Added
- Search sources with automatic switching (SearXNG, Brave Search API, search pages, Wikipedia).
- Refusal to fetch local and private-network addresses during research.
- Crash-safe (atomic) saves for memory, settings and the knowledge index.
- Local image generation downloads 2.0 GB instead of 5.1 GB.
- Continuous integration: tests on Windows and Ubuntu, lint, type check, secret scan, dependency audit.
- `docs/STATUS.md`, the audit ledger (`docs/AUDIT_146_PROGRESS.md`) and pinned dependencies (`requirements/constraints.txt`).

### Known limitations
See `docs/STATUS.md`.

## 2.0.0

The state of the `main` branch on 2026-07-02, before the changes above.
