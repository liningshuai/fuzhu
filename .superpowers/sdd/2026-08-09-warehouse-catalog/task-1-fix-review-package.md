# Task 1 Fix Round Review Package (non-Git workspace)

This project is intentionally not a Git repository, so no BASE/HEAD or Git
diff exists. Review the current changed files directly and limit the review to
the findings listed below plus breakage introduced by the fix round.

## Findings to verify

1. Page-atomic write semantics were missing: verify `upsert_page()` writes all
   observations in one transaction and `upsert_observation()` remains safe.
2. Empty categories could not count as completed: verify explicit category
   completion persistence and `finish_scan()` counting.
3. Outside-root absolute screen paths were leaked into the database: verify
   they are rejected and in-root paths remain project-relative.
4. Successful scan status was `completed` instead of the design's `success`.
5. Verify the evidence-byte/path handling is coherent with Task 1's required
   model and the later scanner/parser responsibilities.

## Files to inspect

- `src/warehouse/models.py`
- `src/warehouse/store.py`
- `tests/warehouse/test_store.py`
- `.superpowers/sdd/2026-08-09-warehouse-catalog/task-1-report.md`
