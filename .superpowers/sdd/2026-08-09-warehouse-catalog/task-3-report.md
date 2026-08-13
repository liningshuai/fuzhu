# Task 3 Report

## Changed files

- `config/warehouse.yaml`
- `scripts/prepare_warehouse_assets.py`
- `src/warehouse/__init__.py`
- `src/warehouse/scanner.py`
- `tests/warehouse/test_scanner_replay.py`
- `assets/screenshots/warehouse_reference_main_city.png`
- `assets/screenshots/warehouse_reference_screen.png`
- `assets/templates/warehouse_back.png`
- `assets/templates/warehouse_entry.png`
- `assets/templates/warehouse_tab_arms_fragments.png`
- `assets/templates/warehouse_tab_items.png`
- `assets/templates/warehouse_tab_skill_fragments.png`
- `assets/templates/warehouse_tab_specialties.png`
- `assets/templates/warehouse_tab_treasure_fragments.png`
- `assets/templates/warehouse_title.png`

## RED

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_scanner_replay -v
```

Output:

```text
test_scanner_replay (unittest.loader._FailedTest.test_scanner_replay) ... ERROR

======================================================================
ERROR: test_scanner_replay (unittest.loader._FailedTest.test_scanner_replay)
----------------------------------------------------------------------
ImportError: Failed to import test module: test_scanner_replay
Traceback (most recent call last):
  File "C:\Users\liningshuai\AppData\Local\Programs\Python\Python312\Lib\unittest\loader.py", line 137, in loadTestsFromName
    module = __import__(module_name)
             ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\liningshuai\Desktop\code\�������¸���\tests\warehouse\test_scanner_replay.py", line 13, in <module>
    from src.warehouse.scanner import WarehouseScanner
ModuleNotFoundError: No module named 'src.warehouse.scanner'


----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

## Implementation summary

- Added `WarehouseScanner` with bounded open/category/cleanup flow:
  - opens the warehouse only when the configured entry template is visible
  - taps only configured entry/tab/back coordinates
  - captures a screenshot file before each page parse
  - fingerprints normalized screen pixels plus item hashes
  - stops a category on repeated-page limit or max-swipe limit
  - records category completion even for empty categories
  - returns success/stopped/partial/failed scan results without inventing navigation
- Added replay tests with fake device, fake matcher, and fake store for:
  - five-category success with safe return to main city
  - repeated-page stop
  - max-swipe bound
  - low-confidence OCR evidence preservation
  - stop event preventing the next category
- Added `prepare_warehouse_assets.py`:
  - reads the two supplied screenshots
  - applies only known-safe viewport defaults (`549x975` full warehouse viewport, `588x1014 -> 0,39,549,975` main-city viewport)
  - fails clearly for unknown source sizes unless explicit viewport overrides are supplied
  - normalizes references to `1080x1920`
  - writes warehouse reference screenshots and template crops
- Updated `config/warehouse.yaml` with tab templates, tap centers, navigation coordinates, swipe bounds, and artifact directory.

## GREEN

Verification command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store tests.warehouse.test_parser tests.warehouse.test_scanner_replay -v
```

Output:

```text
test_finish_scan_counts_explicitly_completed_empty_categories (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_finish_scan_counts_explicitly_completed_empty_categories) ... ok
test_finish_scan_counts_low_confidence_items_needing_review (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_finish_scan_counts_low_confidence_items_needing_review) ... ok
test_open_creates_required_schema_with_foreign_keys_and_unique_item_key (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_open_creates_required_schema_with_foreign_keys_and_unique_item_key) ... ok
test_repeated_same_key_updates_last_seen_without_duplicate_items (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_repeated_same_key_updates_last_seen_without_duplicate_items) ... ok
test_upsert_observation_creates_one_item_and_one_observation_row (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_upsert_observation_creates_one_item_and_one_observation_row) ... ok
test_upsert_observation_rejects_absolute_screen_path_outside_project_root (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_upsert_observation_rejects_absolute_screen_path_outside_project_root) ... ok
test_upsert_page_is_atomic_for_all_observations_on_a_page (tests.warehouse.test_store.WarehouseCatalogStoreTests.test_upsert_page_is_atomic_for_all_observations_on_a_page) ... ok
test_importing_parser_does_not_load_or_instantiate_rapidocr (tests.warehouse.test_parser.WarehouseParserTests.test_importing_parser_does_not_load_or_instantiate_rapidocr) ... ok
test_load_warehouse_config_does_not_modify_runtime_yaml (tests.warehouse.test_parser.WarehouseParserTests.test_load_warehouse_config_does_not_modify_runtime_yaml) ... ok
test_load_warehouse_config_reads_yaml_without_shared_mutable_state (tests.warehouse.test_parser.WarehouseParserTests.test_load_warehouse_config_reads_yaml_without_shared_mutable_state) ... ok
test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup (tests.warehouse.test_parser.WarehouseParserTests.test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup) ... ok
test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty) ... ok
test_parse_visible_cards_marks_low_confidence_name_for_review (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_marks_low_confidence_name_for_review) ... ok
test_sha256_icon_is_stable_for_identical_icon_arrays (tests.warehouse.test_parser.WarehouseParserTests.test_sha256_icon_is_stable_for_identical_icon_arrays) ... ok
test_scan_completes_all_five_categories_and_returns_to_main_city (tests.warehouse.test_scanner_replay.WarehouseScannerReplayTests.test_scan_completes_all_five_categories_and_returns_to_main_city) ... ok
test_scan_honours_stop_event_before_next_category (tests.warehouse.test_scanner_replay.WarehouseScannerReplayTests.test_scan_honours_stop_event_before_next_category) ... ok
test_scan_preserves_low_confidence_card_evidence (tests.warehouse.test_scanner_replay.WarehouseScannerReplayTests.test_scan_preserves_low_confidence_card_evidence) ... ok
test_scan_respects_max_swipe_bound (tests.warehouse.test_scanner_replay.WarehouseScannerReplayTests.test_scan_respects_max_swipe_bound) ... ok
test_scan_stops_on_repeated_page_without_persisting_duplicate_page (tests.warehouse.test_scanner_replay.WarehouseScannerReplayTests.test_scan_stops_on_repeated_page_without_persisting_duplicate_page) ... ok

----------------------------------------------------------------------
Ran 19 tests in 1.593s

OK
```

Asset prep command:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_warehouse_assets.py
```

Result:

```text
(exit code 0, no stderr/stdout)
```

## Asset paths

- `assets/screenshots/warehouse_reference_main_city.png`
- `assets/screenshots/warehouse_reference_screen.png`
- `assets/templates/warehouse_back.png`
- `assets/templates/warehouse_entry.png`
- `assets/templates/warehouse_tab_arms_fragments.png`
- `assets/templates/warehouse_tab_items.png`
- `assets/templates/warehouse_tab_skill_fragments.png`
- `assets/templates/warehouse_tab_specialties.png`
- `assets/templates/warehouse_tab_treasure_fragments.png`
- `assets/templates/warehouse_title.png`

## Concerns / limitations

- The scanner can return `stopped` / `failed` / `partial` to callers, but Task 1's `finish_scan(scan_id)` still persists a `"success"` session row because that interface does not accept a final status override. I did not invent a new store contract in Task 3.
- The default main-city viewport auto-crop is intentionally narrow: it only auto-accepts the supplied `588x1014` screenshot shape and trims it to `0,39,549,975`. Any different source size now fails fast and asks for an explicit viewport override.
- The supplied main-city screenshot contains a red annotation around the warehouse button. The generated `warehouse_entry` template was cropped down to the interior icon region to avoid carrying annotation pixels, but this remains less proven than a clean live screenshot from ADB.
- Runtime navigation was validated by replay tests only. I did not touch the emulator, so live template match quality against device screenshots is still unproven.

## Fix round 1 (2026-08-09)

### Review findings addressed

1. Extended `WarehouseCatalogStore.finish_scan()` to accept compatible optional `status='success'` and `message=None` arguments, validate final status against `success|partial|failed|stopped`, and persist/return the requested final status and message.
2. Updated `WarehouseScanner` success / partial / stopped / failed paths to pass the actual final status into `finish_scan()` instead of overriding only the returned dataclass after the SQLite row had already been written.
3. Switched stop/failure cleanup to read `config.navigation.max_return_rounds`, while clamping the effective cleanup rounds to the closed interval `[0, 2]`.

### RED

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store tests.warehouse.test_scanner_replay -v
```

Key failures before the fix:

```text
TypeError: WarehouseCatalogStore.finish_scan() got an unexpected keyword argument 'status'
AssertionError: 'success' != 'stopped'
```

These failures proved:

- the real store API could not yet accept/persist non-success final states;
- scanner stop paths were still calling `finish_scan()` as implicit success;
- cleanup-round clamp tests were exercising scanner finish behavior through the real stop path.

### GREEN

Focused verification command required for Task 3:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store tests.warehouse.test_parser tests.warehouse.test_scanner_replay -v
```

Result:

```text
Ran 23 tests in 1.896s

OK
```

### Files changed in this fix round

- `src/warehouse/store.py`
- `src/warehouse/scanner.py`
- `tests/warehouse/test_store.py`
- `tests/warehouse/test_scanner_replay.py`

### Notes

- Existing callers remain compatible because `finish_scan(scan_id)` still defaults to success semantics.
- This fix round supersedes the earlier pre-fix note above about non-success scanner results being persisted as `success`.
- This fix round did not touch `8787`, the emulator, or unrelated task files.
