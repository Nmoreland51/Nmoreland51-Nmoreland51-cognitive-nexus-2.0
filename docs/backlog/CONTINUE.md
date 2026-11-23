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
