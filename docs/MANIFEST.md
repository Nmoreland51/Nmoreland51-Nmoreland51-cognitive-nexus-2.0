# Manifest

Discovery and this session. The implementation commit is `b18f3cb400fb1a1f979c43b27d462a9869dccdf7` on `cursor/grok-failover-handoff-3f8b`. This manifest update is a later commit on the same branch.

## Engine, pushed refs seen 2026-11-23

| Ref | SHA | When | Note |
|---|---|---|---|
| `fix/chat-speed-web-search-images` | `561101d37d168c0659371a9243d53887c0681e1d` | 2026-11-23 15:45 -0600 | Newest pushed engine branch. Parent of this work. CI run 45272983617 failed. |
| `copilot/nmoreland51-implement-preservation-gate` | `b1a056814ce82404f442743d5b09c11b6e2d7e26` | 2026-09-13 | Draft PR #1 into `main`. Not modified. |
| `feature/android-api-contract` | `24457defa6f2097217fa2c8aa5737a9ab4cf6a8b` | 2026-09-11 | Not modified. |
| `main` | `dce9ee092345eb82d7f6400dac7ee0e8b0eb5f50` | 2026-07-02 | Not the newest work. Not modified. |

Local state at discovery: branch `main` checked out at `dce9ee0`, clean, one worktree (`/workspace`), no stash. This session then created `cursor/grok-failover-handoff-3f8b` from `561101d`.

## Android, pushed refs seen 2026-11-23

| Ref | SHA | When |
|---|---|---|
| `feature/github-live-interface` | `bbf4e1706140cab334d14739bc609574bc33170a` | 2026-11-04 |
| `main` | `77e34b1baabb1f303b334c4475c4cec9e017c6da` | 2026-09-14 |
| `feat/native-backend-v2` | `26e42c1f6864f9ef8c61e0283bd088bb64d3ef54` | 2026-09-14 |
| `copilot/build-android-app-structure` | `f3b84d6aa24f0d6ce071a4e6a85610c9d9d9287b` | 2026-09-13 |
| `copilot/create-android-gradle-project` | `9c5a2fb7e119bfd476ee9489e2970d035fd585d5` | 2026-09-13 |

Not modified. No device tests.

## This session's tests

Parent `561101d`, `python -m pytest`: 994 passed, 43 failed, 19 errors, 2 skipped.

This branch, same command: 1016 passed, 36 failed, 19 errors, 2 skipped.

Failures removed relative to the parent, and no others added:

- `tests/test_conversation_regression_eval.py::ConversationRegressionEvalTests::test_topic_aware_direct_harm_scenario_tracks_topic`
- `tests/test_nexus_core.py::NexusCoreTests::test_direct_harmful_operational_request_gets_narrow_redirect` (replaced by `test_operational_request_is_sent_to_the_model`)
- `tests/test_nexus_core.py::NexusCoreTests::test_safety_applies_after_harmful_followup_resolution` (replaced by `test_followup_is_resolved_and_sent_to_the_model`)
- `tests/test_nexus_core.py::NexusCoreTests::test_sensitive_discussion_does_not_auto_refuse`
- `tests/test_reality_first_reasoning.py::RealityFirstReasoningTests::test_perpetual_motion_is_impossible` (renamed, now passing)
- `tests/test_reality_first_reasoning.py::RealityFirstReasoningTests::test_time_machine_blocks_procedural_fiction` (renamed, now passing)
- `tests/test_response_planner.py::TestResponsePlanner::test_topic_handling_allows_discussion_but_redirects_operational_harm`

`tests/test_xai_provider.py`: 15 passed. All stand-in HTTP. No live xAI call.

## Not available

- `XAI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Ollama was not running here
- Android device, emulator, JDK
- The file `Cognitive_Nexus_Grok_Failover_Full_Audit.md` (the 146 rows that do exist are `docs/backlog/items.json`)
- Any unpushed local Claude or Codex worktree
