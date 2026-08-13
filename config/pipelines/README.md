# Pipeline 配置

Pipeline 使用固定的 `1080x1920` 竖屏坐标。每个节点可以配置模板/OCR 识别器、动作、成功后的 `next` 候选和失败后的 `error_next` 候选。

常用动作包括：

- `tap_self`：点击识别结果中心，适合按钮模板或 OCR 文字。
- `tap`：点击固定 `point`，或点击 `rect` 的中心。
- `back`、`swipe`、`wait`：调用现有设备层能力。
- `success`、`fail`：终止 Pipeline。

建议给每个会重复访问的节点显式设置 `max_times`，并为导航失败配置 `error_next`。ROI 使用 `[x, y, width, height]`，超出屏幕范围会被拒绝。

新增配置后运行：

```powershell
uv run python scripts/validate_pipelines.py
```

依赖声明和锁定结果由项目根目录的 pyproject.toml 与 uv.lock 管理。新增依赖时修改 pyproject.toml，然后运行 uv lock 和 uv sync --locked；需要兼容导出时再运行 uv export。

迁移期间保持任务配置中的 `implementation: python`。只有离线回放和 8787 端口的真实冒烟测试都通过后，才在用户明确选择的任务上改为 `implementation: pipeline`。
