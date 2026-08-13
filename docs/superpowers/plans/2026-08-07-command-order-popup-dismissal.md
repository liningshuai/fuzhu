# 三类命令弹窗安全跳过 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让建设令、进攻令、防守令弹窗被稳定识别并安全点击空白跳过，同时保持购买、重复登录和未知画面不误触。

**Architecture:** 在现有 `ActivityPopupDetector` 中增加命令弹窗结构签名，复用主城锚点、变暗检测和公共安全弹窗清理循环。检测器只返回正向识别结果，不执行点击；启动流程和任务前清理继续由现有调用方点击 `(30, 500)` 并限制连续次数。

**Tech Stack:** Python 3.10+, unittest, OpenCV, NumPy, existing `TemplateMatcher`, `ActivityPopupDetector`, `TaskContext`, and loguru.

## Global Constraints

- 稳定性优先，不能对未知画面执行空白点击。
- 安全空白点固定为 `(30, 500)`。
- 业务阻断弹窗优先于命令弹窗和活动弹窗。
- 不使用 OCR，不读取发布者或命令内容。
- 不修改 `config/runtime.yaml`，不自动启动挂机。
- 工作目录不是 Git 仓库，不创建 worktree、不初始化 Git、不提交代码。

---

### Task 1: Add failing detector tests

**Files:**
- Modify: `tests/session/test_activity_popup.py`
- Modify: `tests/session/test_highlight_dialog.py`

**Interfaces:**
- Consumes: `ActivityPopupDetector.detect(screen)` and existing `dismiss_activity_popups(ctx, ...)`.
- Produces: executable regression coverage for a command-order screen, blocker precedence, and bounded blank taps.

- [x] **Step 1: Write the failing tests**

Add a synthetic command screen using the existing real `nav_fief` template and a lower gold/orange banner. Assert the detector returns `source == "command_order"` and `reason == "main-city-underlay+dim-overlay+command-banner"`. Add negative tests for a clear main city and a dim screen without a command banner. Add a blocker test proving `duplicate_login_message` or `legend_buy_confirm_area` prevents command detection.

Add a replay test with `command_build`, `command_attack`, `main` states and a detector whose positive result is a `command_order` match. Assert the two taps are exactly `HIGHLIGHT_CLOSE_POINT` and screenshots are refreshed between taps.

```python
def test_detects_command_order_banner_under_main_city(self):
    from src.session.activity_popup import ActivityPopupDetector

    matcher = FakeMatcher(template_dir=Path("."), matches={"nav_fief": 0.95})
    detector = ActivityPopupDetector(matcher)

    match = detector.detect(build_command_order_screen())

    self.assertIsNotNone(match)
    self.assertEqual(match.source, "command_order")
    self.assertEqual(match.reason, "main-city-underlay+dim-overlay+command-banner")
```

- [x] **Step 2: Run the focused tests and verify they fail for the missing feature**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup tests.session.test_highlight_dialog -v
```

Expected: the new detector assertion fails because the current detector returns `None` or the existing generic activity reason; no production implementation has been changed yet.

### Task 2: Implement the command-order structure signature

**Files:**
- Modify: `src/session/activity_popup.py`

**Interfaces:**
- Consumes: `np.ndarray` screenshots and `TemplateMatcher.find()`.
- Produces: `ActivityPopupMatch(source="command_order", confidence=..., reason=...)` or `None`.

- [x] **Step 1: Add constants for the command-region signature**

Define a command region `(0, 1050, 1080, 550)` and conservative thresholds for orange/gold pixels, largest connected banner area, and horizontal coverage. Keep them module-level so tests can exercise the same production thresholds without duplicating magic numbers.

- [x] **Step 2: Add `_detect_command_order()`**

Require a valid `nav_fief` match at `main_city_threshold`, reuse `_measure_dimming()`, then convert the command region to HSV. Count pixels in a gold/orange mask, find external contours, and require the largest candidate to be wide and sufficiently large. Combine command-banner, dimming, and nav confidence. Return `None` for any invalid ROI or missing evidence.

- [x] **Step 3: Insert the new detector before generic central-panel detection**

After business blockers and dedicated activity templates, call `_detect_command_order()`. Return its positive match before `_detect_generic()` so logs identify the specific safe-popup family. Do not change the existing generic thresholds.

- [x] **Step 4: Run the focused tests and verify they pass**

Run the same focused unittest command from Task 1. Expected: all new command-order tests and all existing focused tests pass.

### Task 3: Verify public cleanup and startup integration

**Files:**
- Modify: `tests/session/test_startup_replay.py` only if a startup-specific command replay assertion is needed.

**Interfaces:**
- Consumes: existing `GameStartupFlow` and `dismiss_confirm_dialogs()` detector boundaries.
- Produces: proof that command popups are dismissed with the existing safe point and do not bypass business blockers.

- [x] **Step 1: Run session regression tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay tests.session.test_highlight_dialog tests.session.test_activity_popup tests.session.test_engine_recovery -v
```

Expected: all session tests pass and no purchase/re-login test records a blank tap.

- [x] **Step 2: Run full tests and compile check**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
```

Expected: unittest exits with code 0 and compileall emits no error.

- [x] **Step 3: Confirm the web service without changing runtime state**

```powershell
$response = Invoke-WebRequest http://127.0.0.1:8787/ -UseBasicParsing
$response.StatusCode
```

Expected: `200`. If the service is not running, restart only the existing web process, leave挂机停止, and verify `200` again.

### Task 4: Review the implementation against the specification

**Files:**
- Read: `docs/superpowers/specs/2026-08-07-command-order-popup-dismissal-design.md`
- Read: `docs/superpowers/plans/2026-08-07-command-order-popup-dismissal.md`
- Read: `src/session/activity_popup.py`
- Read: `src/tasks/navigation.py`

- [x] **Step 1: Check spec coverage**

Confirm that the implementation covers all three command types through the shared structure signature, safe point `(30, 500)`, fresh screenshots, bounded rounds, business-blocker precedence, and no task/config changes.

- [x] **Step 2: Check for accidental scope changes**

Confirm with `git`-independent file listing and targeted diff inspection that only the intended docs, tests, and detector source changed; do not initialize Git or modify runtime configuration.
