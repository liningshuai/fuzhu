# 仓库物品资料采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manually triggered warehouse catalog scanner that OCRs all five warehouse categories, stores item/icon evidence in SQLite, and returns to main city after a complete scan.

**Architecture:** Keep this feature outside `BaseTask` and the挂机 registry. Add a focused `src/warehouse/` package containing the SQLite store, OCR/card parser, scanner state machine, and a single background controller used by 8787. Reuse `AdbDevice`, `TemplateMatcher`, `TaskContext` session checks, existing navigation/recovery, and the established 1080×1920 screenshot coordinate system.

**Tech Stack:** Python 3.10+, SQLite (`sqlite3`), OpenCV, NumPy, RapidOCR backend already present in `src/pipeline/recognizers.py`, FastAPI, vanilla JavaScript, `unittest`.

## Global Constraints

- The feature is a manual catalog utility, not a daily task and not part of the挂机 loop.
- The normal path must finish all five categories before returning to main city.
- OCR is permitted only for warehouse catalog text extraction; OCR must not decide click coordinates.
- Every scroll, retry, and stop-wait loop is bounded.
- The scanner must never click “一键使用” or any item card action button.
- A running挂机 engine blocks a new warehouse scan instead of being interrupted.
- Database writes happen after each page so partial scans remain recoverable.
- This workspace is not a Git repository; do not initialize Git, create a worktree, or commit changes.

---

## File Map

Create these focused modules:

- `src/warehouse/models.py`: category specs, observations, scan state, and result dataclasses.
- `src/warehouse/store.py`: SQLite schema, migrations, transactions, upsert and observation queries.
- `src/warehouse/parser.py`: grid crops, OCR adapter calls, name normalization, icon hashing.
- `src/warehouse/scanner.py`: bounded five-category navigation and page collection.
- `src/warehouse/controller.py`: one background scan thread, stop event, and status snapshot.
- `config/warehouse.yaml`: category order, ROI/grid calibration, OCR threshold, and loop limits.

Modify:

- `src/web/app.py`: warehouse scan/status/stop endpoints.
- `src/web/templates/index.html`: manual warehouse scan panel.
- `src/web/static/app.js`: scan controls and polling display.
- `src/web/static/style.css`: only the small status-panel styles required by the new controls.
- `src/config.py`: load the warehouse configuration without writing it into `runtime.yaml`.
- `src/adb/device.py` only if a focused test proves an existing swipe/screenshot interface is insufficient; otherwise reuse it unchanged.

Create assets after implementation is approved and the emulator is on the supplied screens:

- `assets/templates/warehouse_entry.png`
- `assets/templates/warehouse_title.png`
- `assets/templates/warehouse_back.png`
- `assets/templates/warehouse_tab_items.png`
- `assets/templates/warehouse_tab_skill_fragments.png`
- `assets/templates/warehouse_tab_arms_fragments.png`
- `assets/templates/warehouse_tab_treasure_fragments.png`
- `assets/templates/warehouse_tab_specialties.png`
- `assets/screenshots/warehouse_reference_*.png`

Tests:

- `tests/warehouse/test_store.py`
- `tests/warehouse/test_parser.py`
- `tests/warehouse/test_scanner_replay.py`
- `tests/warehouse/test_controller.py`
- `tests/web/test_warehouse_api.py`

---

### Task 1: Define warehouse models and SQLite store

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

- [ ] **Step 1: Write failing schema and transaction tests.**

  Test that a temporary database creates `scan_sessions`, `warehouse_items`, and `warehouse_observations`; a page transaction creates one item and one observation; a repeated observation with the same category/name/hash updates `last_seen_at` instead of inserting an unbounded duplicate.

- [ ] **Step 2: Run the store tests and confirm the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
  ```

  Expected: import or missing-method failures before implementation.

- [ ] **Step 3: Implement the SQLite schema with explicit constraints.**

  Use `CREATE TABLE IF NOT EXISTS`, foreign keys, UTC ISO timestamps, and a unique index on `(category_code, name_normalized, icon_hash)`. Store image paths relative to the project root and commit one transaction per page.

- [ ] **Step 4: Run the store tests and verify GREEN.**

  The temporary database tests must pass without creating `data/warehouse_catalog/catalog.db` in the test checkout.

---

### Task 2: Implement configuration, OCR result normalization, and card parser

**Files:**
- Create: `config/warehouse.yaml`
- Create: `src/warehouse/parser.py`
- Create: `tests/warehouse/test_parser.py`
- Modify: `src/config.py`

**Interfaces:**
- `load_warehouse_config() -> dict`.
- `normalise_item_name(value: str) -> str` using Unicode NFKC and whitespace/punctuation cleanup.
- `sha256_icon(image: np.ndarray) -> str` after deterministic resize/PNG encoding.
- `parse_visible_cards(screen: np.ndarray, layout: dict, ocr_backend: OcrBackend) -> list[ItemObservation]`.

- [ ] **Step 1: Write parser tests for normalization, confidence, and deterministic hashing.**

  Cover full-width text/whitespace normalization, an OCR score below `0.70` setting `needs_review=True`, an empty OCR name still producing a saved observation, and identical icon arrays producing the same hash.

- [ ] **Step 2: Run parser tests and confirm the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.warehouse.test_parser -v
  ```

- [ ] **Step 3: Add the initial bounded layout configuration.**

  Define the five category codes and labels, the four-column grid, the card/icon/name sub-ROIs, `ocr_threshold: 0.70`, `max_swipes_per_category: 30`, and `no_new_page_limit: 2`. Keep coordinates in 1080×1920 logical content coordinates.

- [ ] **Step 4: Implement card parsing using the existing RapidOCR backend contract.**

  Crop each configured card, use OCR only on the name/quantity ROI, preserve the full card and icon bytes, normalize the name, compute the icon hash, and mark missing/low-confidence names for review. Do not click from this module.

- [ ] **Step 5: Run parser tests and verify GREEN.**

  Confirm the parser tests pass and that no OCR provider is instantiated at import time; provider loading must remain lazy so the panel can still start when OCR is unavailable.

---

### Task 3: Add warehouse navigation templates and bounded scanner replay

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

- [ ] **Step 1: Add replay fixtures for the five tabs, repeated pages, and main-city return.**

  Use fake device/matcher objects that expose the existing `tap`, `swipe`, `screenshot`, and `find` contracts. Model one category with two pages, one repeated page, and all five category transitions; assert that only the configured warehouse/tab/back coordinates are clicked and no item card or “一键使用” coordinate is clicked.

- [ ] **Step 2: Run the scanner replay tests and confirm the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.warehouse.test_scanner_replay -v
  ```

- [ ] **Step 3: Prepare stable assets from the provided warehouse screenshots.**

  Normalize the supplied screenshot to the project’s 1080×1920 content coordinates, crop the warehouse entry, title, back button, and five tabs, and save the source replay images. The asset script must use the existing Windows-safe OpenCV file helpers.

- [ ] **Step 4: Implement bounded category scanning.**

  Open the warehouse by template, select each category in configured order, capture the page before swiping, parse and store observations, calculate a page fingerprint from the normalized screen and item hashes, then swipe only while the fingerprint is new and the per-category limits have not been reached. Persist each page before advancing.

- [ ] **Step 5: Implement safe completion and failure cleanup.**

  After all five categories succeed, use the warehouse back template and verify `nav_fief`. On a failure or stop event, stop scanning, mark the session `partial`/`stopped`, and attempt at most two safe back/verification rounds. Never substitute a blind tap for a missing navigation template.

- [ ] **Step 6: Run scanner replay tests and verify GREEN.**

  Confirm the five-category success path returns to main city, repeated pages stop, max swipes stop, OCR failures preserve card evidence, and stop requests do not enter the next category.

---

### Task 4: Add the single background scan controller

**Files:**
- Create: `src/warehouse/controller.py`
- Create: `tests/warehouse/test_controller.py`
- Modify: `src/bot/engine.py` only if a read-only running-state accessor is not already available.

**Interfaces:**
- `WarehouseScanController.start() -> str`.
- `WarehouseScanController.stop() -> str`.
- `WarehouseScanController.snapshot() -> dict[str, Any]`.

- [ ] **Step 1: Write controller tests for duplicate start, running挂机 rejection, stop, and final result.**

  Patch the scanner with a deterministic fake. Assert that a second start is rejected, `engine.status()['running'] == True` rejects a scan, `stop()` sets the event, and the final snapshot includes scan ID, status, category, page, item count, and message.

- [ ] **Step 2: Run controller tests and confirm the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.warehouse.test_controller -v
  ```

- [ ] **Step 3: Implement one-thread ownership and state transitions.**

  Construct a fresh `TaskContext` from the existing engine device/matcher, open the store, run the scanner in a daemon thread, close the store in `finally`, and publish `idle/running/stopping/success/partial/failed/stopped` states. Do not change task configuration or start the bot engine.

- [ ] **Step 4: Run controller tests and verify GREEN.**

---

### Task 5: Expose the scanner through 8787

**Files:**
- Modify: `src/web/app.py`
- Create: `tests/web/__init__.py`
- Create: `tests/web/test_warehouse_api.py`

**Interfaces:**
- `GET /api/warehouse/status` returns the controller snapshot.
- `POST /api/warehouse/scan` starts one manual scan.
- `POST /api/warehouse/stop` requests a bounded stop.
- `GET /api/warehouse/items?category=<code>` reads catalog rows without starting a scan.

- [ ] **Step 1: Write API tests for status, start, stop, and rejection while挂机.**

  Use the project’s FastAPI test style or a direct route call with a patched controller. Assert the endpoints never call `engine.start()` and return a clear conflict when a scan or挂机 is already active.

- [ ] **Step 2: Run API tests and confirm the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.web.test_warehouse_api -v
  ```

- [ ] **Step 3: Implement the four endpoints and wire one controller instance.**

  Keep the database path local, return HTTP `409` for active-operation conflicts, and return HTTP `503` for an offline device/precondition failure. Do not add warehouse data to `runtime.yaml`.

- [ ] **Step 4: Run API tests and verify GREEN.**

---

### Task 6: Add the manual panel controls and progress display

**Files:**
- Modify: `src/web/templates/index.html`
- Modify: `src/web/static/app.js`
- Modify: `src/web/static/style.css`

**Interfaces:**
- Buttons call `/api/warehouse/scan` and `/api/warehouse/stop`.
- Existing status polling reads `/api/warehouse/status` and renders progress without redrawing unrelated task options.

- [ ] **Step 1: Add the panel markup with disabled-state semantics.**

  Add “扫描仓库” and “停止扫描” controls plus status fields for category, page, categories completed, items found, low-confidence count, and message. The scan button is disabled while running; the stop button is disabled while idle.

- [ ] **Step 2: Add JavaScript request and polling handlers.**

  Display server error text, poll at the existing panel interval, and do not enable any task checkbox or call `/api/bot/start`.

- [ ] **Step 3: Add minimal styles and perform a static browser smoke check.**

  Keep the section visually consistent with existing cards and verify that all controls render when the API is idle, running, successful, partial, and failed.

---

### Task 7: Full offline verification and 8787 synchronization

**Files:**
- Modify only test fixtures or documentation if verification finds a concrete issue.

- [ ] **Step 1: Run the focused warehouse suite.**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests\warehouse -v
  ```

  Expected: all store, parser, scanner, and controller tests pass.

- [ ] **Step 2: Run compile and the complete regression suite.**

  ```powershell
  .\.venv\Scripts\python.exe -m compileall -q src tests scripts
  .\.venv\Scripts\python.exe -m unittest discover -q
  ```

  Expected: exit code `0`, no failed tests.

- [ ] **Step 3: Restart 8787 with the current code and verify idle state.**

  Start `main.py` using `.venv\Scripts\python.exe`, request `/`, `/api/status`, and `/api/warehouse/status`, and verify HTTP `200`, `running=false`, and `warehouse.status=idle`. Do not start挂机 or launch the emulator during this step.

- [ ] **Step 4: Perform the real manual collection.**

  With the emulator logged in and at main city, click “扫描仓库” once. Verify from the panel/logs that all five category codes complete, the SQLite database contains rows, image files exist, and the emulator returns to main city. If OCR confidence is low, report the affected rows rather than silently claiming a complete catalog.

- [ ] **Step 5: Record final acceptance evidence.**

  Report scan ID, five-category completion, item count, low-confidence count, database path, return-to-main-city result, test count, and whether any live collection limitation remains.
