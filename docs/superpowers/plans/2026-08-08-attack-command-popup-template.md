# 进攻令弹窗专用模板 Implementation Plan

> **For agentic workers:** Execute the tasks in this plan in order. The project is not a Git repository, so verification is recorded by test output rather than commits.

**Goal:** Add a high-confidence dedicated template for the “攻城令发布” popup while preserving the existing safe blank-tap cleanup path.

**Architecture:** Normalize the supplied emulator screenshot to the existing `1080x1920` replay format, crop the same stable `360x180` banner region used by the defense template, and register the attack template ahead of the shared structural fallback. The popup cleanup path remains unchanged and can only tap `(30, 500)` after a positive detector result.

**Tech Stack:** Python 3.10+, OpenCV, NumPy, `unittest`, existing `TemplateMatcher` and `ActivityPopupDetector`.

## Global Constraints

- Stability is prioritized over recognition coverage.
- Do not use OCR or lower the shared command-order structural thresholds.
- Do not click the popup’s “前往” button.
- Every popup-cleanup loop remains bounded by its existing `max_rounds` limit.
- Existing business-blocker precedence and construction/defense command behavior must remain unchanged.
- This workspace is not a Git repository; do not initialize Git, create a worktree, or commit changes.

---

### Task 1: Add failing attack-template replay tests

**Files:**
- Modify: `tests/session/test_startup_template_assets.py`
- Modify: `tests/session/test_activity_popup.py`
- Modify: `tests/session/test_highlight_dialog.py`

**Interfaces:**
- Consumes: `TemplateMatcher.find()`, `ActivityPopupDetector.detect()` and `dismiss_confirm_dialogs()`.
- Produces: executable regression expectations for the attack replay and safe blank tap.

- [x] **Step 1: Register the attack replay and template asset in startup asset tests.**

  Add `ATTACK_TEMPLATE = "startup_command_order_attack"`, `ATTACK_REPLAY = "startup_command_order_attack_replay.png"`, and assertions that the replay is `(1920, 1080, 3)`, the template exists, is readable, and is larger than `20x20`.

- [x] **Step 2: Add the detector expectation before production support exists.**

  Read the attack replay and assert:

  ```python
  match = ActivityPopupDetector(
      TemplateMatcher(template_dir=config.root / "assets" / "templates")
  ).detect(screen)
  self.assertIsNotNone(match)
  self.assertEqual(match.source, "command_order_attack_template")
  ```

- [x] **Step 3: Add the publisher-area and safe-click expectations.**

  Modify only the left publisher/character area in a replay and assert the dedicated template still matches. Add an image replay through `dismiss_confirm_dialogs()` and assert the only recorded tap is `HIGHLIGHT_CLOSE_POINT`.

- [x] **Step 4: Run the new focused tests and verify the expected RED state.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets tests.session.test_activity_popup tests.session.test_highlight_dialog -v
  ```

  Expected: failure because the attack replay and template assets are not present and the detector source is not registered yet. Do not change production code before confirming this failure.

### Task 2: Create the normalized attack replay and stable template

**Files:**
- Create: `assets/screenshots/startup_command_order_attack_replay.png`
- Create: `assets/templates/startup_command_order_attack.png`
- Create: `scripts/prepare_command_order_attack_asset.py`

**Interfaces:**
- Consumes: `C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-9950afe8-8a9e-4b26-864f-415042c6ef6f.png`.
- Produces: a `1080x1920` game-only replay and a `360x180` template aligned to the existing defense-template geometry.

- [x] **Step 1: Add a deterministic asset-preparation script.**

  Crop the supplied `592x1013` screenshot to the game viewport `(x=0, y=48, width=539, height=965)`, resize the crop to `(1080, 1920)` using `cv2.INTER_CUBIC`, save the replay, then crop `(x=480, y=1330, width=360, height=180)` and save the template. Use `np.fromfile`/`tofile` or the existing OpenCV path-safe helpers for Windows paths.

- [x] **Step 2: Run the preparation script and inspect asset geometry.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe scripts\prepare_command_order_attack_asset.py
  ```

  Verify the replay is `(1920, 1080, 3)` and the template is `(180, 360, 3)`.

- [x] **Step 3: Re-run Task 1 focused tests.**

  The asset tests must now load the files; the detector-source assertions may still fail until Task 3 is implemented.

### Task 3: Register the attack template without changing the cleanup behavior

**Files:**
- Modify: `src/session/activity_popup.py`
- Modify: `tests/session/test_activity_popup.py`

**Interfaces:**
- Consumes: the new template asset and existing `ActivityPopupDetector._find()`.
- Produces: `ActivityPopupMatch(source="command_order_attack_template", ...)` on dedicated-template hits, with the existing `command_order` fallback intact.

- [x] **Step 1: Add attack-template constants and a narrow detector helper.**

  Define:

  ```python
  ATTACK_COMMAND_TEMPLATE = "startup_command_order_attack"
  ATTACK_COMMAND_TEMPLATE_REGION = (450, 1280, 450, 300)
  ATTACK_COMMAND_TEMPLATE_THRESHOLD = 0.88
  ```

  Add `_detect_attack_template()` mirroring `_detect_defense_template()` and return the source/reason pair:

  ```text
  command_order_attack_template
  matched startup_command_order_attack template
  ```

- [x] **Step 2: Put the attack template in both detector entry points.**

  Run `_detect_attack_template()` after the defense-template check and before activity/structural fallback in `detect()`, and after the defense check in `detect_command_order()`.

- [x] **Step 3: Run the focused tests and confirm GREEN.**

  Run the three test modules from Task 1. Expected: all focused tests pass, including the assertion that no “前往” coordinate is tapped.

- [x] **Step 4: Run compile and full regression verification.**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m compileall -q src tests scripts
  .\.venv\Scripts\python.exe -m unittest discover -q
  ```

  Expected: exit code `0`, no failed tests.

### Task 4: 8787 service smoke verification

**Files:**
- No source changes.

- [x] **Step 1: Check the current 8787 process and health endpoint.**

  Use PowerShell to request `http://127.0.0.1:8787/` and `http://127.0.0.1:8787/api/status`, and verify HTTP `200` plus a valid JSON response.

- [x] **Step 2: Restart only if the service is not serving the updated code.**

  Do not launch the emulator or start a task. If a restart is needed, stop only the known 8787 process and start the project’s existing service command, then repeat the HTTP checks.
