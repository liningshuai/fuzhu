# Game Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在游戏出现“重复登录账号，请重新登录游戏”时，全局停止当前任务、限频重启游戏、等待主城并重试当前任务。

**Architecture:** 新增 `GameSessionGuard` 作为设备和模板匹配器之上的会话保护层；`TaskContext.screenshot()` 作为所有任务共享的检测入口。`BaseTask` 把会话中断转换为结构化结果，`BotEngine` 只重试被中断的当前任务，恢复超限或失败时停止挂机。

**Tech Stack:** Python 3.10+、unittest、OpenCV 模板匹配、现有 ADB 封装、loguru。

## Global Constraints

- 坐标基准固定为 `1080x1920`。
- 10 分钟内最多自动重启 2 次。
- 重复登录检测使用专用模板和中央 ROI，不使用通用确定按钮或无条件坐标点击。
- 默认任务实现和 `config/runtime.yaml` 不切换到 Pipeline。
- 不改变见证传奇、名士拜访、过关斩将的业务逻辑。

---

### Task 1: Add session recovery models and tests

**Files:**
- Create: `src/session/__init__.py`
- Create: `src/session/recovery.py`
- Create: `tests/session/__init__.py`
- Create: `tests/session/test_recovery.py`

**Interfaces:**
- `GameSessionRestarted(RuntimeError)`：成功恢复后通知上层重试当前任务。
- `GameSessionRecoveryError(RuntimeError)`：重启超限或恢复失败。
- `GameSessionGuard(device, matcher, max_restarts=2, window_seconds=600, ...)`。
- `GameSessionGuard.check(screen) -> None`：未命中返回；命中则完成恢复并抛出异常。

- [ ] 写 FakeDevice/FakeMatcher，覆盖弹窗未命中、命中、停止/启动顺序和主城确认。
- [ ] 先运行 `.\.venv\Scripts\python.exe -m unittest tests.session.test_recovery -v`，确认新模块缺失或接口缺失导致失败。
- [ ] 实现单调时间限频、专用模板检测、重启和主城轮询。
- [ ] 重新运行该测试，确认 10 分钟内第三次恢复被拒绝。

### Task 2: Integrate guard into TaskContext and task result handling

**Files:**
- Modify: `src/tasks/base.py`
- Modify: `src/tasks/pipeline_task.py`
- Create: `tests/session/test_task_context.py`

**Interfaces:**
- `TaskContext(..., session_guard: GameSessionGuard | None = None)`。
- `TaskContext.screenshot()` 在保护器恢复时不返回旧截图。
- `TaskResult.data["session_recovered"]` 表示可以重试当前任务；`session_recovery_exhausted` 表示应停止挂机。

- [ ] 写测试证明检测到弹窗后抛出 `GameSessionRestarted`，且任务没有调用设备点击。
- [ ] 运行测试确认当前 `TaskContext` 不支持保护器。
- [ ] 修改 `TaskContext.screenshot()` 和 `BaseTask.run()`，专门处理恢复异常；PipelineTask 不吞掉这些异常。
- [ ] 运行 Task 2 测试与现有 Pipeline 测试。

### Task 3: Integrate current-task retry into BotEngine

**Files:**
- Modify: `src/bot/engine.py`
- Create: `tests/session/test_engine_recovery.py`

**Interfaces:**
- `BotEngine._run_task_with_recovery(task_id, task, ctx) -> TaskResult`。
- 会话恢复后重新创建 `TaskContext` 并重试同一 task；不跳过到下一个 task。
- 恢复超限或恢复失败时设置停止事件。

- [ ] 写 FakeTask，第一次返回 `session_recovered`，第二次返回成功；断言同一任务执行两次。
- [ ] 写测试证明 `session_recovery_exhausted` 会停止引擎，不继续执行后续任务。
- [ ] 运行测试确认当前引擎没有该重试行为。
- [ ] 实现局部重试和停止逻辑，保持原任务遍历顺序。
- [ ] 运行引擎测试和全量离线测试。

### Task 4: Add duplicate-login template assets and validation

**Files:**
- Create: `assets/templates/duplicate_login_message.png`
- Create: `assets/templates/duplicate_login_confirm.png`
- Modify: `assets/templates/README.md`
- Create: `tests/session/test_template_assets.py`

**Interfaces:**
- `GameSessionGuard` 默认使用上述两个模板。
- 模板缺失时检测器返回未命中，不触发重启。

- [ ] 从用户提供的真实弹窗截图裁剪稳定的文字区域和确认按钮区域，保持 1080x1920 内容坐标。
- [ ] 写测试确认模板文件存在且可以被 `TemplateMatcher._load()` 读取。
- [ ] 运行测试确认资产可读。
- [ ] 更新模板 README，记录中央 ROI 和阈值用途。

### Task 5: Offline and 8787 verification

**Files:**
- Modify: `config/default.yaml` only if recovery limits need configuration; keep runtime implementation values unchanged.
- Create: `tests/session/test_recovery_replay.py`

- [ ] 用 FakeDevice 回放弹窗出现、重启后主城恢复、当前任务重试的完整序列。
- [ ] 运行 `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`。
- [ ] 运行 `.\venv\Scripts\python.exe -m compileall -q src tests`。
- [ ] 启动 8787，临时只启用用户指定任务，验证重复登录弹窗触发重启和重试。
- [ ] 停止挂机并恢复 `implementation: python`、原任务开关和 8787 服务状态。
