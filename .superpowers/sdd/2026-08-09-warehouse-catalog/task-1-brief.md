# Task 1: Define warehouse models and SQLite store

**Files:**
- Create: `src/warehouse/__init__.py`
- Create: `src/warehouse/models.py`
- Create: `src/warehouse/store.py`
- Create: `tests/warehouse/__init__.py`
- Create: `tests/warehouse/test_store.py`

**Interfaces:**
- `WarehouseCategory(code: str, label: str, order: int)`.
- `ItemObservation(category_code: str, name_raw: str, name_normalized: str, quantity_text: str, ocr_confidence: float, icon_bytes: bytes, card_bytes: bytes, icon_hash: str, page_index: int, screen_path: str, bbox: tuple[int, int, int, int], needs_review: bool)`.
- `WarehouseScanResult(status: str, scan_id: str, categories_completed: int, items_found: int, low_confidence_count: int, message: str)`.
- `WarehouseCatalogStore(path: Path)` with `open()`, `start_scan()`, `upsert_observation()`, `finish_scan()`, `get_items(category_code: str | None = None)`, and `close()`.

**Requirements:**

- The feature is a manual catalog utility, not a daily task and not part of the挂机 loop.
- Use local SQLite with tables `scan_sessions`, `warehouse_items`, and `warehouse_observations`.
- Use foreign keys, UTC ISO timestamps, and a unique index on `(category_code, name_normalized, icon_hash)`.
- Store image paths relative to the project root.
- Commit one transaction per page through the store API.
- Temporary tests must not create the production database path.
- This workspace is not a Git repository; do not initialize Git, create a worktree, or commit changes.

**Test-first work:**

1. Test schema creation, one observation plus one observation row, and repeated same-key observations updating `last_seen_at` without unbounded duplicates.
2. Run `.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v` and confirm RED before implementation.
3. Implement the minimal store and models.
4. Re-run the focused tests and report the output.

Write a report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-1-report.md` containing changed files, test commands/results, and concerns. Return only a short status summary after writing the report. Do not touch 8787, the emulator, or unrelated task files.
