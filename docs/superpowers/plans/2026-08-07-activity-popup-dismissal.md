# 限时活动弹窗安全关闭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在启动进入主城期间，用专用活动模板和保守的结构化视觉检测，逐张关闭限时活动弹窗，同时不误点业务弹窗。

**Architecture:** 新增无点击副作用的 `ActivityPopupDetector`，先尝试自动发现的 `startup_activity_*.png` 模板，再用主城底图锚点、变暗遮罩和中央面板结构三个条件做泛化识别。`GameStartupFlow` 负责优先级、有限次数、空白点击和重新截图；业务弹窗排除继续留在检测器中，不修改现有任务逻辑。

**Tech Stack:** Python 3.10+、unittest、OpenCV、NumPy、Pillow、现有 `TemplateMatcher`、ADB 截图与 loguru。

## Global Constraints

- 坐标基准固定为 `1080x1920` 竖屏。
- 活动关闭只允许点击安全空白点 `(30, 500)`。
- 每次活动点击后必须重新截图；默认最多连续关闭 `8` 张活动弹窗。
- 泛化识别必须同时满足主城底图锚点、变暗遮罩和中央面板结构条件；低置信度时禁止点击。
- 购买确认、重复登录、系统确认、公告、永久卡及任务内购买/奖励弹窗必须优先排除。
- 活动泛化检测只集成到启动收敛流程，不加入通用导航的盲点分支。
- 不修改见证传奇、名士拜访、过关斩将等业务任务逻辑，也不修改 `config/runtime.yaml` 的任务开关。
- 当前目录不是 Git 仓库，不创建 worktree、不初始化 Git、不提交代码。

---

### Task 1: Implement and test the activity popup detector

**Files:**
- Create: `src/session/activity_popup.py`
- Create: `tests/session/test_activity_popup.py`
- Modify: `src/session/__init__.py`

**Interfaces:**
- `ActivityPopupMatch(source: str, confidence: float, reason: str)`：不可变识别结果。
- `ActivityPopupDetector(matcher, panel_region=(20, 400, 1040, 1250), main_city_threshold=0.90, dim_mean_max=92.0, dark_fraction_min=0.35, panel_score_min=0.55, confidence_min=0.70)`。
- `ActivityPopupDetector.detect(screen: Any) -> ActivityPopupMatch | None`：只识别，不点击。
- 专用模板名称通过 `matcher.template_dir.glob("startup_activity_*.png")` 自动发现；模板缺失或读取失败按未命中处理。
- 当测试替身没有 `template_dir`，或输入不是 `numpy.ndarray` 时，检测器返回空值，不抛出模板/图像类型异常。

- [ ] **Step 1: Write the failing detector tests**

  在 `tests/session/test_activity_popup.py` 中加入真实行为测试：

  ```python
  def make_activity_screen():
      screen = np.full((1920, 1080, 3), 45, dtype=np.uint8)
      screen[650:1320, 50:1030] = 175
      return screen

  def make_clear_main_city_screen():
      return np.full((1920, 1080, 3), 100, dtype=np.uint8)

  def test_synthetic_activity_panel_matches_generic_detector(self):
      screen = make_activity_screen()
      detector = ActivityPopupDetector(FakeMatcher())

      match = detector.detect(screen)

      self.assertIsNotNone(match)
      self.assertEqual(match.source, "generic")
      self.assertGreaterEqual(match.confidence, 0.70)

  def test_clear_main_city_replay_is_not_activity(self):
      screen = make_clear_main_city_screen()
      detector = ActivityPopupDetector(FakeMatcher())

      self.assertIsNone(detector.detect(screen))

  def test_missing_main_city_anchor_is_not_activity(self):
      detector = ActivityPopupDetector(MatcherWithoutMainCityAnchor())

      self.assertIsNone(detector.detect(make_activity_screen()))

  def test_known_business_popup_blocks_generic_activity_detection(self):
      detector = ActivityPopupDetector(BusinessPopupMatcher())

      self.assertIsNone(detector.detect(make_activity_screen()))
  ```

  `FakeMatcher` 必须对 `nav_fief` 返回低阈值命中；`MatcherWithoutMainCityAnchor` 对 `nav_fief` 返回空；`BusinessPopupMatcher` 对 `guoguan_buy_title` 或 `dialog_confirm` 返回命中。测试使用 NumPy 图像，不只断言 mock 调用次数。

- [ ] **Step 2: Run the detector tests and verify the expected failure**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v
  ```

  Expected: 因为 `src.session.activity_popup` 尚未存在而失败，或因检测器接口尚未实现而失败；不得出现测试本身导入错误以外的无关异常。

- [ ] **Step 3: Implement the minimal detector**

  `ActivityPopupDetector.detect()` 按以下顺序运行：

  ```python
  def detect(self, screen):
      if self._blocked_by_business_popup(screen):
          return None

      known = self._find_known_activity_template(screen)
      if known is not None:
          return ActivityPopupMatch("template", known.score, known.name)

      anchor = self._find_main_city_underlay(screen)
      if anchor is None:
          return None
      dim_mean, dark_fraction = self._measure_dimming(screen)
      panel_score = self._measure_central_panel(screen)
      if (
          dim_mean > self.dim_mean_max
          or dark_fraction < self.dark_fraction_min
          or panel_score < self.panel_score_min
      ):
          return None
      confidence = self._combine_scores(
          anchor.score,
          1.0 - dim_mean / 255.0,
          dark_fraction,
          panel_score,
      )
      if confidence < self.confidence_min:
          return None
      return ActivityPopupMatch("generic", confidence, "main-city-underlay+dim-overlay+central-panel")
  ```

  实现要求：

  - 使用 `TemplateMatcher.find()` 以 `main_city_threshold=0.90` 查找 `nav_fief`，但该命中只表示主城底图存在，不表示启动成功；
  - 在 `panel_region=(20,400,1040,1250)` 内用灰度均值和低亮度像素比例计算变暗分数；
  - 用 Canny 边缘和轮廓/局部对比计算中央面板分数，不能只依赖单一平均亮度；
  - 对 `duplicate_login_message`、`duplicate_login_confirm`、`guoguan_buy_title`、`guoguan_buy_confirm`、`legend_buy_title`、`dialog_nation_title`、`dialog_confirm`、`startup_announcement_claim`、`startup_enter_game`、`startup_permanent_claim` 任一命中时返回空；模板不存在必须安全跳过；
  - 所有分数归一化到 `0.0..1.0`，泛化命中要求固定的 `panel_score_min` 和组合置信度下限；
  - 检测器只返回结果，不执行 `tap`，也不修改设备状态。

- [ ] **Step 4: Run detector tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_activity_popup -v
  ```

  Expected: 所有检测器正例和负例通过，未发生点击。

---

### Task 2: Add activity replay assets and validate the template catalog

**Files:**
- Create: `assets/screenshots/startup_activity_replay.png`
- Create: `assets/templates/startup_activity_current_poster.png`
- Create or modify: `tests/session/test_startup_template_assets.py`
- Modify: `assets/templates/README.md`

**Interfaces:**
- 活动回放和模板统一为 `1080x1920`。
- 新增 `startup_activity_*.png` 文件会被 `ActivityPopupDetector` 自动发现，不需要修改 Python 分支。

- [ ] **Step 1: Add the failing asset assertions**

  在资产测试中增加：

  ```python
  def test_current_activity_replay_and_template_are_readable(self):
      screen = self.read_screen("startup_activity_replay.png")
      self.assertEqual(screen.shape[:2], (1920, 1080))
      template = self.matcher._load("startup_activity_current_poster")
      self.assertGreater(template.shape[0], 200)
      self.assertGreater(template.shape[1], 400)

  def test_current_activity_template_matches_replay(self):
      screen = self.read_screen("startup_activity_replay.png")
      match = self.matcher.find(screen, "startup_activity_current_poster", threshold=0.90)
      self.assertIsNotNone(match)
  ```

- [ ] **Step 2: Run the asset tests and verify they fail**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
  ```

  Expected: 新增回放或模板不存在，测试失败。

- [ ] **Step 3: Normalize the supplied screenshot and crop the stable activity panel**

  将用户提供的 `C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-ac5950d9-c369-46df-b686-8292b53c946b.png` 等比例转换到 `1080x1920`，保存为 `assets/screenshots/startup_activity_replay.png`。从活动面板主体裁剪稳定区域生成 `assets/templates/startup_activity_current_poster.png`，不得包含模拟器边框、动态资源数字或红点。

  使用现有 `scripts/capture_template.py` 或同等 Pillow/OpenCV 处理，并用 `TemplateMatcher` 检查模板中心不落在空白背景区域。

- [ ] **Step 4: Document the activity template convention**

  在 `assets/templates/README.md` 增加 `startup_activity_*.png` 说明：模板用于活动面板识别，点击始终使用 `(30,500)`，新增活动只需添加模板和回放，不修改检测分支。

- [ ] **Step 5: Run asset tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
  ```

---

### Task 3: Integrate bounded multi-popup dismissal into `GameStartupFlow`

**Files:**
- Modify: `src/session/startup.py`
- Modify: `tests/session/test_startup.py`
- Create or modify: `tests/session/test_startup_replay.py`

**Interfaces:**
- `GameStartupFlow(..., activity_detector: ActivityPopupDetector | None = None, max_activity_dismissals: int = 8)`。
- 当 `activity_detector` 未传入时，构造 `ActivityPopupDetector(matcher)`。
- `GameStartupTimeout` 继续作为启动失败异常；超出活动关闭上限时错误信息必须包含上限数值。

- [ ] **Step 1: Write failing startup integration tests**

  增加 FakeDevice/FakeActivityDetector 回放：

  ```python
  def test_two_activity_pages_are_closed_before_main_city(self):
      device = ReplayDevice(["activity_1", "activity_2", "main"])
      detector = FakeActivityDetector({"activity_1", "activity_2"})
      flow = GameStartupFlow(
          device,
          FakeMatcher(),
          activity_detector=detector,
          max_activity_dismissals=8,
          poll_interval=0,
      )

      flow.wait_until_main_city()

      self.assertEqual(device.blank_taps, [(30, 500), (30, 500)])
      self.assertEqual(device.state, "main")

  def test_activity_dismissal_stops_at_configured_limit(self):
      device = ReplayDevice(["activity_1", "activity_2", "activity_3"])
      detector = FakeActivityDetector({"activity_1", "activity_2", "activity_3"})

      with self.assertRaises(GameStartupTimeout) as ctx:
          GameStartupFlow(
              device,
              FakeMatcher(),
              activity_detector=detector,
              max_activity_dismissals=2,
              poll_interval=0,
              timeout_seconds=0.1,
          ).wait_until_main_city()

      self.assertIn("2", str(ctx.exception))
      self.assertEqual(len(device.blank_taps), 2)
  ```

  增加业务负例：活动检测器未命中时不点击；已知购买弹窗由专用分支处理，不进入泛化空白点击。

- [ ] **Step 2: Run startup integration tests and verify they fail**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay -v
  ```

  Expected: 当前 `GameStartupFlow` 没有 `activity_detector` 参数，或连续活动状态不会被处理，测试失败。

- [ ] **Step 3: Implement the minimal integration**

  在 `GameStartupFlow.__init__` 保存 detector、计数器和上限；每轮既有动作均未命中后，在 `nav_fief` 成功确认前执行：

  ```python
  activity = self.activity_detector.detect(screen)
  if activity is not None:
      if self._activity_dismissals >= self.max_activity_dismissals:
          raise GameStartupTimeout(
              f"活动弹窗连续关闭已达到上限 {self.max_activity_dismissals}"
          )
      self.device.tap(*HIGHLIGHT_CLOSE_POINT)
      self._activity_dismissals += 1
      logger.info(
          "启动流程关闭活动弹窗 source={} score={:.3f} count={}/{}",
          activity.source,
          activity.confidence,
          self._activity_dismissals,
          self.max_activity_dismissals,
      )
      continue

  if self._find(screen, "nav_fief") is not None:
      return
  ```

  已知业务模板优先级保持在活动检测之前；活动点击后 `continue` 强制重新截图；未命中活动检测时不点击任何坐标。

- [ ] **Step 4: Run focused startup tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup tests.session.test_startup_replay tests.session.test_startup_template_assets -v
  ```

---

### Task 4: Full regression, documentation, and 8787 synchronization

**Files:**
- Modify: `docs/superpowers/specs/2026-08-07-activity-popup-dismissal-design.md` only if implementation measurements require a documented threshold correction.
- Modify: `assets/templates/README.md` if final asset names or ROI differ from Task 2.

- [ ] **Step 1: Run the full offline test suite**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  ```

  Expected: 全部通过，且现有流水线、会话恢复、见证传奇、名士拜访相关测试不回归。

- [ ] **Step 2: Run compilation verification**

  ```powershell
  .\.venv\Scripts\python.exe -m compileall -q src tests
  ```

- [ ] **Step 3: Restart the 8787 service with the current `.venv`**

  精确停止当前项目 `main.py` 进程，使用项目 `.venv\Scripts\python.exe main.py` 重新启动；不修改 `config/runtime.yaml`，不启动任务线程。

- [ ] **Step 4: Run the live startup smoke test**

  在雷电模拟器中触发启动/挂机路径，验证：

  - 当前活动弹窗可以点击 `(30,500)` 关闭；
  - 连续活动页面逐张关闭；
  - 购买确认、重复登录等业务弹窗没有被泛化分支误点；
  - 最终确认 `nav_fief` 后才启动挂机线程。

- [ ] **Step 5: Leave the service reachable and report evidence**

  通过 `http://127.0.0.1:8787/` 返回 HTTP 200，调用停止接口确保挂机线程停止，并报告测试数量、服务状态、真实联调是否覆盖及任何未覆盖外部状态。
