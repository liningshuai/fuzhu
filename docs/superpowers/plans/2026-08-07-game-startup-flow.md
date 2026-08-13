# 游戏启动与回主城状态收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在普通启动和重复登录恢复后，自动处理公告、进入游戏、永久卡奖励和高亮弹窗，稳定进入主城后才执行任务。

**Architecture:** 新增无业务副作用的 `GameStartupFlow`，通过模板识别把游戏状态收敛到主城。`BotEngine` 启动和 `GameSessionGuard` 恢复共同调用该流程；现有任务只在流程成功后继续，通用弹窗入口复用高亮关闭规则。

**Tech Stack:** Python 3.10+、unittest、OpenCV 模板匹配、现有 ADB 封装、loguru。

## Global Constraints

- 坐标基准固定为 `1080x1920`。
- 启动流程默认超时 60 秒，轮询间隔 1 秒。
- 每轮最多执行一个模板命中的动作，动作后重新截图。
- 未命中对应模板时禁止固定坐标点击。
- 高亮弹窗只在“点击任意区域关闭”提示模板命中后点击安全空白点。
- 不修改见证传奇、名士拜访、过关斩将的业务逻辑。
- 不改变 `config/runtime.yaml` 中现有任务开关和 Python 默认实现。
- 当前工作区不是 Git 仓库，不初始化 Git、不提交代码。

---

### Task 1: Define startup flow contract and failing tests

**Files:**
- Create: `src/session/startup.py`
- Create: `tests/session/test_startup.py`
- Modify: `src/session/__init__.py`

**Interfaces:**
- `GameStartupTimeout(RuntimeError)`：60 秒内未进入主城。
- `GameStartupFlow(device, matcher, timeout_seconds=60.0, poll_interval=1.0, sleep_fn=time.sleep, monotonic_fn=time.monotonic)`。
- `GameStartupFlow.wait_until_main_city() -> None`。
- `STARTUP_REGION = (0, 0, 1080, 1920)`：启动页模板统一搜索区域。

- [ ] **Step 1: Write the failing tests**

  使用 FakeDevice/FakeMatcher 模拟画面状态和点击记录，覆盖：已在主城立即返回；公告命中点击“朕已阅”；登录页命中点击“进入游戏”；永久卡命中点击“立即领取”；高亮提示命中点击安全空白；未知画面不点击；超时抛出 `GameStartupTimeout`。

- [ ] **Step 2: Run the tests and verify the failure**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup -v
  ```

  Expected: 因 `src.session.startup` 尚不存在或接口尚不存在而失败。

- [ ] **Step 3: Implement the minimal startup flow**

  在 `GameStartupFlow.wait_until_main_city()` 中按以下固定顺序处理每一轮截图：

  ```python
  STARTUP_REGION = (0, 0, 1080, 1920)
  screen = device.screenshot()
  if matcher.find(screen, "startup_announcement_claim", threshold=0.78, region=STARTUP_REGION):
      device.tap(match.x, match.y)
  elif matcher.find(screen, "startup_enter_game", threshold=0.78, region=STARTUP_REGION):
      device.tap(match.x, match.y)
  elif matcher.find(screen, "startup_permanent_claim", threshold=0.78, region=STARTUP_REGION):
      device.tap(match.x, match.y)
  elif matcher.find(screen, "startup_highlight_close_hint", threshold=0.78, region=STARTUP_REGION):
      device.tap(30, 500)
  elif matcher.find(screen, "nav_fief", threshold=0.78) is not None:
      return
  else:
      sleep_fn(poll_interval)
  ```

  实际实现中保留模板缺失的安全处理：缺失模板按未命中处理，并继续等待或最终超时；不把异常转成盲点。

- [ ] **Step 4: Run the focused tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup -v
  ```

  Expected: 所有启动状态测试通过。

### Task 2: Create and validate startup template assets

**Files:**
- Create: `assets/templates/startup_announcement_claim.png`
- Create: `assets/templates/startup_enter_game.png`
- Create: `assets/templates/startup_permanent_claim.png`
- Create: `assets/templates/startup_highlight_close_hint.png`
- Create: `assets/templates/startup_highlight_close_hint_reward.png`
- Create: `assets/screenshots/startup_announcement_replay.png`
- Create: `assets/screenshots/startup_enter_game_replay.png`
- Create: `assets/screenshots/startup_permanent_replay.png`
- Create: `assets/screenshots/startup_highlight_replay.png`
- Create: `assets/screenshots/startup_highlight_reward_replay.png`
- Create: `tests/session/test_startup_template_assets.py`
- Modify: `assets/templates/README.md`

**Interfaces:**
- 五个模板均可由 `TemplateMatcher._load()` 读取。
- 五个固定回放截图保持 1080×1920，测试不依赖会被 8787 “截图”按钮覆盖的 `panel_latest.png`。

- [ ] **Step 1: Write failing asset tests**

  测试五个模板存在、可读，并分别在对应固定回放截图中以至少 `0.90` 分数命中；在主城或非目标画面中不误命中高亮关闭提示。

- [ ] **Step 2: Run the asset tests and verify they fail**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
  ```

  Expected: 资产不存在导致失败。

- [ ] **Step 3: Crop the four templates from the user screenshots**

  去除截图中的雷电模拟器顶部栏和右侧工具栏，将游戏视口统一转换为 1080×1920；分别裁剪五个稳定文字/按钮区域，避免带入动态资源数字、红点和变化背景。奖励弹窗的高亮提示单独使用奖励场景模板，避免与普通高亮弹窗背景差异造成漏检。

- [ ] **Step 4: Add the asset documentation**

  在 README 中记录模板名称、对应画面、坐标基准、ROI 和“只有模板命中才点击”的安全规则。

- [ ] **Step 5: Run the asset tests and verify they pass**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
  ```

### Task 3: Integrate startup flow into session recovery and BotEngine

**Files:**
- Modify: `src/session/recovery.py`
- Modify: `src/bot/engine.py`
- Create: `tests/session/test_startup_integration.py`

**Interfaces:**
- `GameSessionGuard` 在 `stop_game()` / `start_game()` 后调用 `GameStartupFlow.wait_until_main_city()`。
- `BotEngine.start(ensure_game=True)` 在启动挂机线程前调用同一流程。
- 启动流程异常不执行任务；会话恢复仍保留 `GameSessionRestarted` 和 `GameSessionRecoveryError` 语义。

- [ ] **Step 1: Write failing integration tests**

  测试恢复器和引擎均调用启动流程；启动流程失败时引擎不创建任务线程；恢复成功后仍由当前任务重试逻辑接管。

- [ ] **Step 2: Run integration tests and verify they fail**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_integration -v
  ```

  Expected: 当前 `BotEngine.start()` 和 `GameSessionGuard` 只启动游戏，不处理公告/登录/奖励状态。

- [ ] **Step 3: Implement the integration**

  复用同一 `GameStartupFlow` 接口，不在 `BotEngine` 和 `GameSessionGuard` 中复制模板判断；保持现有设备刷新、会话限频和当前任务重试逻辑。

- [ ] **Step 4: Run focused integration tests**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_startup_integration tests.session.test_engine_recovery tests.session.test_recovery_replay -v
  ```

### Task 4: Add generalized high-light popup cleanup

**Files:**
- Modify: `src/tasks/navigation.py`
- Create: `tests/session/test_highlight_dialog.py`

**Interfaces:**
- 增加一个只在高亮关闭提示模板命中时点击空白的辅助函数。
- `dismiss_confirm_dialogs()` 保持购买次数弹窗等现有特殊分支不变。

- [ ] **Step 1: Write failing tests**

  覆盖高亮提示命中时点击安全空白、未命中时零点击、点击后继续原有确认弹窗处理。

- [ ] **Step 2: Run the tests and verify failure**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog -v
  ```

- [ ] **Step 3: Implement the narrow cleanup branch**

  将高亮提示检测放在通用确认弹窗处理之前或之后的明确位置，不能覆盖购买次数弹窗分支；检测失败只返回未处理，不抛出无意义的点击。

- [ ] **Step 4: Run navigation and focused tests**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.session.test_highlight_dialog tests.pipeline.test_replay -v
  ```

### Task 5: Full offline verification and 8787 smoke test

**Files:**
- Create: `tests/session/test_startup_replay.py`
- Modify: `docs/superpowers/specs/2026-08-07-game-startup-flow-design.md` only if implementation findings require a documented correction.

- [ ] **Step 1: Add the complete offline sequence test**

  用 FakeDevice 回放：公告 → 朕已阅 → 登录页 → 进入游戏 → 永久卡领取 → 高亮弹窗空白关闭 → 主城；断言点击顺序和最终停止条件。

- [ ] **Step 2: Run the full test suite and compile check**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  .\.venv\Scripts\python.exe -m compileall -q src tests
  ```

- [ ] **Step 3: Restart the 8787 service**

  确认旧服务已停止后，在项目目录启动 `main.py`，刷新 8787 页面；不修改用户任务开关。

- [ ] **Step 4: Run the live startup smoke test**

  用户保持雷电模拟器在主页，由 8787 执行“启动游戏/挂机”路径；验证公告、进入游戏、永久卡、高亮弹窗和主城识别。若出现真实重复登录弹窗，验证恢复流程也能进入主城。

- [ ] **Step 5: Restore and report final state**

  保持用户原有 `config/runtime.yaml` 任务开关和实现方式，停止挂机线程，确认 8787 服务仍可访问，并报告真实测试覆盖范围和未能触发的外部状态。
