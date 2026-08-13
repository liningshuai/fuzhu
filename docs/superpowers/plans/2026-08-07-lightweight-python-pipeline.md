# Lightweight Python Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 Python 任务默认行为的前提下，实现可配置的轻量 Pipeline 执行器，并先用“自动领邮件”完成截图回放和真实 8787 测试。

**Architecture:** Pipeline 作为 `BaseTask` 的一种实现方式接入现有 `BotEngine`。Loader 负责解析和校验 YAML，Recognizer 负责 template/OCR，ActionExecutor 负责设备动作，Runner 负责节点流转、重试、兜底和执行轨迹；复杂任务继续保留 Python 实现。

**Tech Stack:** Python 3.10+、PyYAML、OpenCV、NumPy、Pillow、Loguru、ADB；OCR 使用可懒加载的 `rapidocr_onnxruntime` Provider。

## Global Constraints

- 第一阶段必须支持 `template`、`ocr`、`roi`、`threshold`、`action`、`next`、`error_next`、`max_times`、`delay`。
- 坐标设计基准固定为 `1080x1920`，设备输入继续通过现有 `AdbDevice` 执行。
- `implementation: python` 时现有任务行为不能改变；Pipeline 只通过显式配置启用。
- OCR Provider 缺失时返回 `NOT_READY`，禁止退化为无条件点击。
- Pipeline 必须有节点访问上限和全局步骤上限，不能无限循环。
- 第一阶段不迁移到 C++，不复制 MaaAssistantArknights 的代码、模板或资源。
- 截图、OCR 和日志均在本机处理，不上传账号或游戏画面。
- 先迁移“自动领邮件”，再评估“名士拜访”；见证传奇和过关斩将继续使用原 Python 任务。
- 当前工作区不是 Git 仓库，实施过程中不执行 `git commit`，不擅自初始化仓库。

---

### Task 1: 建立 Pipeline 数据模型与配置校验

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/models.py`
- Create: `src/pipeline/loader.py`
- Create: `tests/__init__.py`
- Create: `tests/pipeline/__init__.py`
- Create: `tests/pipeline/test_loader.py`
- Create: `tests/pipeline/fixtures/valid.yaml`
- Create: `tests/pipeline/fixtures/unknown_next.yaml`
- Create: `tests/pipeline/fixtures/invalid_vision.yaml`
- Create: `tests/pipeline/fixtures/unbounded_wait.yaml`

**Interfaces:**
- Produces `RecognizerSpec`, `ActionSpec`, `PipelineNode`, `PipelineDefinition`。
- Produces `load_pipeline(path: Path) -> PipelineDefinition`。
- Produces `validate_pipeline(definition: PipelineDefinition) -> None`，失败时抛出 `PipelineConfigError`。
- Later tasks consume these models and loader functions，不直接解析 YAML。

- [ ] **Step 1: Write failing schema tests**

```python
from pathlib import Path
import unittest

from src.pipeline.loader import PipelineConfigError, load_pipeline


class PipelineLoaderTests(unittest.TestCase):
    def test_loads_valid_pipeline(self):
        path = Path("tests/pipeline/fixtures/valid.yaml")
        definition = load_pipeline(path)
        self.assertEqual(definition.id, "demo")
        self.assertEqual(definition.start, "main")
        self.assertEqual(definition.nodes["main"].recognize.template, "nav_fief")

    def test_rejects_unknown_next_node(self):
        path = Path("tests/pipeline/fixtures/unknown_next.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)

    def test_rejects_invalid_roi_and_threshold(self):
        path = Path("tests/pipeline/fixtures/invalid_vision.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)

    def test_requires_bounded_deterministic_nodes(self):
        path = Path("tests/pipeline/fixtures/unbounded_wait.yaml")
        with self.assertRaises(PipelineConfigError):
            load_pipeline(path)


if __name__ == "__main__":
    unittest.main()
```

Create the four fixture files under `tests/pipeline/fixtures/` with one valid graph, one missing node reference, one ROI/threshold violation, and one deterministic node with no `max_times`.

- [ ] **Step 2: Run the loader tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_loader -v
```

Expected: import failure because `src.pipeline.loader` and its models do not exist yet.

- [ ] **Step 3: Implement immutable models**

In `src/pipeline/models.py`, define:

```python
@dataclass(frozen=True)
class RecognizerSpec:
    type: Literal["template", "ocr"]
    template: str | None = None
    text: str | None = None
    roi: tuple[int, int, int, int] | None = None
    threshold: float = 0.82


@dataclass(frozen=True)
class ActionSpec:
    type: Literal["none", "tap_self", "tap", "back", "swipe", "wait", "success", "fail"]
    point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    from_point: tuple[int, int] | None = None
    to_point: tuple[int, int] | None = None
    duration_ms: int = 400
    seconds: float = 0.0


@dataclass(frozen=True)
class PipelineNode:
    id: str
    recognize: RecognizerSpec | None
    action: ActionSpec
    next: tuple[str, ...] = ()
    error_next: tuple[str, ...] = ()
    max_times: int = 1
    delay: float = 0.0


@dataclass(frozen=True)
class PipelineDefinition:
    id: str
    start: str
    coordinate_base: tuple[int, int]
    nodes: dict[str, PipelineNode]
```

Use `dataclasses`, `typing.Literal`, and no external validation framework. Normalize YAML lists to tuples and keep node IDs as dictionary keys.

- [ ] **Step 4: Implement loader and validation**

Define `PipelineConfigError(ValueError)` in `src/pipeline/loader.py`, then:

1. Read UTF-8 YAML with `yaml.safe_load`.
2. Require `id`, `start`, and `nodes`.
3. Validate `coordinate_base == (1080, 1920)` for the first version.
4. Validate `roi` as four integers with positive width/height and bounds inside the coordinate base.
5. Validate thresholds in `[0.0, 1.0]`.
6. Validate template recognizers have `template`, OCR recognizers have non-empty `text`.
7. Validate all `next` and `error_next` references.
8. Validate `max_times >= 1`, `delay >= 0`, swipe parameters, and deterministic nodes.
9. Require at least one terminal `success` or `fail` node reachable from `start` by graph traversal.
10. Reject unknown action or recognizer types rather than silently ignoring them.

Raise `PipelineConfigError` with the YAML path, node ID, and field name in the message.

- [ ] **Step 5: Run the loader tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_loader -v
```

Expected: all loader and validation tests pass.

---

### Task 2: Implement recognizers and actions

**Files:**
- Create: `src/pipeline/recognizers.py`
- Create: `src/pipeline/actions.py`
- Create: `tests/pipeline/test_recognizers_actions.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces `Recognition` with `kind`, `score`, `x`, `y`, `w`, `h`, and optional `text`。
- Produces `RecognitionProvider.recognize(ctx, spec, screen) -> Recognition | None`。
- Produces `OcrBackend.recognize(image) -> list[OcrText]`。
- Produces `ActionResult(ok, terminal_status, message)`。
- Produces `ActionExecutor.execute(ctx, spec, recognition) -> ActionResult`。
- `PipelineRunner` in Task 3 consumes these interfaces。

- [ ] **Step 1: Write failing recognition and action tests**

```python
class RecognitionActionTests(unittest.TestCase):
    def test_template_recognizer_converts_match_result(self):
        result = TemplateRecognizer().recognize(self.ctx, self.template_spec, self.screen)
        self.assertEqual(result.x, 200)
        self.assertEqual(result.score, 0.91)

    def test_tap_self_uses_recognition_center(self):
        result = ActionExecutor().execute(
            self.ctx,
            ActionSpec(type="tap_self"),
            Recognition(kind="template", score=0.91, x=200, y=300, w=40, h=20),
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.device.calls, [("tap", 200, 300, True)])
```

The test fixture's fake matcher must implement:

```python
def find(self, screen, name, threshold=None, region=None):
    return MatchResult(name=name, x=200, y=300, score=0.91, w=40, h=20)
```

Implement the test file with the standard-library `unittest` API, and add fake OCR backend tests for exact text matching and missing-provider behavior.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_recognizers_actions -v
```

Expected: import failure for recognizer/action modules.

- [ ] **Step 3: Implement template recognition**

`TemplateRecognizer` must call the existing `ctx.matcher.find(screen, template, threshold, region)` and convert `MatchResult` to `Recognition`. It must not perform a second screenshot and must propagate a missing-template error as a controlled `RecognitionError` for the Runner to report as `NOT_READY`.

- [ ] **Step 4: Implement the OCR provider boundary**

Define an `OcrBackend` protocol and a lazy `RapidOcrBackend`:

1. Import `rapidocr_onnxruntime` only when an OCR node is executed.
2. Convert the provider output to `OcrText(text, score, rect)`.
3. Normalize whitespace and compare the requested text as a substring.
4. Return the highest-scoring matching text in the ROI.
5. If the package or model is unavailable, raise `OcrProviderUnavailable` so the Runner returns `NOT_READY` and performs no click.

Add `rapidocr_onnxruntime` to `requirements.txt` without importing it at module import time.

- [ ] **Step 5: Implement actions**

`ActionExecutor` behavior:

- `none`: return successful non-terminal result.
- `tap_self`: require a `Recognition`; call `ctx.device.tap(x, y, jitter=True)`.
- `tap`: require `point` or use the center of `rect`; call `ctx.device.tap`.
- `back`: call `ctx.device.back()`.
- `swipe`: call `ctx.device.swipe` with the configured endpoints and duration.
- `wait`: sleep for `seconds` without sending input.
- `success`: return terminal success.
- `fail`: return terminal failure.

Catch device exceptions and return `ActionResult(ok=False, ...)`; do not swallow the exception message.

- [ ] **Step 6: Run all recognizer/action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_recognizers_actions -v
```

Expected: all template, fake OCR, action, and missing-provider tests pass without requiring a real device.

---

### Task 3: Implement the Pipeline runner

**Files:**
- Create: `src/pipeline/result.py`
- Create: `src/pipeline/runner.py`
- Create: `tests/pipeline/test_runner.py`

**Interfaces:**
- Produces `PipelineStatus` values `SUCCESS`, `FAILED`, `NOT_READY`, `STEP_LIMIT`。
- Produces `PipelineResult(status, message, trace)`。
- Produces `PipelineRunner(ctx, max_steps=100).run(definition) -> PipelineResult`。
- Consumes Task 1 models and Task 2 recognizer/action interfaces。

- [ ] **Step 1: Write failing Runner tests**

Cover these exact cases:

```python
class PipelineRunnerTests(unittest.TestCase):
    def test_success_path_records_trace(self):
        result = self.runner.run(self.valid_definition)
        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual([step.node_id for step in result.trace], ["main", "finish"])

    def test_primary_next_miss_uses_error_next(self):
        result = self.runner.run(self.definition_with_fallback)
        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual(result.trace[-1].node_id, "fallback_success")

    def test_node_max_times_prevents_loop(self):
        result = self.runner.run(self.looping_definition)
        self.assertIs(result.status, PipelineStatus.FAILED)
        self.assertIn("max_times", result.message)

    def test_global_step_limit_prevents_unbounded_graph(self):
        result = PipelineRunner(self.ctx, max_steps=3).run(self.looping_definition)
        self.assertIs(result.status, PipelineStatus.STEP_LIMIT)
```

Add a test that verifies one screenshot is reused while selecting among a node's candidate list.

- [ ] **Step 2: Run Runner tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_runner -v
```

Expected: import failure for `src.pipeline.runner` and `src.pipeline.result`.

- [ ] **Step 3: Implement result and trace models**

Define:

```python
@dataclass(frozen=True)
class PipelineTrace:
    node_id: str
    recognition_type: str | None
    score: float | None
    point: tuple[int, int] | None
    action_type: str
    elapsed_ms: int
    error: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    status: PipelineStatus
    message: str
    trace: tuple[PipelineTrace, ...]
```

- [ ] **Step 4: Implement candidate selection and transitions**

Implement `PipelineRunner.run` with these rules:

1. Start with candidate list `[definition.start]`.
2. For a candidate list, capture one screenshot and evaluate nodes in order.
3. A recognizer node is selected only when its recognizer returns a match.
4. A deterministic node without a recognizer may only be selected as the last candidate.
5. Increment the selected node's visit count before running its action; exceeding `max_times` routes to that node's `error_next`.
6. On recognition/provider/screenshot failure, return `NOT_READY` when the failure is environmental; otherwise evaluate `error_next`.
7. On action failure, evaluate the current node's `error_next`.
8. After a successful non-terminal action, sleep `delay` and evaluate `next` on a fresh screenshot.
9. `success` and `fail` actions terminate immediately.
10. Stop with `STEP_LIMIT` after `max_steps` selected nodes.

Every selected node appends a `PipelineTrace`, including failure information, before the next transition.

- [ ] **Step 5: Run Runner tests and verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_runner -v
```

Expected: all success, fallback, max-times, step-limit, and screenshot reuse tests pass.

---

### Task 4: Add BaseTask compatibility and pipeline selection

**Files:**
- Create: `src/tasks/pipeline_task.py`
- Modify: `src/tasks/registry.py:30-65`
- Modify: `config/default.yaml` under `tasks.auto_mail`
- Create: `tests/pipeline/test_pipeline_task.py`

**Interfaces:**
- Produces `PipelineTask(task_id: str, pipeline_id: str, enabled: bool)`.
- `PipelineTask.execute(ctx) -> TaskResult` maps Pipeline statuses to existing `TaskStatus` values.
- `create_task(task_id)` selects `PipelineTask` only when `implementation == "pipeline"`.
- Default configuration keeps `auto_mail.implementation == "python"`.

- [ ] **Step 1: Write failing adapter and registry tests**

```python
class PipelineTaskTests(unittest.TestCase):
    def test_python_implementation_still_creates_existing_task(self):
        task = create_task("auto_mail")
        self.assertEqual(task.__class__.__name__, "AutoMailTask")

    def test_pipeline_implementation_creates_pipeline_task(self):
        config.set_task_option("auto_mail", "implementation", "pipeline")
        try:
            task = create_task("auto_mail")
            self.assertIsInstance(task, PipelineTask)
            self.assertEqual(task.pipeline_id, "auto_mail")
        finally:
            config.set_task_option("auto_mail", "implementation", "python")

    def test_pipeline_status_maps_to_task_status(self):
        result = PipelineTask("auto_mail", "auto_mail", enabled=True).execute(self.ctx)
        self.assertIn(result.status, {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.NOT_READY})
```

Patch the Runner in the test so no real device or screenshot is needed.

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_pipeline_task -v
```

Expected: import failure for `src.tasks.pipeline_task` or the new registry branch.

- [ ] **Step 3: Implement the adapter**

`PipelineTask` loads `config/pipelines/<pipeline_id>.yaml`, calls `PipelineRunner(ctx).run(definition)`, includes the last trace error in the `TaskResult.message`, and maps:

- `PipelineStatus.SUCCESS` -> `TaskStatus.SUCCESS`
- `PipelineStatus.NOT_READY` -> `TaskStatus.NOT_READY`
- all other statuses -> `TaskStatus.FAILED`

Do not write daily completion fields in the generic adapter.

- [ ] **Step 4: Add registry selection without changing defaults**

At the start of `create_task`, inspect the task metadata. If `implementation == "pipeline"`, construct `PipelineTask`; otherwise use the existing `IMPLEMENTED` mapping. Keep `auto_mail` in `IMPLEMENTED` for the Python fallback.

In `config/default.yaml`, add:

```yaml
    implementation: python
    pipeline: auto_mail
```

Do not switch `runtime.yaml` to Pipeline automatically.

- [ ] **Step 5: Run adapter and regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_pipeline_task -v
.\.venv\Scripts\python.exe -m compileall -q src
```

Expected: adapter tests pass and all source files compile.

---

### Task 5: Add the first auto-mail Pipeline and validation command

**Files:**
- Create: `config/pipelines/auto_mail.yaml`
- Create: `config/pipelines/README.md`
- Create: `scripts/validate_pipelines.py`
- Create: `tests/pipeline/test_pipeline_files.py`

**Interfaces:**
- `config/pipelines/auto_mail.yaml` is loadable by `load_pipeline`.
- `scripts/validate_pipelines.py` exits `0` only when every `config/pipelines/*.yaml` is valid.
- No existing task is switched to Pipeline by this task.

- [ ] **Step 1: Write the fixture validation test**

```python
from pathlib import Path
import unittest

from src.pipeline.loader import load_pipeline


class PipelineFileTests(unittest.TestCase):
    def test_auto_mail_pipeline_is_valid(self):
        definition = load_pipeline(Path("config/pipelines/auto_mail.yaml"))
        self.assertEqual(definition.id, "auto_mail")
        self.assertEqual(definition.start, "main_city")
        self.assertIn("success", definition.nodes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the file test and verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_pipeline_files -v
```

Expected: file-not-found failure because `config/pipelines/auto_mail.yaml` does not exist yet.

- [ ] **Step 3: Write the auto-mail Pipeline**

Use the existing mail templates and navigation regions to define these nodes:

```text
main_city -> open_more -> more_open -> open_mail -> mail_open -> read_all -> close_mail -> success
```

Use `error_next` to retry the current navigation node or return to `main_city`. Use `max_times` on every node. Use `tap_self` for matched buttons and `tap`/`back` only where the existing navigation helper already uses a fixed, verified control point. Do not add unconditional clicks for a missing template.

The Pipeline may use template recognition for the first live version. OCR support is validated separately and remains available for future count/text nodes.

- [ ] **Step 4: Add validation CLI and Pipeline documentation**

`validate_pipelines.py` must:

1. Resolve the project root from the script location.
2. Iterate sorted `config/pipelines/*.yaml` files.
3. Print `PASS <path>` for valid files.
4. Print the exception and `FAIL <path>` for invalid files.
5. Exit `0` only if all files pass; otherwise exit `1`.

Document how to add a node, choose an ROI, run validation, and keep `implementation: python` during migration in `config/pipelines/README.md`.

- [ ] **Step 5: Run pipeline-file checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pipeline.test_pipeline_files -v
.\.venv\Scripts\python.exe scripts/validate_pipelines.py
```

Expected: the auto-mail file test passes and the validation command exits `0`.

---

### Task 6: Add screenshot replay tests and perform 8787 smoke testing

**Files:**
- Create: `tests/pipeline/test_replay.py`
- Modify: `src/web/static/app.js` only if the existing task card cannot display `implementation: pipeline`; otherwise leave it unchanged.
- Modify: `config/runtime.yaml` only temporarily during manual testing, then restore `implementation: python`.

**Interfaces:**
- Replay tests use fake device/matcher/OCR objects and never send ADB commands.
- The real smoke test uses the existing 8787 controls and logs.

- [ ] **Step 1: Add replay fixtures and tests**

Use `assets/screenshots/test_main.png` and other existing screenshots only where they represent the required state. For missing states, create exactly the minimal deterministic PNG fixtures under `tests/pipeline/fixtures/images/` and list each fixture in the test file. Test that the Runner selects the expected node and action sequence without a real device.

- [ ] **Step 2: Run the complete offline suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe scripts/validate_pipelines.py
```

Expected: all tests pass, source compilation succeeds, and all Pipeline files validate.

- [ ] **Step 3: Switch only auto-mail to Pipeline for a live test**

Temporarily set the runtime task metadata to:

```yaml
tasks:
  auto_mail:
    implementation: pipeline
```

Start the existing local service, open `http://127.0.0.1:8787/`, and run only the auto-mail task against the manually logged-in emulator. Confirm the log contains node-level trace information and a final success or controlled failure.

- [ ] **Step 4: Verify rollback and existing-task regression**

Restore `implementation: python`, restart or reload the service, and run the existing auto-mail path once. Confirm that the old task behavior is unchanged. Also confirm `mingshi`, `legend`, and `guoguan` still register and do not get routed through Pipeline.

- [ ] **Step 5: Leave the default implementation unchanged**

Keep `config/default.yaml` and `config/runtime.yaml` on `implementation: python` until the live Pipeline run passes on a user-selected test account. Do not claim the migration is complete until the offline suite and the 8787 smoke test both pass.

## Plan Self-Review

- Spec coverage: schema fields are covered by Tasks 1 and 5; recognizers/actions by Task 2; transitions and safeguards by Task 3; backward compatibility by Task 4; migration and 8787 validation by Tasks 5 and 6.
- Placeholder scan: the plan contains no unresolved implementation markers or undefined implementation step.
- Type consistency: `PipelineDefinition`, `PipelineNode`, `RecognizerSpec`, `ActionSpec`, `PipelineResult`, and `PipelineRunner.run()` are defined before downstream tasks consume them.
- Scope: the first implementation produces a working generic executor and one Pipeline without migrating complex business tasks.
