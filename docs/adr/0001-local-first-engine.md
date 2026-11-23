# ADR 0001: Local-first engine with a single core and file-based stores

Date: 2026-11-23. Status: accepted (records decisions already embodied in the code).

## Context

Cognitive Nexus is a personal assistant that must work on one person's computer without sending their data anywhere unless they choose to. It has a desktop interface and an Android client.

## Decisions

1. **One engine, several front ends.** `modules/nexus_core.NexusCore` owns chat, research, memory and image generation. The Streamlit app (`app.py`) and the Android backend (in the `cognitive-nexus-android` repository, which imports this engine) call it; neither re-implements its logic.
2. **Local models first.** Text generation goes through `modules/provider_router.ProviderRouter`, which prefers a local Ollama model. Cloud providers are optional and must never be used unless the user enabled them.
3. **Files, not a database server.** Memory, chat history, settings and the knowledge index are JSON files under `data/` and `ai_system/`. Saves are atomic (`modules/file_utils.py`). This keeps installation to "clone and run" at the cost of weak concurrency; the Android backend keeps its own SQLite store for sessions.
4. **The web is untrusted.** Everything fetched from the web passes `modules/url_safety.safe_get` (public addresses only) and is treated as data, never as instructions.
5. **Claims of quality need evidence.** Research verdicts quote the passages they rely on and never exceed "LIKELY"; `docs/STATUS.md` separates tested, live-verified and unverified features; the audit ledger requires verification notes for anything marked complete.

## Consequences

- Any feature added to the engine is available to both front ends, and any engine bug affects both.
- JSON stores need explicit locking when two processes write (desktop and phone backend).
- Quality depends on the local model. Orchestration, retrieval and checks can improve reliability but cannot make a small model as capable as a large one.
