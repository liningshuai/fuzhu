# Task 4: Add the single background scan controller

**Files:**
- Create: `src/warehouse/controller.py`
- Create: `tests/warehouse/test_controller.py`
- Modify: `src/warehouse/scanner.py` only if a small progress callback is required to expose current category/page.
- Modify: `src/bot/engine.py` only if a read-only running-state accessor is not already available.

**Interfaces:**
- `WarehouseScanController.start() -> str`.
- `WarehouseScanController.stop() -> str`.
- `WarehouseScanController.snapshot() -> dict[str, Any]`.

**Global constraints:**
- The feature is a manual catalog utility, not a daily task and not part of the挂机 loop.
- A running挂机 engine rejects a new warehouse scan; the controller must never call engine.start().
- Only one warehouse scan thread may exist at a time; duplicate start is rejected.
- Stop is cooperative and bounded; it sets a stop event and lets the scanner perform its capped cleanup.
- OCR provider construction remains lazy.
- Reuse the engine's current device, matcher, and session guard through a fresh TaskContext. Do not create a second ADB process or restart the game here.
- Store the database under the project-local warehouse catalog path and keep partial results.
- Publish states idle/running/stopping/success/partial/failed/stopped and include scan_id, category, page, categories_completed, items_found, low_confidence_count, and message in snapshots.

**Test-first work:**

1. Write controller tests with a deterministic fake scanner and fake engine for duplicate start, running挂机 rejection, stop event propagation, final result publication, and snapshot fields.
2. Run:

   `.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_controller -v`

   Confirm RED before implementation.
3. Implement one daemon thread, a lock-protected state snapshot, a stop event, bounded thread join behavior, and cleanup in `finally`. Do not block the web request on the scan.
4. If progress fields cannot be filled from the existing scanner, add one optional progress callback with a no-op default; keep the scanner's public constructor compatible and update replay tests only as needed.
5. Run the focused controller test and the existing store/parser/scanner tests.

Read `src/bot/engine.py`, `src/tasks/base.py`, `src/warehouse/scanner.py`, `src/config.py`, and the Task 1/2 reports before editing. Do not start 8787 or operate the emulator. This workspace is not a Git repository; do not initialize Git or commit. Write a detailed report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-4-report.md` with RED/GREEN evidence, changed files, and concerns. Return a short status summary only.
