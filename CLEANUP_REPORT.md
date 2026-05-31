# Cognitive Nexus Repository Hygiene Patch Report

Date: 2026-05-31

## Summary

This patch keeps the working app behavior intact and only changes repository hygiene, validation, and documentation.

The app stayed alive during validation:

```text
http://localhost:8501/_stcore/health -> 200 ok
```

## Files Ignored

Added `.gitignore` with rules for generated/private/runtime junk:

```text
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
*.pid
streamlit_app.out.log
streamlit_app.err.log
streamlit_app_*.out.log
streamlit_app_*.err.log
streamlit_stdout.log
streamlit_stderr.log
logs/*.log
logs/*.jsonl
data/chat_history.json
data/user_profile.json
data/search_cache/
data/search_history/
data/web_research/
data/research_reports/
data/images/
data/knowledge_notes/
ai_system/knowledge_bank/web_research/embeddings.json
ai_system/knowledge_bank/web_research/chunks.json
ai_system/knowledge_bank/web_research/metadata.json
audit/
progress/
build/
dist/
```

Confirmed the requested active source/test paths are not ignored:

```text
none of the active source/test paths are ignored
```

Note: `.gitignore` does not automatically remove files that were already tracked before this patch. Existing tracked runtime/build/cache files still appear as dirty until they are explicitly removed from the index in a commit.

## Files Preserved

These active source/test files remain real project files and are not ignored:

```text
core/
modules/core_health.py
modules/reality_research_agent.py
tests/test_core_health.py
tests/test_reality_research_agent.py
tests/test_reality_first_reasoning.py
tests/test_reality_grounding.py
tests/test_prompt_firewall.py
tests/test_research_notes.py
tests/test_web_research_module.py
```

## Legacy Files Quarantined

Renamed the broken legacy backup without repairing it:

```text
legacy/cognitive_nexus_ai_corrupted_backup.py
-> legacy/cognitive_nexus_ai_corrupted_backup.py.disabled
```

This prevents the known corrupted legacy `.py` file from being compiled as active Python source.

## Validation Scripts Added

Added `run_tests.py`.

It runs:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Added `smoke_test.py`.

It imports:

```text
app
modules.nexus_core
modules.provider_router
modules.reality_research_agent
modules.core_health
core
search.bloodhound_search
```

On success it prints:

```text
Cognitive Nexus smoke test passed.
```

## README Updates

Updated `README.md` with the correct validation commands:

```powershell
python smoke_test.py
python -m unittest discover -s tests -p "test_*.py"
```

Also documented that root-level `python -m unittest discover` does not discover the full suite in this repo.

## Validation Commands Run

### Smoke Test

Command:

```powershell
python smoke_test.py
```

Result:

```text
Cognitive Nexus smoke test passed.
```

Non-fatal Streamlit bare-mode warnings appeared because `app` was imported outside `streamlit run`:

```text
WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext!
WARNING streamlit.runtime.caching.cache_data_api: No runtime found, using MemoryCacheStorageManager
```

Exit code: `0`

### Active Compile Check

Command:

```powershell
python -m compileall -q app.py streamlit_app.py modules core search nexus_router.py web_research_module.py
```

Result:

```text
exit code 0
```

### Full Active Test Suite

Command:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Result:

```text
Ran 122 tests in 5.508s

OK
```

Non-fatal output:

```text
INFO:web_research_module:sentence-transformers embeddings unavailable; falling back to hash vectors: model unavailable
```

Exit code: `0`

### App Health Check

Command:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health -TimeoutSec 10
```

Result:

```text
StatusCode Content
---------- -------
       200 ok
```

## Remaining Dirty Files

Post-patch status count:

```text
unstaged tracked changes: 77
untracked files: 106
total dirty entries: 183
```

Important remaining dirty categories:

- Active source changes that should be reviewed/committed intentionally:
  - `app.py`
  - `modules/nexus_core.py`
  - `modules/provider_router.py`
  - `modules/providers.py`
  - `modules/context_manager.py`
  - `modules/image_gen.py`
  - `modules/nexus_config.py`
  - `modules/project_status.py`
  - `modules/research.py`
  - `nexus_router.py`
  - `web_research_module.py`
  - relevant tests under `tests/`

- New hygiene files from this patch:
  - `.gitignore`
  - `run_tests.py`
  - `smoke_test.py`
  - `CLEANUP_REPORT.md`

- Active files that remain untracked and should be committed if they are part of the app:
  - `core/`
  - `modules/core_health.py`
  - `modules/reality_research_agent.py`
  - `tests/test_core_health.py`
  - `tests/test_reality_research_agent.py`
  - `tests/test_reality_first_reasoning.py`
  - `tests/test_reality_grounding.py`
  - `tests/test_prompt_firewall.py`
  - `tests/test_research_notes.py`
  - `tests/test_web_research_module.py`

- Already-tracked generated/private files still dirty despite `.gitignore`:
  - `__pycache__/...`
  - `modules/__pycache__/...`
  - `tests/__pycache__/...`
  - `dist/...`
  - `build/...`
  - `logs/uncertainty.jsonl`
  - `streamlit_app.out.log`
  - `streamlit_app.err.log`
  - `streamlit_app.pid`
  - `data/chat_history.json`
  - `data/user_profile.json`
  - `ai_system/knowledge_bank/web_research/chunks.json`
  - `ai_system/knowledge_bank/web_research/embeddings.json`
  - `ai_system/knowledge_bank/web_research/metadata.json`

These tracked generated/private files should not be included in a clean source commit unless intentionally curated. They should be removed from tracking with a deliberate index cleanup commit while keeping local working copies.

## What Should Be Committed

Commit intentionally:

```text
.gitignore
README.md
run_tests.py
smoke_test.py
CLEANUP_REPORT.md
core/
modules/core_health.py
modules/reality_research_agent.py
tests/test_core_health.py
tests/test_reality_research_agent.py
tests/test_reality_first_reasoning.py
tests/test_reality_grounding.py
tests/test_prompt_firewall.py
tests/test_research_notes.py
tests/test_web_research_module.py
active source files already changed for the working app
active tests that cover the working app
legacy/cognitive_nexus_ai_corrupted_backup.py.disabled, if legacy quarantine history should be preserved
```

## What Should NOT Be Committed

Do not commit generated/private/runtime artifacts:

```text
__pycache__/
*.pyc
streamlit_app*.log
*.pid
logs/*.jsonl
data/chat_history.json
data/user_profile.json
data/search_cache/
data/search_history/
data/web_research/
data/research_reports/
data/images/
data/knowledge_notes/
ai_system/knowledge_bank/web_research/chunks.json
ai_system/knowledge_bank/web_research/embeddings.json
ai_system/knowledge_bank/web_research/metadata.json
audit/
progress/
build/
dist/
```

Also do not commit private chat/profile/research outputs unless converted into a small sanitized demo dataset.

## Hygiene Patch 2: Tracked Artifact Index Cleanup

Patch 2 removed generated/private files from git tracking only. Local files were kept on disk.

Command class used:

```powershell
git rm --cached -r --pathspec-from-file=<temp pathspec file> --pathspec-file-nul
```

The pathspec came from:

```powershell
git ls-files -ci --exclude-standard
```

Result:

```text
tracked ignored files before cleanup: 3631
git rm --cached exit code: 0
tracked ignored files after cleanup: 0
```

The first attempt failed because PowerShell expanded the temp file path incorrectly:

```text
fatal: could not open 'C:/Users/Nmore/AppData/Local/Temp/tmpF32A.tmp.FullName' for reading: No such file or directory
```

That failed attempt did not remove files from disk or from the index. The corrected command succeeded.

Sample staged removals from git tracking:

```text
__pycache__/app.cpython-312.pyc
ai_system/knowledge_bank/web_research/chunks.json
ai_system/knowledge_bank/web_research/embeddings.json
ai_system/knowledge_bank/web_research/metadata.json
build/cognitive_nexus_full_project/...
cognitive_nexus/__pycache__/...
data/chat_history.json
data/images/generated/...
data/user_profile.json
data/web_research/...
dist/CognitiveNexusFullProject/...
logs/uncertainty.jsonl
modules/__pycache__/...
streamlit_app.err.log
streamlit_app.out.log
streamlit_app.pid
tests/__pycache__/...
```

These are staged as `D` in git because the cleanup removes them from the repository index. The local copies are still present and ignored.

## Local Files Kept

Confirmed local generated/private files still exist after `git rm --cached`:

```text
__pycache__/
dist/
build/
logs/uncertainty.jsonl
streamlit_app.out.log
streamlit_app.err.log
streamlit_app.pid
data/chat_history.json
data/user_profile.json
ai_system/knowledge_bank/web_research/chunks.json
ai_system/knowledge_bank/web_research/embeddings.json
ai_system/knowledge_bank/web_research/metadata.json
```

Confirmed active source/test paths still exist:

```text
core/
modules/core_health.py
modules/reality_research_agent.py
tests/test_core_health.py
tests/test_reality_research_agent.py
tests/test_reality_first_reasoning.py
tests/test_reality_grounding.py
tests/test_prompt_firewall.py
tests/test_research_notes.py
tests/test_web_research_module.py
```

## Patch 2 Validation

### Smoke Test

Command:

```powershell
python smoke_test.py
```

Result:

```text
Cognitive Nexus smoke test passed.
exit code 0
```

Non-fatal Streamlit bare-mode warnings still appear when importing `app` outside `streamlit run`.

### Active Compile Check

Command:

```powershell
python -m compileall -q app.py streamlit_app.py modules core search nexus_router.py web_research_module.py
```

Result:

```text
exit code 0
```

### Full Active Test Suite

Command:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Result:

```text
Ran 122 tests in 5.408s

OK
exit code 0
```

Non-fatal output:

```text
sentence-transformers embeddings unavailable; falling back to hash vectors: model unavailable
```

### App Health Check

Command:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health -TimeoutSec 10
```

Result:

```text
StatusCode: 200
Content: ok
```

## Remaining Dirty Status After Patch 2

Post-cleanup status summary:

```text
staged generated/private index removals: 3631
unstaged modified tracked files: 23
unstaged deleted tracked files: 13
untracked files: 107
tracked ignored files still present: 0
total dirty entries: 3774
```

Remaining non-generated-deletion dirty entries:

```text
 M .env.example
 D "ENHANCED_IMAGE_GENERATION_INTEGRATION - Copy.md"
 D "OPENCHAT_INTEGRATION_GUIDE - Copy.md"
 M README.md
 D "TEMP_THINKING_INTEGRATION_GUIDE - Copy.md"
 D "UI_STRUCTURE_DOCUMENTATION - Copy.md"
 M app.py
 D "cognitive_nexus_ai - Copy.py"
 M cognitive_nexus_ai.py
 D cognitive_nexus_ai_corrupted_backup.py
 D "cognitive_nexus_ai_updated - Copy.py"
 D "cognitive_nexus_temp_thinking - Copy.py"
 M config/nexus_config.json
 D experimental_test.py
 M modules/chat_profile.py
 M modules/context_manager.py
 M modules/image_gen.py
 M modules/nexus_config.py
 M modules/nexus_core.py
 M modules/project_status.py
 M modules/provider_router.py
 M modules/providers.py
 M modules/research.py
 M nexus_router.py
 D "requirements - Copy.txt"
 D "requirements_openchat - Copy.txt"
 M run.py
 D simple_test.py
 D test_web_research_module.py
 M test_web_research_simple.py
 M tests/test_context_manager.py
 M tests/test_image_generation_module.py
 M tests/test_nexus_core.py
 M tests/test_provider_router.py
 M verify_setup.py
 M web_research_module.py
?? .gitignore
?? .learnings/
?? AGENTS.md
?? CLEANUP_REPORT.md
?? COGNITIVE_NEXUS_AUDIT_REPORT.md
?? COGNITIVE_NEXUS_UPGRADE_SUMMARY.md
?? FINAL_PROJECT_AUDIT.md
?? PHASE_4_UI_SIMPLIFICATION_COMPLETED.md
?? PHASE_5_LEGACY_CLEANUP_COMPLETED.md
?? PHASE_6_PACKAGING_DEMO_COMPLETED.md
?? PROJECT_STRUCTURE.md
?? RELEASE_CHECKLIST.md
?? SCREENSHOT_GUIDE.md
?? agents/
?? core/
?? data/reality_grounding_patterns.json
?? emergence/
?? experiments/
?? launch_demo.bat
?? legacy/
?? memory/
?? modules/core_health.py
?? modules/reality_research_agent.py
?? providers/
?? research/
?? routing/
?? run_tests.py
?? simulation/
?? skills/self-improvement/
?? smoke_test.py
?? tests/test_app_controls.py
?? tests/test_core_health.py
?? tests/test_project_status.py
?? tests/test_prompt_firewall.py
?? tests/test_reality_first_reasoning.py
?? tests/test_reality_grounding.py
?? tests/test_reality_research_agent.py
?? tests/test_research_notes.py
?? tests/test_web_research_module.py
?? theories/
?? visualization/
?? worlds/
```

## Commit Recommendation

Recommended cleanup commit contents:

```text
.gitignore
CLEANUP_REPORT.md
README.md
run_tests.py
smoke_test.py
the 3631 staged git rm --cached removals for generated/private artifacts
```

Recommended app/source commit candidates, after reviewing the existing work:

```text
app.py
cognitive_nexus_ai.py
config/nexus_config.json
core/
modules/chat_profile.py
modules/context_manager.py
modules/core_health.py
modules/image_gen.py
modules/nexus_config.py
modules/nexus_core.py
modules/project_status.py
modules/provider_router.py
modules/providers.py
modules/reality_research_agent.py
modules/research.py
nexus_router.py
run.py
test_web_research_simple.py
tests/test_app_controls.py
tests/test_context_manager.py
tests/test_core_health.py
tests/test_image_generation_module.py
tests/test_nexus_core.py
tests/test_project_status.py
tests/test_prompt_firewall.py
tests/test_provider_router.py
tests/test_reality_first_reasoning.py
tests/test_reality_grounding.py
tests/test_reality_research_agent.py
tests/test_research_notes.py
tests/test_web_research_module.py
verify_setup.py
web_research_module.py
```

Review before staging:

```text
.env.example
AGENTS.md
COGNITIVE_NEXUS_AUDIT_REPORT.md
COGNITIVE_NEXUS_UPGRADE_SUMMARY.md
FINAL_PROJECT_AUDIT.md
PHASE_4_UI_SIMPLIFICATION_COMPLETED.md
PHASE_5_LEGACY_CLEANUP_COMPLETED.md
PHASE_6_PACKAGING_DEMO_COMPLETED.md
PROJECT_STRUCTURE.md
RELEASE_CHECKLIST.md
SCREENSHOT_GUIDE.md
agents/
data/reality_grounding_patterns.json
emergence/
experiments/
launch_demo.bat
legacy/
memory/
providers/
research/
routing/
simulation/
skills/self-improvement/
theories/
visualization/
worlds/
```

Do not re-add or commit local generated/private contents:

```text
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
*.pid
streamlit_app*.log
logs/*.log
logs/*.jsonl
data/chat_history.json
data/user_profile.json
data/search_cache/
data/search_history/
data/web_research/
data/research_reports/
data/images/
data/knowledge_notes/
ai_system/knowledge_bank/web_research/chunks.json
ai_system/knowledge_bank/web_research/embeddings.json
ai_system/knowledge_bank/web_research/metadata.json
audit/
progress/
build/
dist/
```

## Final Hygiene Verdict

Patch 2 completed the requested index cleanup.

Generated/private artifacts are no longer tracked ignored files (`git ls-files -ci --exclude-standard` returns `0`). Local runtime data, logs, cache files, build outputs, and generated reports were kept on disk.

The active app still imports, compiles, tests, and remains live on port `8501`.

The repo is not clean yet, but the remaining dirt is now visible as either real source/doc/test work, intentional staged index removals, or untracked files that need human review. The next step should be a deliberate commit split, not more feature work.
