# Safe Task Popup Dismissal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent task navigation from being blocked by the already-confirmed safe-to-skip task/guide popup while preserving purchase, login, and unknown-popup protections.

**Architecture:** Reuse `ActivityPopupDetector` as the only recognizer for generic safe-to-skip overlays. Add a context-aware cleanup helper that screenshots before every decision, taps only `(30, 500)` after a positive match, and verifies the popup state again before returning. Call this helper from the existing shared dialog-cleanup boundary used before each task and by navigation helpers.

**Tech Stack:** Python 3.10+, unittest, OpenCV, NumPy, existing `TaskContext`, `ActivityPopupDetector`, and loguru.

## Global Constraints

- Keep the safe blank point fixed at `(30, 500)`.
- Do not lower existing template thresholds or add blind fixed-coordinate clicks.
- Business purchase dialogs, duplicate-login dialogs, known confirm dialogs, and unknown screens must not trigger the safe blank click.
- Every safe-popup click must be followed by a fresh screenshot; consecutive handling must stop at a bounded limit.
- Do not modify `config/runtime.yaml`, enable tasks, or change unrelated business-task logic.
- The current directory is not a Git repository; do not initialize Git, create a worktree, or commit changes.

---

### Task 1: Add a context-aware safe-popup cleanup helper

**Files:**
- Modify: `src/tasks/navigation.py`
- Modify: `tests/session/test_highlight_dialog.py`

**Interfaces:**
- Add `dismiss_activity_popups(ctx: TaskContext, max_rounds: int = 3, detector: ActivityPopupDetector | None = None) -> int`.
- The helper returns the number of safe popups dismissed. It must stop without tapping when the detector does not match or when the limit is reached.

- [x] **Step 1: Write the failing tests**

  Add tests using a fake detector and replay device:

  ```python
  def test_safe_activity_popup_uses_blank_point_and_fresh_screenshot(self):
      ctx = ReplayContext(["activity_1", "activity_2", "main"])
      detector = ReplayActivityDetector({"activity_1", "activity_2"})

      closed = dismiss_activity_popups(ctx, max_rounds=3, detector=detector)

      self.assertEqual(closed, 2)
      self.assertEqual(ctx.device.blank_taps, [(30, 500), (30, 500)])
      self.assertEqual(ctx.device.screenshots, ["activity_1", "activity_2", "main"])

  def test_safe_activity_popup_never_taps_unknown_or_business_screen(self):
      ctx = ReplayContext(["unknown"])
      detector = ReplayActivityDetector(set())

      closed = dismiss_activity_popups(ctx, detector=detector)

      self.assertEqual(closed, 0)
      self.assertEqual(ctx.device.blank_taps, [])

  def test_safe_activity_popup_stops_at_limit(self):
      ctx = ReplayContext(["activity_1", "activity_2", "activity_3"])
      detector = ReplayActivityDetector({"activity_1", "activity_2", "activity_3"})

      closed = dismiss_activity_popups(ctx, max_rounds=2, detector=detector)

      self.assertEqual(closed, 2)
      self.assertEqual(ctx.device.blank_taps, [(30, 500), (30, 500)])
  ```

- [x] **Step 2: Run the focused tests and verify they fail**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog -v
  ```

  Expected: the new import or helper call fails because `dismiss_activity_popups` does not yet exist.

- [x] **Step 3: Implement the minimal helper**

  In `src/tasks/navigation.py`, construct the existing detector lazily, screenshot through `ctx.screenshot()`, return immediately on no match, and tap only `HIGHLIGHT_CLOSE_POINT`. After each tap, sleep using the existing short UI delay. Do not call `tap_blank()` for non-matches.

- [x] **Step 4: Run the focused tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog tests.session.test_activity_popup -v
  ```

### Task 2: Integrate safe-popup cleanup into the shared task boundary

**Files:**
- Modify: `src/tasks/navigation.py`
- Modify: `src/bot/engine.py` only if a shared-boundary test proves the existing call path cannot reach the helper.
- Modify: `tests/session/test_highlight_dialog.py`
- Modify: `tests/session/test_engine_recovery.py` only if required for the integration seam.

**Interfaces:**
- `dismiss_confirm_dialogs()` must process known highlight dialogs first, then safe activity/guide popups, then known confirm dialogs.
- Existing purchase-dialog early exit and duplicate-login handling remain unchanged.

- [x] **Step 1: Add the failing integration regression test**

  Add a test that gives `dismiss_confirm_dialogs()` a real `panel_latest.png` replay followed by a clear main-city screen. Assert that the only action during the popup state is `(30, 500)` and that no `btn_more` or purchase confirmation action is attempted.

- [x] **Step 2: Run the regression test and verify it fails**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog -v
  ```

  Expected: the popup remains unhandled and the blank-tap assertion fails.

- [x] **Step 3: Integrate the helper at the existing cleanup boundary**

  Call `dismiss_activity_popups()` from `dismiss_confirm_dialogs()` after the specific highlight check and before generic confirm matching. Preserve the purchase-dialog guard before this call so a “confirm purchase” screen cannot be dismissed by the safe blank point.

- [x] **Step 4: Run focused navigation and task tests**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog tests.session.test_startup tests.session.test_startup_replay tests.session.test_engine_recovery -v
  ```

### Task 3: Verify full regression and service synchronization

**Files:**
- No production files unless a focused test exposes a regression.

- [x] **Step 1: Run the complete offline test suite**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  ```

- [x] **Step 2: Run compilation verification**

  ```powershell
  .\.venv\Scripts\python.exe -m compileall -q src tests
  ```

- [x] **Step 3: Restart 8787 using the current code**

  Stop only the project’s existing 8787 process, start `main.py` with `.venv\Scripts\python.exe`, and do not enable or run tasks automatically.

- [x] **Step 4: Verify the local endpoint and stopped state**

  Confirm `http://127.0.0.1:8787/` responds successfully and the engine remains stopped. Report any live-device validation that was not possible separately from offline test evidence.

## Self-review checklist

- The current `panel_latest.png` regression is covered.
- Known purchase and login blockers remain excluded before generic activity detection.
- Every safe blank tap is followed by a screenshot.
- The helper has a bounded maximum and does not turn unknown screens into clicks.
- Existing startup and full-suite tests remain in the verification set.

## Verification record

- Focused regression suite: 44/44 passed.
- Full offline suite: 87/87 passed.
- Compilation: `compileall -q src tests` exited with code 0.
- 8787 endpoint: HTTP 200; engine `running=false`; device online and game foreground.
- Generic unknown-popup false-positive risk remains a monitored design trade-off because future activity pages must be supported without a fixed whitelist.
