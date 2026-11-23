This backlog is worked in phases. Whoever continues should read this section, then the item entries below.

**Where the work lives**

- Engine repository, branch `fix/chat-speed-web-search-images` (every commit is pushed; CI runs on each push).
- The status of every item is in `docs/backlog/status.json`. Change it with `python tools/audit_ledger.py set <id> <STATUS> --evidence "..." --tests "..." --commits "<sha>"`, which also re-renders this report.
- Run the tests with `pip install -r requirements/dev.txt` and `python -m pytest`.

**Phase order** (from the owner's instructions of 2026-11-23)

1. Remaining reliability, memory, research and architecture items.
2. The autonomous software development agent (items 053-069).
3. Tool execution, scheduling, durable jobs and automation (070-080).
4. Android functionality, desktop/mobile synchronisation, streaming and remote access (081-095).
5. Model performance, retrieval, hardware use and response quality (096-106).
6. Security hardening, integration tests, packaging and release preparation.

**What the development machine cannot do** (as of 2026-11-23)

- No Android phone, emulator image or JDK: Android device tests and local Gradle builds are impossible; only the Python backend in the Android repository can be run.
- No OpenAI, Anthropic, GitHub or Brave API keys: cloud providers and pull-request automation cannot be exercised against the real services.
- No NVIDIA GPU: the only installed chat model, `dolphin3:8b`, runs on CPU at about 3 tokens per second, which limits how much live model testing is practical.
- No Docker or WSL distribution: process isolation uses operating-system job limits, not containers.

**Next steps**

Updated at the end of each work batch; see the newest entry at the bottom.

- 2026-11-23: ledger created from the code at commit `f5d234d`. Next: Phase 1 (dependency lock, lint and security scans in CI; cloud-failover privacy; memory locking and provenance; token-aware context; semantic retrieval; research prompt-injection defence).
- 2026-11-23, after Phase 1a and 1b: CI now runs lint, type checks, the secret scan and a dependency audit against pinned versions (Phase 1a). Providers: cloud fallback is off unless chosen, the fallback notice is never treated as a model answer, providers are proven with a real test prompt, the Anthropic default model and request are current, failures are logged by kind, and every answer is labelled with who wrote it (Phase 1b, commits de2332c, 725edd5, 4963836). Next: Phase 1c (cross-process locking for the JSON stores; fact records with provenance, conflicts and schema migrations; a token-aware context budget; export, encrypted backup, restore and selective wipe), then 1d (semantic embeddings; PDF and DOCX ingestion), then 1e (prompt-injection defence for research and the research benchmarks).
- 2026-11-23, after Phase 1c: saved data is changed under cross-process locks; one fact store with provenance, replacement, expiry, migrations and forget that reaches history and snapshots; every store is listed in modules/data_stores.py (docs/DATA_STORES.md is generated); export, encrypted backup, verified restore, snapshots, repair and wipe (modules/backup.py, tools/data_tool.py, ui/data_panel.py); the prompt is sized in tokens against the model's real window (modules/token_estimate.py, modules/context_budget.py) after measuring that long prompts were being cut by the model server. Tests run in a throwaway home (tests/conftest.py). Still open from this phase: the knowledge index has no lock, version or migration (do it with the index rewrite in 1d); live files are not encrypted (item 112, security phase); project memory (048). Next: Phase 1d (knowledge store in SQLite with semantic embeddings from Ollama, hybrid keyword search, PDF and DOCX ingestion, a measured retrieval benchmark), then 1e (research prompts fence page text; hostile-content and stance benchmarks).
