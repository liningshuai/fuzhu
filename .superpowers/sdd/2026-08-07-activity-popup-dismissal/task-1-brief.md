# Task 1: Implement and test the activity popup detector

Create `src/session/activity_popup.py` and `tests/session/test_activity_popup.py`; export the public types from `src/session/__init__.py`.

Implement frozen `ActivityPopupMatch(source: str, confidence: float, reason: str)` and `ActivityPopupDetector(matcher, panel_region=(20,400,1040,1250), main_city_threshold=0.90, dim_mean_max=92.0, dark_fraction_min=0.35, panel_score_min=0.55, confidence_min=0.70)`. `detect(screen)` only recognizes and never taps. It must safely return None for non-NumPy inputs, missing `template_dir`, missing templates, or image failures.

Detection order: business blockers first; then auto-discovered `startup_activity_*.png` templates; then conservative generic detection. Generic detection requires low-threshold `nav_fief` underlay, dim overlay (mean and dark-pixel fraction), and central panel structure from Canny/contours/local contrast. It must return None if any condition fails. Exclude `duplicate_login_message`, `duplicate_login_confirm`, `guoguan_buy_title`, `guoguan_buy_confirm`, `legend_buy_title`, `dialog_nation_title`, `dialog_confirm`, `startup_announcement_claim`, `startup_enter_game`, and `startup_permanent_claim` when present. Scores must be normalized and generic confidence must meet the configured minimum.

TDD: write tests first and run `\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v` to observe the expected failure. Use synthetic NumPy screens: dark background plus bright central panel for positive, uniform bright clear screen for negative, fake matcher with/without nav_fief and with business blockers. Then implement and rerun the focused test. Do not modify task logic or click the device.

Global constraints: 1080x1920 vertical baseline; only startup flow will later perform the safe blank click `(30,500)`; no Git initialization or commits.
