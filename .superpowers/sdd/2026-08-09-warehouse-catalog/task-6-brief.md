# Task 6: Add the manual panel controls and progress display

**Files:**
- Modify: `src/web/templates/index.html`
- Modify: `src/web/static/app.js`
- Modify: `src/web/static/style.css`

**Interfaces:**
- Buttons call `/api/warehouse/scan` and `/api/warehouse/stop`.
- Existing status polling reads `/api/warehouse/status` and renders progress without redrawing unrelated task options.

**Global constraints:**
- This is a manual catalog utility, not a daily task and not part of the挂机 controls.
- The panel must never call `/api/bot/start`, enable a task checkbox, or change runtime task configuration.
- Scan button disabled while status is running/stopping; stop button disabled while idle or terminal.
- Render category, page, categories completed, items found, low-confidence count, status, and message.
- Display server 409/503 error messages without breaking the existing status panel.
- Keep the existing task list dirty-state behavior intact.

**Test-first / smoke work:**

1. Add a static test or deterministic DOM-oriented check for panel markup, endpoint strings, disabled-state logic, and preservation of the existing bot controls.
2. Run the focused UI/static test command used by the project and confirm RED before implementation.
3. Add minimal HTML, JavaScript, and CSS. Poll the warehouse endpoint at the existing panel interval or a single additional bounded interval; do not create overlapping unbounded timers.
4. Verify idle/running/stopping/success/partial/failed/stopped rendering with deterministic fixtures. A live browser/device is not required in this task; defer live 8787 verification to Task 7.

Read the existing index.html/app.js/style.css and Task 5 API report before editing. Do not start 8787 or operate the emulator. This workspace is not a Git repository; do not initialize Git or commit. Write a detailed report to `.superpowers/sdd/2026-08-09-warehouse-catalog/task-6-report.md` with test/smoke evidence and concerns. Return a short status summary only.
