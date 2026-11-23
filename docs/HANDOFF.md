# Handoff

Read this file first. It is enough to resume without the chat that produced it.

## Where the code is

- Engine repository: `Nmoreland51/Nmoreland51-Nmoreland51-cognitive-nexus-2.0`
- This work: branch `cursor/grok-failover-handoff-3f8b`, based on `561101d37d168c0659371a9243d53887c0681e1d` (`fix/chat-speed-web-search-images`).
- Do not commit on `fix/chat-speed-web-search-images`, `main`, `feature/android-api-contract`, or `copilot/nmoreland51-implement-preservation-gate`.
- Exact SHAs and test totals: `docs/MANIFEST.md`.
- What is done and what is next: `docs/PROGRESS.md`.
- Why xAI is off by default: `docs/DECISIONS.md`.
- The 43-case matrix: `docs/GROK_TEST_MATRIX.csv`.

## What was true at discovery (2026-11-23)

Pushed engine branches, newest commit first:

| Branch | SHA | Commit date |
|---|---|---|
| `fix/chat-speed-web-search-images` | `561101d37d168c0659371a9243d53887c0681e1d` | 2026-11-23 15:45 -0600 |
| `copilot/nmoreland51-implement-preservation-gate` | `b1a056814ce82404f442743d5b09c11b6e2d7e26` | 2026-09-13 |
| `feature/android-api-contract` | `24457defa6f2097217fa2c8aa5737a9ab4cf6a8b` | 2026-09-11 |
| `main` | `dce9ee092345eb82d7f6400dac7ee0e8b0eb5f50` | 2026-07-02 |

`main` is not the newest work. Open engine PR: draft #1 from the Copilot branch into `main`. It was not merged and not edited.

Android repository `Nmoreland51/cognitive-nexus-android`, newest pushed branch `feature/github-live-interface` at `bbf4e1706140cab334d14739bc609574bc33170a` (2026-11-04). `main` there is `77e34b1baabb1f303b334c4475c4cec9e017c6da` (2026-09-14). This session did not change that repository.

This session can only see GitHub. A Claude or Codex checkout that was never pushed is invisible here. The engine worktree at discovery was clean (`git status` empty, one worktree at `/workspace`).

The package named `Cognitive_Nexus_Grok_Failover_Full_Audit.md` was not in the upload set and is not in the repository. The 146-item list that is in the repository is `docs/backlog/items.json`, rendered to `docs/AUDIT_146_PROGRESS.md`. Those 146 rows were not re-graded. Their completion counts were not increased.

## How to run the tests

```bash
pip install -r requirements/dev.txt -c requirements/constraints.txt
python -m pytest
python tools/audit_ledger.py check
python tools/check_repo_hygiene.py
```

Focused checks for this branch:

```bash
python -m pytest tests/test_xai_provider.py tests/test_provider_truth.py tests/test_owner_control.py
```

There is no `XAI_API_KEY` in this environment. Do not invent one. Live rows in the matrix stay "Not run / blocked on key" until Nate provides a key and someone records the reply.

## How to turn xAI on (owner, later)

1. Export `XAI_API_KEY` in the environment. Do not put it in the repo or in `config/nexus_config.json`.
2. Add `xai` to the provider order in Settings. It is not in the default order.
3. If `xai` is not first, also turn on "Allow cloud fallback". That sends prompts to a paid service when an earlier provider fails.
4. Leave "Let xAI store prompts for 30 days" off unless you want xAI to retain the prompt and reply.

## Do not

- Merge this branch.
- Force-push or rewrite `fix/chat-speed-web-search-images`.
- Add topic filters or canned refusals. The owner removed those. Reality check default is label, not withhold.
- Treat a mock or a fallback notice as a successful Grok answer.
