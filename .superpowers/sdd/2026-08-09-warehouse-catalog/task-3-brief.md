# Task 3: Add warehouse navigation templates and bounded scanner replay

**Files:**
- Create: `src/warehouse/scanner.py`
- Create: `tests/warehouse/test_scanner_replay.py`
- Create: `scripts/prepare_warehouse_assets.py`
- Create: `assets/screenshots/warehouse_reference_*.png`
- Create: `assets/templates/warehouse_*.png`

**Interfaces:**
- `WarehouseScanner(ctx: TaskContext, store: WarehouseCatalogStore, config: dict, ocr_backend: OcrBackend, stop_event: threading.Event | None = None)`.
- `WarehouseScanner.scan() -> WarehouseScanResult`.
- Internal bounded methods: `_open_warehouse()`, `_scan_category(category)`, `_collect_page()`, `_advance_page()`, `_close_to_main_city()`.

**Global constraints:**
- This is a manual catalog utility, not a daily task and not part of the挂机 loop.
- The normal path must finish all five categories before returning to main city.
- OCR may extract text only; it must not decide click coordinates.
- Every scroll/retry/stop-wait loop is bounded.
- Never click item cards or the 一键使用 action.
- A running挂机 engine is handled by the later controller; this scanner itself must not start it.
- Database writes happen page by page; use Task 1's upsert_page() and record_category_completion().
- On stop/failure preserve completed pages and attempt at most two safe return-to-main-city rounds.
- Do not invent live template pixels. Use the supplied source screenshots when preparing assets; if a source crop cannot be safely inferred, fail the asset script clearly and leave a documented limitation.

**Replay requirements:**

1. Write fake-device/fake-matcher replay tests first. Model one category with two new pages followed by a repeated page, all five tab transitions, and a main-city return. Assert only configured warehouse/tab/back coordinates are tapped; no item-card or 一键使用 coordinate is tapped.
2. Run:

   `.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_scanner_replay -v`

   Confirm RED before implementation.
3. Implement `scripts/prepare_warehouse_assets.py` using OpenCV. It must read the supplied warehouse screenshot sources, normalize to 1080x1920 logical coordinates, save reference screenshots, and crop the warehouse entry/title/back button/five tabs into `assets/templates/warehouse_*.png`. Keep the source paths configurable and do not silently create placeholder templates.
4. Implement bounded scanner navigation. Use template names and fixed configured click centers for navigation; OCR is only passed to parse_visible_cards. Capture and persist each page before swiping, fingerprint normalized screen/item hashes, stop after max swipes or no-new-page limit, and explicitly mark each category complete including empty categories.
5. Implement safe cleanup: after success use the warehouse back template and verify `nav_fief` before returning success; on stop/failure make at most two safe back/verification rounds and return the corresponding stopped/partial/failed result.
6. Add replay tests for successful five-category completion, repeated-page stop, max-swipe bound, OCR failure preserving card evidence, and stop preventing the next category.

**Supplied source screenshots:**
- `C:\Users\liningshuai\AppData\Local\Temp\codex-clipboard-c6af9293-b499-482e-94c2-4bcae1471a28.png` (warehouse screen)
- `C:\Users\liningshuai\AppData\Local\Temp\codex-clipboard-657b99e6-a608-46de-834e-3c9942293eed.png` (main-city screen)

Read existing `src/tasks/base.py`, `src/adb/device.py`, `src/vision/match.py`, `src/tasks/navigation.py`, the Task 1/2 modules, and the source screenshots before editing. Do not start 8787 or operate the emulator. This workspace is not a Git repository; do not initialize Git or commit. Write a detailed report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-3-report.md` with RED/GREEN evidence, changed files, asset paths, and any limitations. Return a short status summary only.
