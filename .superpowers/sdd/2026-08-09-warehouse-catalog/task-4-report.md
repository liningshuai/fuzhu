# Task 4 Report: Add the single background scan controller

## Changed files

- `src/warehouse/controller.py`
- `src/warehouse/scanner.py`
- `tests/warehouse/test_controller.py`

## RED

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_controller -v
```

Observed failure before implementation:

```text
ModuleNotFoundError: No module named 'src.warehouse.controller'
FAILED (errors=4)
```

This RED state was expected because Task 4's controller module did not exist yet.

## Implementation summary

- Added `WarehouseScanController` with:
  - one daemon worker thread
  - lock-protected snapshot state
  - duplicate-start rejection
  - bot-engine-running rejection via read-only `engine.status()`
  - cooperative stop via `threading.Event`
  - bounded `join(timeout=...)` in `stop()`
  - final snapshot publication for `success/partial/failed/stopped`
- Kept engine ownership boundaries intact:
  - reuses `engine._new_task_context()`
  - never calls `engine.start()` or `engine.stop()`
  - reuses the current engine device, matcher, and session guard
- Kept OCR construction lazy by instantiating the OCR backend only inside the background worker.
- Kept the database project-local at:

  ```text
  data/warehouse_catalog/catalog.db
  ```

- Added an optional `progress_callback` to `WarehouseScanner` with a no-op default so replay compatibility remains intact while the controller can publish:
  - `scan_id`
  - `category`
  - `page`
  - `categories_completed`
  - `message`

## GREEN

Focused controller command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_controller -v
```

Output:

```text
test_snapshot_publishes_progress_final_result_and_project_local_store_path ... ok
test_start_rejects_duplicate_scan_and_uses_one_daemon_worker ... ok
test_start_rejects_when_bot_engine_is_running ... ok
test_stop_sets_event_and_returns_without_waiting_for_unbounded_cleanup ... ok

Ran 4 tests in 0.017s

OK
```

## Regression verification

Store:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
```

Result:

```text
Ran 9 tests in 0.501s

OK
```

Parser:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_parser -v
```

Result:

```text
Ran 7 tests in 0.011s

OK
```

Scanner replay:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_scanner_replay -v
```

Result:

```text
Ran 7 tests in 1.375s

OK
```

## Behavior covered by the new controller tests

- rejects duplicate manual scan starts while the worker is alive
- rejects warehouse scans while the bot engine reports `running=True`
- starts exactly one daemon worker
- propagates `stop()` through the shared stop event
- returns from `stop()` without waiting for unbounded worker cleanup
- preserves final snapshot fields: `status`, `scan_id`, `category`, `page`, `categories_completed`, `items_found`, `low_confidence_count`, `message`
- builds a fresh `TaskContext` from the engine's current device/matcher/session guard
- uses the project-local warehouse database path

## Concerns

- The real scanner currently reports live progress for `scan_id/category/page/categories_completed/message`; `items_found` and `low_confidence_count` become authoritative at final result publication rather than being recomputed mid-scan.
- `WarehouseScanner.scan()` still closes the store in its own `finally`, and the controller also closes the store in its worker `finally`; this is intentional and currently safe because `WarehouseCatalogStore.close()` is idempotent.

## Fix round 1: preserve terminal snapshot during stop race

### Review finding

`stop()` could overwrite a terminal snapshot (`success`/`partial`/`failed`/`stopped`) with `stopping` if the worker had already published its final result but had not yet cleared `self._thread` in the worker `finally` block.

### Root cause

`stop()` treated any live worker thread as stoppable-in-progress state and unconditionally rewrote the snapshot unless it was already `stopping`. That state transition was too broad for the post-publish/pre-thread-clear window.

### RED

Added a deterministic regression test that pauses the worker immediately after `_publish_result()` returns, keeping the worker thread alive while exposing the terminal snapshot window.

Command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_controller.WarehouseScanControllerTests.test_stop_preserves_terminal_snapshot_before_worker_thread_clears -v
```

Observed failure before the fix:

```text
AssertionError: 'stopping' != 'success'
```

### GREEN

Changed `WarehouseScanController.stop()` so it only rewrites the snapshot when the current state is exactly `running`. If the worker has already published a terminal result, `stop()` still sets the cooperative stop event and returns the same public message, but it preserves the terminal snapshot.

Focused verification:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_controller.WarehouseScanControllerTests.test_stop_preserves_terminal_snapshot_before_worker_thread_clears -v
```

Result:

```text
Ran 1 test in 0.014s

OK
```

Full controller verification:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_controller -v
```

Result:

```text
Ran 5 tests in 0.030s

OK
```

Related warehouse regressions:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_store -v
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_parser -v
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_scanner_replay -v
```

Result:

```text
Ran 9 tests in 0.512s
OK

Ran 7 tests in 0.010s
OK

Ran 7 tests in 1.369s
OK
```

### Files changed in this fix round

- `src/warehouse/controller.py`
- `tests/warehouse/test_controller.py`

### Remaining concerns

- `stop()` still returns `"Warehouse scan stop requested."` even if a terminal snapshot has already been published but the worker thread has not yet cleared. This preserves the existing public contract requested by the task, but callers should rely on `snapshot()` for the authoritative terminal state.
