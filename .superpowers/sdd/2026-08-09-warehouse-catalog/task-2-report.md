# Task 2 Report

## Changed files

- `config/warehouse.yaml`
- `src/config.py`
- `src/warehouse/parser.py`
- `tests/warehouse/test_parser.py`

## RED

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_parser -v
```

Output:

```text
test_parser (unittest.loader._FailedTest.test_parser) ... ERROR

======================================================================
ERROR: test_parser (unittest.loader._FailedTest.test_parser)
----------------------------------------------------------------------
ImportError: Failed to import test module: test_parser
Traceback (most recent call last):
  File "C:\Users\liningshuai\AppData\Local\Programs\Python\Python312\Lib\unittest\loader.py", line 137, in loadTestsFromName
    module = __import__(module_name)
             ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\liningshuai\Desktop\code\兵临天下辅助\tests\warehouse\test_parser.py", line 8, in <module>
    from src.config import load_warehouse_config
ImportError: cannot import name 'load_warehouse_config' from 'src.config'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

## Implementation summary

- Added dedicated warehouse config loader that reads only `config/warehouse.yaml` and returns a safe copy.
- Added warehouse layout config with the required five categories, four-column grid, and explicit icon/text/name/quantity ROIs.
- Implemented item-name normalization with Unicode NFKC, punctuation spacing cleanup, and casefolded whitespace-free output.
- Implemented deterministic icon hashing from resized PNG bytes.
- Implemented visible-card parsing that:
  - OCRs only the configured text ROI
  - preserves card/icon PNG evidence
  - derives `bbox` as `(x, y, width, height)`
  - keeps empty-name observations for review
  - marks low-confidence names for review

## GREEN

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_parser -v
```

Output:

```text
test_load_warehouse_config_reads_yaml_without_shared_mutable_state (tests.warehouse.test_parser.WarehouseParserTests.test_load_warehouse_config_reads_yaml_without_shared_mutable_state) ... ok
test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup (tests.warehouse.test_parser.WarehouseParserTests.test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup) ... ok
test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty) ... ok
test_parse_visible_cards_marks_low_confidence_name_for_review (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_marks_low_confidence_name_for_review) ... ok
test_sha256_icon_is_stable_for_identical_icon_arrays (tests.warehouse.test_parser.WarehouseParserTests.test_sha256_icon_is_stable_for_identical_icon_arrays) ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.005s

OK
```

## Concerns

- `parse_visible_cards` currently picks the single best OCR fragment per name/quantity ROI; if real screenshots split a name across multiple OCR boxes, the next task may need a merge rule.
- Empty-slot filtering currently relies on icon pixels or OCR evidence rather than a dedicated card-presence detector; if the real warehouse UI contains decorative empty cards, detection may need tightening.

---

## Task 2 fix round: test hardening

### Scope

- Added a regression test proving importing and reloading `src.warehouse.parser` does not load `rapidocr_onnxruntime`, instantiate `RapidOCR`, or touch OCR models.
- Added a regression test proving `load_warehouse_config()` does not modify `config/runtime.yaml` by snapshotting file existence, bytes, and `mtime_ns` before and after the call.

### Changed files

- `tests/warehouse/test_parser.py`
- `.superpowers/sdd/2026-08-09-warehouse-catalog/task-2-report.md`

### TDD / verification note

- For this fix round, the newly added regression tests passed on the first run. That means the approved implementation already satisfied the required behavior and this round closed the reviewer-noted coverage gap rather than correcting production behavior.

### Verification

Command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_parser -v
```

Output:

```text
test_importing_parser_does_not_load_or_instantiate_rapidocr (tests.warehouse.test_parser.WarehouseParserTests.test_importing_parser_does_not_load_or_instantiate_rapidocr) ... ok
test_load_warehouse_config_does_not_modify_runtime_yaml (tests.warehouse.test_parser.WarehouseParserTests.test_load_warehouse_config_does_not_modify_runtime_yaml) ... ok
test_load_warehouse_config_reads_yaml_without_shared_mutable_state (tests.warehouse.test_parser.WarehouseParserTests.test_load_warehouse_config_reads_yaml_without_shared_mutable_state) ... ok
test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup (tests.warehouse.test_parser.WarehouseParserTests.test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup) ... ok
test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty) ... ok
test_parse_visible_cards_marks_low_confidence_name_for_review (tests.warehouse.test_parser.WarehouseParserTests.test_parse_visible_cards_marks_low_confidence_name_for_review) ... ok
test_sha256_icon_is_stable_for_identical_icon_arrays (tests.warehouse.test_parser.WarehouseParserTests.test_sha256_icon_is_stable_for_identical_icon_arrays) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.008s

OK
```

### Concerns

- The import/reload regression test is intentionally isolated with `sys.modules` patching so it does not attempt any real OCR dependency import or model loading.
- The runtime config regression test proves non-mutation of the on-disk `runtime.yaml`, but it does not assert anything about unrelated in-memory global config state because the reviewer request was file-safety specific.
