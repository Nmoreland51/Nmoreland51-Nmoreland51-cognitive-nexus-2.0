# Cognitive Nexus Operation 7 Legacy / Ignore Report

Audit date: 2026-05-31

Scope: ignore confirmed runtime state and quarantine untracked prototype root packages. No commits were created. No app behavior was rewritten. No permanent deletion was performed except cache artifacts explicitly allowed by Operation 7.

## .gitignore Updates

Added:

```gitignore
.learnings/
data/reality_grounding_patterns.json
```

Already present before Operation 7:

```gitignore
__pycache__/
*.pyc
```

Not ignored:

- `legacy/`
- `modules/`
- `core/`
- `search/`
- `tests/`

## Folders Moved

Created:

```text
legacy/experimental_architecture/
```

Moved these root prototype packages into it:

```text
agents/
emergence/
experiments/
memory/
providers/
research/
routing/
simulation/
theories/
visualization/
worlds/
```

Resulting source files:

```text
legacy/experimental_architecture/agents/base.py
legacy/experimental_architecture/agents/nexus.py
legacy/experimental_architecture/agents/__init__.py
legacy/experimental_architecture/emergence/monitor.py
legacy/experimental_architecture/emergence/__init__.py
legacy/experimental_architecture/experiments/experiment.py
legacy/experimental_architecture/experiments/__init__.py
legacy/experimental_architecture/memory/store.py
legacy/experimental_architecture/memory/__init__.py
legacy/experimental_architecture/providers/local.py
legacy/experimental_architecture/providers/__init__.py
legacy/experimental_architecture/research/strategy.py
legacy/experimental_architecture/research/__init__.py
legacy/experimental_architecture/routing/router.py
legacy/experimental_architecture/routing/__init__.py
legacy/experimental_architecture/simulation/loop.py
legacy/experimental_architecture/simulation/__init__.py
legacy/experimental_architecture/theories/theory.py
legacy/experimental_architecture/theories/__init__.py
legacy/experimental_architecture/visualization/insight.py
legacy/experimental_architecture/visualization/__init__.py
legacy/experimental_architecture/worlds/environment.py
legacy/experimental_architecture/worlds/__init__.py
```

Left in place for review:

```text
skills/self-improvement/
COGNITIVE_NEXUS_AUDIT_REPORT.md
data/reality_grounding_patterns.json
.learnings/
```

## Cache Files Removed

Removed only cache directories from inside `legacy/experimental_architecture/`:

```text
legacy/experimental_architecture/agents/__pycache__
legacy/experimental_architecture/emergence/__pycache__
legacy/experimental_architecture/experiments/__pycache__
legacy/experimental_architecture/memory/__pycache__
legacy/experimental_architecture/providers/__pycache__
legacy/experimental_architecture/research/__pycache__
legacy/experimental_architecture/routing/__pycache__
legacy/experimental_architecture/simulation/__pycache__
legacy/experimental_architecture/theories/__pycache__
legacy/experimental_architecture/visualization/__pycache__
legacy/experimental_architecture/worlds/__pycache__
```

Post-clean check found no `__pycache__` directories or `*.pyc` files inside `legacy/experimental_architecture/`.

## Validation Results

Commands run:

```powershell
python smoke_test.py
python -m compileall -q app.py streamlit_app.py modules core search nexus_router.py web_research_module.py
python -m unittest discover -s tests -p "test_*.py"
```

Results:

- Smoke test: passed, `Cognitive Nexus smoke test passed.`
- Compile check: passed with no errors.
- Unit tests: passed, `Ran 122 tests in 5.481s`, `OK`.

Non-fatal output:

- Streamlit bare-mode warnings appeared during smoke/tests.
- `sentence-transformers embeddings unavailable; falling back to hash vectors: model unavailable` appeared during tests.

## Remaining Untracked Files

Visible in `git status --short` after Operation 7:

```text
?? COGNITIVE_NEXUS_AUDIT_REPORT.md
?? OPERATION_6_CLASSIFICATION_REPORT.md
?? OPERATION_7_LEGACY_IGNORE_REPORT.md
?? legacy/experimental_architecture/
?? skills/self-improvement/
```

Ignored and therefore no longer shown by normal status:

```text
.learnings/
data/reality_grounding_patterns.json
```

Modified tracked file:

```text
.gitignore
```

## Exact Commit Recommendation

Recommended commit message:

```text
chore(repo): quarantine experimental prototypes
```

Recommended files for that commit:

```text
.gitignore
legacy/experimental_architecture/
OPERATION_6_CLASSIFICATION_REPORT.md
OPERATION_7_LEGACY_IGNORE_REPORT.md
```

Commit only if the team wants operation reports tracked. If not, leave the two operation reports uncommitted or move sanitized copies to docs later.

## Exact Files To Leave Uncommitted

Leave these uncommitted for now:

```text
COGNITIVE_NEXUS_AUDIT_REPORT.md
skills/self-improvement/
.learnings/
data/reality_grounding_patterns.json
```

Reason:

- `COGNITIVE_NEXUS_AUDIT_REPORT.md` contains local paths and stale machine-specific diagnostics.
- `skills/self-improvement/` needs human review for provenance/license/encoding.
- `.learnings/` is local tool-generated state.
- `data/reality_grounding_patterns.json` is runtime/test-generated auditor state.

## Next Operation

Operation 8: Commit Legacy / Ignore Cleanup.

Suggested scope:

1. Stage `.gitignore`.
2. Stage `legacy/experimental_architecture/`.
3. Decide whether to stage Operation 6 and 7 reports.
4. Do not stage `COGNITIVE_NEXUS_AUDIT_REPORT.md`, `skills/self-improvement/`, `.learnings/`, or `data/reality_grounding_patterns.json`.
5. Run smoke, compile, and 122-test suite before committing.

