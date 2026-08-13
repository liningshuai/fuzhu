# Task 1 Report - Activity Popup Detector

## Status

Task 1 completed on 2026-08-07. No commit was created because the project is not a Git repository and the task explicitly prohibited Git initialization or commits.

## Implementation

Implemented a new startup-only recognition component in `src/session/activity_popup.py`:

- Added frozen `ActivityPopupMatch(source, confidence, reason)`.
- Added `ActivityPopupDetector(...)` with the constructor defaults required by the brief.
- Implemented `detect(screen)` as a recognition-only API that never taps the device.
- Enforced detection order:
  1. business/exclusion templates first;
  2. auto-discovered `startup_activity_*.png` templates;
  3. conservative generic popup detection.
- Made detection fail safe by returning `None` for:
  - non-NumPy inputs;
  - missing `matcher.template_dir`;
  - missing/nonexistent template directories;
  - template/image matching failures;
  - generic detection preconditions not satisfied.
- Implemented conservative generic detection requiring all of:
  - low-threshold `nav_fief` underlay;
  - dim-screen checks (`mean` and dark-pixel fraction);
  - central panel structure from Canny edges, contour area, and local contrast;
  - normalized confidence meeting `confidence_min`.

Also updated `src/session/__init__.py` to export:

- `ActivityPopupDetector`
- `ActivityPopupMatch`

## Files Changed

- `C:\Users\liningshuai\Desktop\code\兵临天下辅助\src\session\activity_popup.py`
- `C:\Users\liningshuai\Desktop\code\兵临天下辅助\src\session\__init__.py`
- `C:\Users\liningshuai\Desktop\code\兵临天下辅助\tests\session\test_activity_popup.py`

## TDD Evidence

### RED

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v
```

Key failure:

- `ModuleNotFoundError: No module named 'src.session.activity_popup'`

Interpretation:

- This was the expected initial RED state because the detector module did not exist yet.

### GREEN

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v
```

Result:

- `Ran 7 tests`
- `OK`

Covered behaviors:

- returns `None` for non-NumPy input;
- returns `None` when `template_dir` is missing;
- stops on business blocker templates before activity templates;
- returns a discovered `startup_activity_*` template match;
- returns a generic popup match for a dim overlay with panel structure;
- returns `None` for a bright clear main-city screen;
- returns `None` for template/image matching failures.

## Self-Review

What I checked:

- The implementation stays isolated to the files allowed by the brief.
- `detect(screen)` performs recognition only and does not tap or modify startup/business flow.
- The exclusion list is applied before activity-template recognition.
- Generic detection is gated conservatively and returns `None` unless all required signals are present.
- Public exports were added so the component can be imported from `src.session`.

Additional note:

- I could not perform the Git-SHA-based reviewer dispatch flow from the `requesting-code-review` skill because this project is explicitly not a Git repository. I performed a local self-review instead.

## Risks / Follow-up Notes

- The generic detector is intentionally conservative; real screenshots that differ materially from the synthetic panel shape may require threshold retuning later.
- On any template/image matching exception, the detector currently returns `None` immediately. This is safe for startup use, but it also means a single unreadable required template suppresses detection rather than attempting degraded fallback behavior.
- Current tests are focused and synthetic, as required by the brief. Real-device screenshot coverage would still be useful in a later task, but was out of scope here.
