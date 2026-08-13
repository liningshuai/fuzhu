# 轻量 Python Pipeline 设计

## 1. 背景与目标

当前项目的任务流程主要写在 Python 任务类中。现有实现已经能够完成邮件、过关斩将、见证传奇、名士拜访等功能，但识别、动作、重试、页面跳转和失败兜底经常混在同一个任务文件里，新增功能时容易复制大量流程代码。

本设计引入一个轻量、可回退的 Python Pipeline 执行器，借鉴 MaaAssistantArknights 的配置驱动流程思想，但不迁移其 C++ 工程，也不复制其代码或游戏资源。

第一阶段目标：

1. 支持 `template`、`ocr`、`roi`、`threshold`、`action`、`next`、`error_next`、`max_times`、`delay`。
2. 保留现有 `BaseTask`、`BotEngine`、ADB 设备控制和已验证的 Python 任务。
3. 先将“自动领邮件”迁移为第一条纯 Pipeline，用于验证执行器本身。
4. 再将“名士拜访”作为第二个迁移对象，验证随机商品位置和业务状态记录的兼容性。
5. Pipeline 失败时能够回到原 Python 实现或安全结束，不得影响现有任务。

## 2. 非目标

第一阶段不实现以下内容：

- 不迁移到 C++、CMake 或 MaaCore。
- 不重写现有所有任务。
- 不实现 MAA 的完整任务表达式、`baseTask` 继承体系或可视化编辑器。
- 不实现多设备调度、远程控制或服务端任务下发。
- 不把明日方舟的模板、资源或业务逻辑复制到本项目。
- 不让 Pipeline 直接承担任务特有的每日完成记录、购买次数策略等业务状态；这类状态仍由任务适配层负责。

## 3. 方案选择

### 方案 A：继续使用纯 Python 任务类

改动最小，适合复杂业务，但每个任务都需要自行处理识别、重试、跳转和错误分支，无法解决流程代码重复问题。

### 方案 B：所有任务全部配置化

结构最统一，但需要一次性迁移现有任务；复杂战斗、购买策略和每日状态很难用简单配置表达，风险较高。

### 方案 C：Python 任务与 Pipeline 并行（采用）

简单、稳定的流程使用 Pipeline；需要复杂计算或业务状态的流程继续使用 Python。Pipeline 通过 `BaseTask` 适配器接入，`BotEngine`、Web 面板和日志接口保持不变。

采用方案 C 的原因：它能立即验证通用执行器的价值，同时为迁移失败保留明确回退路径。

## 4. 总体架构

新增目录：

```text
src/pipeline/
├── models.py          # Pipeline、Node、Recognizer、Action 数据模型
├── loader.py          # YAML 加载、路径解析、配置校验
├── recognizers.py     # template / OCR 识别器适配
├── actions.py         # tap / back / swipe / wait 等动作
├── runner.py          # 节点状态机执行器
└── result.py          # 执行结果、步骤轨迹和错误信息

config/pipelines/
└── auto_mail.yaml     # 第一条 Pipeline

src/tasks/pipeline_task.py  # Pipeline 到 BaseTask 的适配器
scripts/validate_pipelines.py
tests/pipeline/
```

现有代码的接入关系：

```text
BotEngine
  -> BaseTask.run()
      -> PipelineTask.execute()
          -> PipelineLoader
          -> PipelineRunner
              -> TaskContext.screenshot()
              -> TemplateMatcher / OcrRecognizer
              -> TaskContext.device.tap/back/swipe
```

Pipeline 不直接创建 ADB 设备，也不绕过 `TaskContext`，从而继续复用现有的设备、日志和输入抖动逻辑。

## 5. 配置格式

Pipeline 使用 YAML，单个流程包含入口节点和节点表：

```yaml
id: auto_mail
coordinate_base: [1080, 1920]
start: main_city

nodes:
  main_city:
    recognize:
      type: template
      template: nav_fief
      roi: [0, 1650, 1080, 270]
      threshold: 0.78
    action:
      type: none
    next: [open_more]
    error_next: [retry_main_city]
    max_times: 3
    delay: 0.4

  open_more:
    recognize:
      type: template
      template: btn_more
      roi: [820, 1450, 260, 350]
      threshold: 0.70
    action:
      type: tap_self
    next: [open_mail]
    error_next: [main_city]
    max_times: 3
    delay: 1.0

  open_mail:
    recognize:
      type: ocr
      text: 邮件
      roi: [700, 500, 350, 500]
      threshold: 0.60
    action:
      type: tap_self
    next: [finish]
    error_next: [back_to_city]
    max_times: 3
    delay: 1.0

  back_to_city:
    action:
      type: back
    next: [main_city]
    max_times: 2
    delay: 0.8

  retry_main_city:
    action:
      type: wait
      seconds: 1.0
    next: [main_city]
    max_times: 2

  finish:
    action:
      type: success
```

字段规则：

- `id`：Pipeline 唯一标识。
- `coordinate_base`：坐标设计基准，第一阶段固定为 `1080x1920`，运行时由设备层换算。
- `start`：入口节点。
- `nodes`：节点定义表。
- `recognize.type`：第一阶段支持 `template` 和 `ocr`。
- `recognize.template`：模板名，交给现有 `TemplateMatcher` 加载。
- `recognize.text`：OCR 目标文字，第一阶段使用规范化后的包含匹配，不实现正则表达式。
- `roi`：`[x, y, width, height]`，超出屏幕范围时校验失败，不静默修正。
- `threshold`：模板分数或 OCR 置信度阈值，范围为 `0.0` 到 `1.0`。
- `action.type`：支持 `none`、`tap_self`、`tap`、`back`、`swipe`、`wait`、`success`、`fail`。`tap` 使用 `point` 或 `rect` 参数，`swipe` 使用 `from`、`to`、`duration_ms` 参数，`wait` 使用 `seconds` 参数。
- `next`：当前节点成功后的有序候选节点列表；第一阶段按列表顺序执行第一个可用节点。
- `error_next`：当前节点识别失败、动作失败或达到最大尝试次数后的有序兜底列表。
- `max_times`：节点最多访问次数，识别失败也计数，防止死循环。
- `delay`：动作完成后等待的秒数；第一阶段不拆分 before/after 两种延迟。

没有 `recognize` 的节点只能使用 `back`、`swipe`、`wait`、`success`、`fail` 等确定性动作，并且必须通过 `max_times` 或终止动作限制流程长度。

## 6. 执行器行为

执行器按以下规则工作：

1. Loader 读取 Pipeline，并校验入口、节点引用、模板路径、ROI、阈值、动作参数和终止节点。
2. Runner 从 `start` 开始，每次进入节点时增加该节点访问次数。
3. 有识别器的节点截取一张当前画面，并在该画面上完成识别；同一组候选节点不会为每个候选重复截图。
4. 识别成功后将 `MatchResult` 或 `OcrResult` 传给动作层。`tap_self` 点击识别框中心区域，继续使用设备层的随机抖动。
5. 动作完成后等待 `delay`，再截取下一张画面，并按 `next` 列表顺序选择第一个匹配节点。没有识别器的确定性节点只能作为候选列表的最后一项。
6. 识别失败、动作异常、截图异常或达到 `max_times` 时，按同样规则评估 `error_next`；没有可用兜底时返回失败。
7. 到达 `success` 或 `fail` 节点时终止。
8. 每一步记录节点名、识别类型、分数、ROI、命中坐标、动作、耗时和错误原因。

Runner 必须设置全局最大步骤数，默认值为 100；即使配置出现环路，也不能无限运行。

## 7. OCR 适配

当前项目没有 OCR 依赖，因此识别器采用接口隔离：

```python
class OcrRecognizer:
    def recognize(self, image, roi, text, threshold):
        ...
```

第一阶段使用本地 `rapidocr_onnxruntime` 作为默认实现，模型只在本机运行，不上传截图。Pipeline 没有 OCR 节点时不加载 OCR 模型；存在 OCR 节点但依赖或模型缺失时返回 `NOT_READY`，不得回退成无条件点击。

后续如需替换 PaddleOCR，只增加新的 Provider，不修改 Pipeline 配置格式和 Runner。

## 8. 现有任务接入与回退

新增 `PipelineTask` 继承 `BaseTask`。任务配置增加实现方式选择：

```yaml
tasks:
  auto_mail:
    enabled: true
    implementation: python
    pipeline: auto_mail
```

可选值为：

- `python`：执行现有任务类。
- `pipeline`：执行对应 Pipeline。

迁移步骤：

1. 先新增 Pipeline 文件和离线测试，不改变线上默认实现。
2. 通过命令行单次执行 Pipeline，确认截图回放结果。
3. 在 8787 面板中将 `auto_mail.implementation` 切换为 `pipeline`，进行真实账号冒烟测试。
4. 连续验证通过后再考虑默认切换。
5. 名士拜访迁移时，购买日期、已购买状态和随机商品选择继续保留在 Python 适配层；Pipeline 只负责页面导航和基础点击。

## 9. 测试与验收

### 单元测试

- YAML 正常加载和字段默认值。
- 未知节点、未知模板、非法 ROI、阈值越界能够被拒绝。
- `next`、`error_next`、`max_times` 和全局步骤上限能够终止环路。
- 模板识别结果能正确转换为点击坐标。
- OCR Provider 缺失时返回 `NOT_READY`，不执行危险动作。

### 截图回放测试

使用已保存截图和 FakeDevice/FakeRecognizer，不连接真实模拟器，验证：

- 自动领邮件的主城、更多、邮件、阅读、返回流程。
- 模板未命中时进入兜底分支。
- 弹窗遮挡时不会误点业务按钮。
- 成功、失败和超时日志包含完整步骤轨迹。

### 真实测试

在 8787 端口验证：

1. 原有 Python 任务保持可用。
2. Pipeline 关闭时不改变现有行为。
3. Pipeline 开启后能完成自动领邮件。
4. 失败时能停止或回到主城，不进入无限点击。
5. 名士拜访仍能购买一次铜钱碎片并写入每日完成状态。

## 10. 风险与回滚

- OCR 引擎安装复杂：OCR 通过 Provider 隔离，模板流程不依赖 OCR。
- 配置环路：节点访问计数和全局步骤上限双重限制。
- 误识别点击：必须配置 ROI 和阈值；识别失败不得使用默认坐标点击。
- 迁移影响现有功能：默认使用 `implementation: python`，Pipeline 只通过显式开关启用。
- 游戏更新导致模板失效：保留现有截图、识别分数和步骤日志，便于重新采样模板。

本设计不要求删除或重写现有任务。只有在 Pipeline 经过截图回放和真实账号测试后，才允许逐个切换实现方式。
