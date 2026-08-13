# Task 2 Review Package (non-Git workspace)

This project is intentionally not a Git repository, so no BASE/HEAD or Git
diff exists. Review the current Task 2 files directly against the brief and
the global constraints. Do not mutate the workspace.

## Files

- `config/warehouse.yaml`
- `src/config.py`
- `src/warehouse/parser.py`
- `tests/warehouse/test_parser.py`
- `.superpowers/sdd/2026-08-09-warehouse-catalog/task-2-report.md`

## Attention lens

Check exact five-category order and bounded values, 1080x1920 coordinate
semantics, lazy OCR loading, OCR limited to the configured text ROI, evidence
preservation for empty names, deterministic normalization/hash behavior, and
that warehouse config is not merged into or written to runtime.yaml.
