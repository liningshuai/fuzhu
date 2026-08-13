# Final review fix report

Date: 2026-08-07

commit=none

## Scope

- Modified `src/session/activity_popup.py`
- Modified `tests/session/test_activity_popup.py`
- Modified `src/session/startup.py`
- Modified `tests/session/test_startup_replay.py`

No Git initialization, no worktree, no commit, no simulator launch.

## Finding 1: generic gating drifted from design/brief

Original finding:

- `nav_fief` used `main_city_threshold - 0.15`, making the default anchor threshold 0.75 instead of the explicit 0.90 contract.
- dim/darkness was measured over the full screen instead of the fixed central activity `panel_region`.
- missing negative coverage for no main-city anchor, insufficient dimming, and missing central panel structure.

Technical judgment:

- The main-city anchor is a prerequisite for "main city underlay exists"; lowering it widens generic activity detection beyond the brief.
- Full-screen dimming can be distorted by unrelated screen areas. The safer signal is bounded to the configured `panel_region`, sampling edge bands around the central activity panel so the bright panel body does not hide the dim overlay.

Fix:

- Generic `nav_fief` now calls matcher with `threshold=self.main_city_threshold` (default 0.90).
- Added `_measure_dimming()` using bounded samples inside `panel_region` edge bands; kept `dim_mean_max=92.0` and `dark_fraction_min=0.35`.
- Kept central panel structure gating via edge/contour/contrast score.
- Stabilized generic match contract as `source="generic"` and `reason="main-city-underlay+dim-overlay+central-panel"`.

Regression tests:

- `test_generic_detection_uses_configured_main_city_anchor_threshold`
- `test_detect_returns_none_when_activity_roi_is_not_dimmed`
- `test_detect_returns_none_when_central_panel_structure_is_missing`
- Existing bright main-city and missing anchor/image-failure negatives remain covered.

## Finding 2: business popup isolation insufficient

Original finding:

- Known blockers missed `dialog_confirm_tight`, `legend_buy_confirm`, and `legend_buy_confirm_area`.
- All blocker checks used a blanket 0.90 threshold instead of task-specific or conservative known thresholds.

Technical judgment:

- Business confirmations must block generic activity detection before any safe-blank dismissal is considered.
- Existing task/navigation code already uses lower, bounded thresholds for these templates; mirroring those thresholds with optional regions is safer than both blanket 0.90 and arbitrary very-low thresholds.

Fix:

- Replaced `EXCLUDED_TEMPLATES` with `BLOCKER_TEMPLATES` containing per-template thresholds:
  - duplicate login: 0.78
  - guoguan buy title/confirm: 0.70/0.72
  - legend buy title/confirm/confirm_area: 0.82/0.70/0.58, with legend buy regions for low-threshold blockers
  - dialog title/confirm_tight/confirm: 0.78/0.82/0.80
  - startup announcement/enter/permanent blockers: 0.90
- Added `dialog_confirm_tight`, `legend_buy_confirm`, and `legend_buy_confirm_area`.
- A blocker template failure now skips only that blocker; a blocker hit still returns `None` before activity detection.

Regression tests:

- `test_weak_business_blockers_prevent_generic_activity_detection`
- Existing `test_detect_stops_on_business_blocker_before_activity_templates`
- Existing startup replay business popup test remains passing.

## Finding 3: template/image exceptions should degrade per item

Original finding:

- A single optional `startup_activity_*.png` read/match failure aborted the whole detector.
- Need coverage that later valid activity templates still match, while `nav_fief` or image conversion failure remains safe.

Technical judgment:

- Optional blocker/activity templates should be best-effort candidates. One bad optional asset should not mask a later valid dedicated activity template.
- Generic detection prerequisites are different: if main-city anchor lookup or image conversion fails, the conservative result is `None`.

Fix:

- Blocker checks catch exceptions per blocker and continue.
- Activity template discovery catches glob errors and per-template matcher errors; bad candidates are skipped.
- Generic detection catches `nav_fief` matcher failure and returns `None`.
- Overall detector remains no-click and returns only `ActivityPopupMatch | None`.
- Stabilized dedicated-template match contract as `source="template"` with the template name in `reason`.

Regression tests:

- `test_bad_activity_template_is_skipped_before_later_valid_template`
- `test_detect_returns_none_for_nav_fief_or_image_conversion_failures`
- Existing non-numpy and missing template-dir safety tests remain passing.

## Minor: activity dismissal limit diagnostics

Original finding:

- `GameStartupTimeout` for activity dismissal limit should retain the numeric limit and include the last `ActivityPopupMatch` source/reason.

Fix:

- Limit exception message now includes the numeric limit plus `last_activity_source` and `last_activity_reason`.
- Activity dismissal log now includes source, reason, score, and count/max.

Regression test:

- `test_activity_dismissal_limit_raises_after_two_taps` now asserts the limit, last source, and last reason.

## Test evidence

RED evidence before implementation:

- `.\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v`
  - Failed 7 detector tests covering template source/reason, bad template skip, `nav_fief` threshold, and weak/new blockers.
- `.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_replay -v`
  - Failed activity dismissal limit diagnostic assertion because the exception omitted `activity_3` and `fake replay match`.

GREEN / final evidence:

- `.\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup tests.session.test_startup tests.session.test_startup_replay tests.session.test_startup_template_assets -v`
  - Ran 31 tests, OK.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  - Ran 80 tests, OK.
- `.\.venv\Scripts\python.exe -m compileall -q src tests`
  - Exit code 0.

