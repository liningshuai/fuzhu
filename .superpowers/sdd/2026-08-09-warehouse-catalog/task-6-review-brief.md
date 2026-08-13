# Task 6 review brief: warehouse panel

## Scope

Review the manual warehouse catalog panel implementation and its recovery from a failed intermediate JavaScript patch.

## Requirements

- `index.html` exposes manual scan/stop controls and progress fields.
- `app.js` calls `/api/warehouse/scan`, `/api/warehouse/stop`, and polls `/api/warehouse/status` through the existing bounded status interval.
- Running/stopping states disable scan appropriately; idle/terminal states disable stop appropriately.
- Existing挂机 controls and task-list dirty-state behavior remain intact.
- The panel is manual-only and must not start挂机 or the emulator.
- New UI text must be valid UTF-8 and JavaScript must pass syntax checking.

## Evidence already run

- `node --check src/web/static/app.js`
- `.venv\\Scripts\\python.exe -B -m unittest tests.web.test_warehouse_panel_static -v`

## Files to inspect

- `src/web/templates/index.html`
- `src/web/static/app.js`
- `src/web/static/style.css`
- `tests/web/test_warehouse_panel_static.py`
- `src/web/app.py`
- `src/warehouse/controller.py`

## Review output

Report Critical/Important/Minor findings with file and line references. Do not edit files. State whether Task 6 is safe to continue to full regression.
