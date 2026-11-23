# Progress

Session date: 2026-11-23. Engine parent: `561101d37d168c0659371a9243d53887c0681e1d`.

## Milestones this session

| Milestone | State | What happened |
|---|---|---|
| M0 handoff | Written | `docs/HANDOFF.md`, this file, `docs/AUDIT_146_PROGRESS.md`, `docs/DECISIONS.md`, `docs/MANIFEST.md`. A later cold start has not yet read them (matrix D01, D07). |
| M1 backup fix | Done for one scoped fix, tests passing | Seven tests on `561101d` still expected topic categories and withheld fiction steps that owner-control had already removed. Those tests now match the code. No topic filter was added back. |
| M2 xAI adapter | Code and stand-in tests done. Live API not run | `modules/xai_provider.py`. Responses API, streaming deltas, multi-turn input, function tools with `call_id`. Key from `XAI_API_KEY` only. |
| M3 failover | Code and stand-in tests done. Live failover not run | `xai` is a cloud provider. Default order does not include it. Cloud fallback stays off. Failures keep distinct kinds. A tool `call_id` is not executed twice. Mid-stream failure does not append a second answer. |
| M4 platform | Not done | Desktop settings can select `xai` and the store checkbox. No browser pass, no live chat, no Android device. Android repo not modified. |
| M5 matrix | Updated, not finished | `docs/GROK_TEST_MATRIX.csv`. Live rows explicitly not run. |
| M6 restriction register | Not done | No new content filter. `docs/OWNER_CONTROL_RESTRICTIONS.md` still does not exist. Owner-control ledger rows that had no status now say partial or missing. |
| M7 release | Not done | No merge, no release, no tag. |

## 146-item ledger

Counts at `561101d`, unchanged by this session: 44 complete, 41 partial, 60 missing, 1 not applicable. The Grok matrix is an extension, not extra completions.

Owner-control ids (OC-*, CN-GR-*, OC-T*) had no status on `561101d`, which made `python tools/audit_ledger.py check` fail. They are recorded now. None were marked complete.

## Tests run here

`python -m pytest` on this branch: 1016 passed, 36 failed, 19 errors, 2 skipped.

Same command on parent `561101d`: 994 passed, 43 failed, 19 errors, 2 skipped.

The only difference is the seven tests listed in `docs/MANIFEST.md`. The agent failures (`tests/test_agent_github.py` setup errors, `tests/test_agent_coder_tolerance.py`, one jobs test, one tools test) fail the same way on the parent. They were not "fixed" by skipping them.

`python -m ruff check` on the touched modules passed. `python -m mypy` on `modules/xai_provider.py` and the other typed modules it sits with passed. `python tools/audit_ledger.py check` passed after the owner rows were recorded.

GitHub Actions on `8c1f8a3`: Ubuntu and the ledger job passed. Windows failed the same nine `tests/test_agent_benchmark.py` cases that already failed on `561101d`. Those tasks reach review, then the independent clone check disagrees. `tools/agent_benchmark.py` now clones with `core.autocrlf=false` and compares the committed blob. Actions on `02ce243`: all 6 checks passed, including Python 3.12 and 3.13 on Windows. https://github.com/Nmoreland51/Nmoreland51-Nmoreland51-cognitive-nexus-2.0/actions/runs/45287989155

Actions on `f9dcdb5` (a progress-note commit) aborted Python 3.13 on Ubuntu inside trafilatura while two page scrapes ran at once (`tests/test_owner_control.py::test_a_substring_never_blocks_a_message`, exit 134). The other five jobs passed. `modules/web_research.py` now holds one lock around trafilatura so parallel scrapes cannot enter that copy at the same time.

GitHub Actions on `561101d`: run 45272983617, conclusion failure. https://github.com/Nmoreland51/Nmoreland51-Nmoreland51-cognitive-nexus-2.0/actions/runs/45272983617

## Next

1. Nate: provide `XAI_API_KEY` if live rows P02–P05 and F01 should be run. Do not commit the key.
2. Keep working the pre-existing agent test failures on a branch that does not rewrite `fix/chat-speed-web-search-images`.
3. OC-1 still needs `docs/OWNER_CONTROL_RESTRICTIONS.md` from an actual inventory, not a guessed list.
4. Android device tests stay blocked. Newest Android branch is `feature/github-live-interface` at `bbf4e170`.
