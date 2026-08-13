# Task 5 Review Package (non-Git workspace)

This project is not a Git repository. Review the current API files directly
against the Task 5 brief and controller/store contracts. Do not mutate files.

## Files

- `src/web/app.py`
- `tests/web/__init__.py`
- `tests/web/test_warehouse_api.py`
- `.superpowers/sdd/2026-08-09-warehouse-catalog/task-5-report.md`

## Attention lens

Verify exact four endpoint behavior, one controller instance, JSON-serializable
409/503 errors, offline and bot-running checks before start, no engine.start or
task config mutations, prompt/nonblocking start-stop semantics, safe store
close on item reads, category filtering, and preservation of existing routes.
