# 防守令弹窗专用模板增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为防守令发布弹窗增加高阈值专用模板识别，并保留现有三类命令结构识别作为兜底，只通过公共安全空白点跳过弹窗。

**Architecture:** 在 `ActivityPopupDetector.detect()` 的业务阻断检查之后增加防守令模板优先分支。模板只覆盖标准化画面中稳定的“守城令发布”标题和上方金色面板，排除发布者、动态信息和“前往”按钮；模板未命中时继续走现有活动模板、命令结构和通用弹窗识别。公共清理函数不增加新的点击逻辑。

**Tech Stack:** Python 3.10+, OpenCV, NumPy, Pillow, `unittest`, Loguru, ADB screenshot replay, FastAPI/uvicorn smoke check。

## Global Constraints

- 不使用 OCR。
- 不降低现有三类命令通用结构识别阈值。
- 业务购买、重复登录、系统确认和无法安全检查的画面优先阻断空白点击。
- 防守令命中后只允许点击 `(30, 500)`，不得点击“前往”或弹窗内其他业务按钮。
- 每次点击后必须重新截图，连续处理受 `max_rounds` 限制。
- 不修改每日完成记录、购买次数、任务开关和 `config/runtime.yaml`。
- 运行时必须使用标准 `1080x1920` 游戏截图，不包含模拟器外框或浏览器区域。
- 项目不是 Git 仓库，本计划不创建 worktree、不初始化 Git、不提交代码。

## Files and Responsibilities

- Create: `assets/screenshots/startup_command_order_defense_replay.png` — 用户防守令截图去除外框并标准化到 `1080x1920` 的回放图。
- Create: `assets/templates/startup_command_order_defense.png` — 从回放图固定 ROI 裁剪出的高稳定模板。
- Modify: `src/session/activity_popup.py` — 增加防守令专用模板常量和优先识别分支，保持业务阻断优先级。
- Modify: `tests/session/test_activity_popup.py` — 增加专用模板命中、负样本和业务阻断优先级测试。
- Modify: `tests/session/test_startup_template_assets.py` — 增加防守令回放图、模板可读性和几何契约测试。
- Modify: `tests/session/test_highlight_dialog.py` — 增加专用模板命中后只点击安全空白点的公共清理回放测试。

---

### Task 1: Add the defense replay asset contract and failing tests

**Files:**
- Create: `assets/screenshots/startup_command_order_defense_replay.png`
- Create: `assets/templates/startup_command_order_defense.png`
- Modify: `tests/session/test_activity_popup.py`
- Modify: `tests/session/test_startup_template_assets.py`
- Modify: `tests/session/test_highlight_dialog.py`

**Interfaces:**
- Produces a normalized `1080x1920` BGR replay image and a readable defense template for later detector tests.
- Tests expect `ActivityPopupDetector.detect()` to return `source="command_order_defense_template"` before implementation exists.

- [ ] **Step 1: Add failing detector tests before implementation**

Add tests with these assertions:

```python
def test_defense_replay_uses_dedicated_template(self):
    screen = self.read_screen("startup_command_order_defense_replay.png")
    detector = ActivityPopupDetector(self.matcher)

    match = detector.detect(screen)

    self.assertIsNotNone(match)
    self.assertEqual(match.source, "command_order_defense_template")


def test_defense_template_is_blocked_by_business_popup(self):
    matcher = FakeMatcher(
        template_dir=config.root / "assets" / "templates",
        matches={"duplicate_login_message": 0.99,
                 "startup_command_order_defense": 0.99},
    )

    self.assertIsNone(ActivityPopupDetector(matcher).detect(build_clear_screen()))
```

Add an asset contract test that requires the replay to be `(1920, 1080, 3)` and the template to be readable with both dimensions greater than 20 pixels.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest \
  tests.session.test_activity_popup \
  tests.session.test_startup_template_assets -v
```

Expected: FAIL because the new replay/template assets and dedicated detector source do not yet exist. Do not change production code to make this first run pass.

- [ ] **Step 3: Create the normalized replay image**

Read `C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-d30369e1-2f51-4b8c-adaf-828b61f6fcce.png`, take the game viewport `(x=0, y=0, width=543, height=965)`, resize it to `(1080,1920)` with cubic interpolation, and write `assets/screenshots/startup_command_order_defense_replay.png` as PNG. The crop must not contain an emulator toolbar, browser window, or black outer area.

- [ ] **Step 4: Create the dedicated template crop**

From the normalized replay, crop `(x=480, y=1330, width=360, height=180)` and write `assets/templates/startup_command_order_defense.png`. This crop contains the stable “守城令发布” title and upper gold command panel, while excluding the publisher region and the right-side “前往” button.

- [ ] **Step 5: Re-run the focused tests and confirm they still fail only on production recognition**

Run the same focused unittest command. Expected: asset-readability tests pass, while the detector-source assertion remains FAIL because `ActivityPopupDetector` has not been modified.

### Task 2: Implement dedicated-template-first detection

**Files:**
- Modify: `src/session/activity_popup.py`

**Interfaces:**
- Add constants for template name, search ROI `(450, 1280, 450, 300)`, and dedicated threshold `0.88`.
- Add a private method `_detect_defense_template(screen: np.ndarray) -> ActivityPopupMatch | None`.
- `detect()` continues returning `ActivityPopupMatch | None` and retains blocker-first behavior.

- [ ] **Step 1: Implement the minimal template recognizer**

The method must:

1. Verify `matcher.template_dir` exists.
2. Call the existing matcher exactly as follows:

```python
hit = self._find(
    screen,
    "startup_command_order_defense",
    threshold=0.88,
    region=(450, 1280, 450, 300),
)
```

3. Return `None` when there is no hit.
4. Return this result on a hit:

```python
ActivityPopupMatch(
    source="command_order_defense_template",
    confidence=round(float(hit.score), 2),
    reason="matched startup_command_order_defense template",
)
```

Catch only the same safe template-loading/matching failures already handled by the detector and return `None`; do not use a coordinate fallback.

- [ ] **Step 2: Put the dedicated check after blockers and before generic activity detection**

In `detect()` preserve this order:

```python
if self.business_blocker_status(screen) is not False:
    return None

defense_match = self._detect_defense_template(screen)
if defense_match is not None:
    return defense_match

# existing startup_activity_*.png, command-order structure, and generic checks
```

Do not change `BLOCKER_TEMPLATES`, command-order structural thresholds, or `dismiss_activity_popups()`.

- [ ] **Step 3: Run the focused detector tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest \
  tests.session.test_activity_popup \
  tests.session.test_startup_template_assets -v
```

Expected: all focused detector and asset tests PASS.

### Task 3: Verify safe blank-click integration and false-positive boundaries

**Files:**
- Modify: `tests/session/test_highlight_dialog.py`
- Modify: `tests/session/test_activity_popup.py`

**Interfaces:**
- Reuse `dismiss_confirm_dialogs()` and `dismiss_activity_popups()` without adding a second click path.

- [ ] **Step 1: Add a failing integration replay test**

Use a `TaskContext` with a replay device whose states are:

```python
["startup_command_order_defense_replay", "main"]
```

Assert that `dismiss_confirm_dialogs(ctx, max_rounds=2)` returns one closed popup and the only device tap is `HIGHLIGHT_CLOSE_POINT`.

- [ ] **Step 2: Run the new integration test and verify it fails before the assertion is satisfied**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest \
  tests.session.test_highlight_dialog -v
```

Expected before the production change: the test cannot observe the dedicated source or safe tap. After Task 2, it must pass.

- [ ] **Step 3: Add negative and precedence assertions**

Verify all of the following:

```python
# Main city without overlay: no match and no tap.
# Duplicate-login or purchase blocker plus defense-like template: no match and no tap.
# Defense overlay with publisher area changed: dedicated template still matches.
# Existing build/attack structural fixtures: source remains command_order.
```

- [ ] **Step 4: Run the session regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/session -v
```

Expected: all session tests PASS.

### Task 4: Full verification and runtime handoff

**Files:**
- No additional source files.

- [ ] **Step 1: Run the complete unit test suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Compile all Python sources**

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
```

Expected: exit code 0.

- [ ] **Step 3: Run the 8787 HTTP smoke check**

```powershell
(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8787/').StatusCode
(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8787/api/status').Content
```

Expected: HTTP 200; service remains stopped unless the user explicitly starts挂机.

- [ ] **Step 4: Restart the 8787 service to load the new module**

Stop only the verified `main.py` process listening on port 8787, start the project service again, and verify `/api/status` returns HTTP 200. Do not start挂机 or click the emulator during this step.

- [ ] **Step 5: Report runtime verification boundary**

Tell the user to leave the defense popup visible and click挂机 once. Confirm from the API/logs that the new runtime process records a dedicated-template match and a safe blank tap; do not claim the live tap succeeded without that evidence.
