# Task 4 Fix Round Review Package (non-Git workspace)

Review only the terminal-state race fix in this non-Git workspace.

Finding to verify:

- `stop()` could overwrite a terminal snapshot with `stopping` during the
  post-publish/pre-thread-clear window. Verify that only `running` transitions
  to `stopping`, and that a deterministic regression test covers the window.

Files:

- `src/warehouse/controller.py`
- `tests/warehouse/test_controller.py`
- `.superpowers/sdd/2026-08-09-warehouse-catalog/task-4-report.md`
