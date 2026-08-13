# Task 5: Expose the scanner through 8787

**Files:**
- Modify: `src/web/app.py`
- Create: `tests/web/__init__.py`
- Create: `tests/web/test_warehouse_api.py`

**Interfaces:**
- `GET /api/warehouse/status` returns the controller snapshot.
- `POST /api/warehouse/scan` starts one manual scan.
- `POST /api/warehouse/stop` requests a bounded stop.
- `GET /api/warehouse/items?category=<code>` reads catalog rows without starting a scan.

**Global constraints:**
- Warehouse scanning is manual and must never call engine.start() or change task configuration.
- Return HTTP 409 for duplicate scan, scan-vs挂机 conflict, or stopping an idle/non-active scan.
- Return HTTP 503 for an offline device/precondition failure before starting a scan.
- Keep the database project-local and do not put warehouse data/config into runtime.yaml.
- Do not block an HTTP request on the scan worker; start/stop endpoints return promptly.
- Reading items must never start a scan or挂机.

**Test-first work:**

1. Add direct route tests (or the existing FastAPI test style) for idle status, start, stop, duplicate/挂机 rejection, offline 503, and item reads with a category filter. Patch the controller/engine at the app boundary and assert `engine.start()` is never called.
2. Run:

   `.\.venv\Scripts\python.exe -m unittest tests.web.test_warehouse_api -v`

   Confirm RED before implementation.
3. Wire exactly one controller instance in `src/web/app.py`. Keep error messages and status payloads JSON-serializable. Use HTTPException with 409/503 as specified.
4. Run the focused API tests plus warehouse store/parser/scanner/controller tests.

Read `src/web/app.py`, `src/warehouse/controller.py`, `src/warehouse/store.py`, and the existing test style before editing. Do not start 8787 or operate the emulator. This workspace is not a Git repository; do not initialize Git or commit. Write a detailed report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-5-report.md` with RED/GREEN evidence and concerns. Return a short status summary only.
