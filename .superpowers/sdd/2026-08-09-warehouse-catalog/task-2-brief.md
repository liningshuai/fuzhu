# Task 2: Implement configuration, OCR result normalization, and card parser

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

**Requirements:**

- The feature is a manual catalog utility, not a daily task and not part of the挂机 loop.
- OCR is permitted only for warehouse catalog text extraction; OCR must not decide click coordinates.
- Every scroll, retry, and stop-wait loop is bounded.
- Use the existing RapidOCR backend contract and keep provider loading lazy; importing the parser must not instantiate OCR.
- Preserve card and icon evidence even when OCR returns an empty name; mark low-confidence names for review.
- Use the existing 1080×1920 logical content coordinate system.
- Do not write warehouse settings into `runtime.yaml`.

**Test-first work:**

1. Write parser tests for Unicode/whitespace normalization, confidence below 0.70 setting `needs_review=True`, an empty OCR name still producing a saved observation, and identical icon arrays producing the same hash.
2. Run:

   `.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_parser -v`

   Confirm the expected RED state before implementation.
3. Add `config/warehouse.yaml` with the five category codes and labels, a four-column grid, card/icon/name sub-ROIs, `ocr_threshold: 0.70`, `max_swipes_per_category: 30`, and `no_new_page_limit: 2`.
4. Implement card parsing using the existing `src.pipeline.recognizers.OcrBackend` / `OcrText` contract. Crop each configured card, OCR only the name/quantity ROI, preserve full card and icon bytes, normalize the name, compute the icon hash, and mark missing/low-confidence names for review. Do not click from this module.
5. Run the focused parser tests and report the output.

Read the existing `src/config.py` and `src/pipeline/recognizers.py` before editing. Do not start 8787 or operate the emulator. Write a report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-2-report.md` with changed files, RED/GREEN evidence, test results, and concerns. This workspace is not a Git repository; do not initialize Git or commit.
