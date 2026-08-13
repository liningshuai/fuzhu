# Task 3 Report — Integrate bounded activity-popup dismissal into GameStartupFlow

## Status

Task 3 completed on 2026-08-07.

- commit=none
- The project directory is not a Git repository.
- No Git repository, worktree, or commit was created.
- No real simulator operation was performed.

## Scope

Modified only the Task 3-allowed files:

- `src/session/startup.py`
- `tests/session/test_startup.py`
- `tests/session/test_startup_replay.py`
- `.superpowers/sdd/2026-08-07-activity-popup-dismissal/task-3-report.md`

Did not modify Task 4 business logic, `config/runtime.yaml`, or the existing
legendary-hero, scholar-visit, and guoguan business flows.

## Implementation

`GameStartupFlow` now accepts:

```python
activity_detector: ActivityPopupDetector | None = None
max_activity_dismissals: int = 8
```

When no detector is supplied, it constructs `ActivityPopupDetector(matcher)`.
The startup action order remains:

1. announcement;
2. enter game;
3. permanent claim;
4. known highlight/reward popup handling;
5. activity popup detection;
6. `nav_fief` main-city confirmation.

Activity handling is bounded and screenshot-safe:

- The dismissal counter is reset for each `wait_until_main_city()` call.
- If a match is found after the configured limit has already been reached,
  `GameStartupTimeout` is raised and its message contains the numeric limit.
- Each activity match clicks only `HIGHLIGHT_CLOSE_POINT == (30, 500)`.
- After each activity click, the loop immediately continues, forcing a new
  screenshot before any further detection or click.
- Activity logs include source, confidence score, and dismissal count.
- A negative dismissal limit is rejected with `ValueError`.

## TDD process

### RED

Added replay tests before changing production code for:

- `activity_1 -> activity_2 -> main`, requiring exactly two `(30, 500)` taps
  and screenshots for each state;
- three activity states with `max_activity_dismissals=2`, requiring two taps
  followed by `GameStartupTimeout` containing `2`;
- no detector match causing no blank tap;
- known highlight-popup handling taking priority over activity detection.

Focused command before implementation:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay -v
```

RED result: the new cases failed because `GameStartupFlow.__init__()` did not
yet accept `activity_detector`. Existing unrelated startup cases remained
passing after correcting the test helper to omit the optional keyword when it
was not used.

### GREEN

Implemented the minimum constructor and loop changes in `startup.py`, then
reran the focused suite successfully.

## Verification

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay -v
```

Result:

- Exit code: `0`
- `11` tests passed

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

Result:

- Exit code: `0`
- `7` tests passed

The final verification reran both commands after the last production-code
adjustment; both suites passed.

## Final result

Bounded multi-popup activity dismissal is integrated into
`GameStartupFlow` while preserving the existing startup action priority and
the one-action-per-fresh-screenshot rule.

commit=none

## Fix round 1 — review Minor

### Review finding addressed

Added a GameStartupFlow-level integration regression for a business popup.
The test does not inject an activity detector. It supplies the default flow
with a matcher whose `template_dir` is a real temporary directory and whose
`find()` returns a hit for the ActivityPopupDetector exclusion template
`dialog_confirm`.

The fake device remains in `business_popup` after each screenshot and returns
a NumPy screen, matching the detector's real input contract. The test verifies
that:

- `GameStartupTimeout` is raised with a short fake clock/timeout;
- the matcher actually received the `dialog_confirm` lookup, proving the
  default `ActivityPopupDetector(matcher)` path ran;
- no device tap occurred, including no `(30, 500)` activity blank tap;
- no startup-specific activity template or `nav_fief` match is provided.

Only `tests/session/test_startup_replay.py` and this report were modified in
this fix round. Production code was not changed.

### TDD evidence

The first run of the new test exposed a test-fixture error: the fake screenshot
was a string, so `ActivityPopupDetector` correctly returned early before
checking its exclusion list. The fixture was corrected to return a NumPy
screen while preserving the `business_popup` device state. The strengthened
test then passed and confirmed that `dialog_confirm` was queried.

### Verification

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay -v
```

- Exit code: `0`
- `12` tests passed

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

- Exit code: `0`
- `7` tests passed

commit=none
