# Definition of done

A change is done when all of these are true. "It works on my machine" and "the tests are mocked but pass" are not enough on their own.

1. **It does the real thing.** The behaviour exists in the code path the app uses, not only as a setting, a placeholder or a document.
2. **It has automated tests** that fail without the change, and `python -m pytest` passes.
3. **CI is green** on the pushed commit: tests on Windows and Ubuntu, lint, type check, secret scan, ledger check, dependency audit.
4. **It was run for real where that is possible** (a live model, a live search, the running app), and the result was looked at. If it could not be run for real, the reason is written down.
5. **Limits are stated.** Anything the change does not cover is recorded in `docs/STATUS.md` or the audit ledger, not left implied.
6. **No private data or secrets** are added to the repository (`python tools/check_repo_hygiene.py`).
7. **The audit ledger is updated** when the change touches a backlog item: `python tools/audit_ledger.py set <id> <STATUS> --evidence ... --tests ... --commits ...`.
8. **New dependencies are listed** in `requirements/` and pinned in `requirements/constraints.txt`.

## Statuses used in the audit ledger

- **COMPLETE**: points 1 to 5 hold for the item as written.
- **PARTIAL**: real work exists, and the evidence says exactly what is missing.
- **MISSING**: nothing real exists yet.
- **NOT APPLICABLE**: the item does not apply; the evidence says why.
