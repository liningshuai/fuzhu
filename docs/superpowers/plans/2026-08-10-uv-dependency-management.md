# uv 依赖管理迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目依赖和 `.venv` 统一迁移到 `uv`，生成可复现锁文件，并验证 RapidOCR 与现有测试环境可用。

**Architecture:** `pyproject.toml` 是依赖声明唯一来源，`uv.lock` 是解析结果，`requirements.txt` 是由 `uv export` 生成的兼容产物。业务代码不变，README 使用 `uv run` 执行命令。

**Tech Stack:** Python 3.12、uv 0.9+、PEP 621 `pyproject.toml`、SQLite/OpenCV/FastAPI 现有依赖、unittest。

## Global Constraints

- 虚拟环境固定使用项目根目录 `.venv`。
- Python 支持范围为 `>=3.10,<3.13`，当前验证 Python 3.12。
- `pyproject.toml` 是唯一手工维护的依赖清单。
- `requirements.txt` 只能由 `uv export` 生成，不手工增加依赖。
- 不修改业务逻辑，不启动挂机，不强制重启现有 8787 服务。
- 如果网络/审批阻止依赖安装，停止并报告具体阻塞，不使用未声明的替代包。

---

### Task 1: 建立 uv 项目元数据和锁文件

**Files:**
- Create: `pyproject.toml`
- Generate: `uv.lock`
- Regenerate: `requirements.txt`

**Interfaces:**
- `uv sync --locked` 必须使用项目 `.venv`。
- `uv export --format requirements-txt` 必须能生成兼容导出文件。

- [ ] **Step 1: 先确认现有依赖清单和 uv 版本**

记录 `requirements.txt` 中的 13 个直接依赖和当前 `uv --version`；不要在这一步改动依赖版本。

- [ ] **Step 2: 创建 `pyproject.toml`**

将现有直接依赖迁移到 `[project.dependencies]`，使用如下项目约束：

```toml
[project]
name = "binglin-tianxia-helper"
version = "0.1.0"
requires-python = ">=3.10,<3.13"

[tool.uv]
package = false
```

依赖名称和版本下限必须与原 `requirements.txt` 一致。

- [ ] **Step 3: 生成锁文件和兼容导出**

运行：

```powershell
uv lock
uv export --format requirements-txt --no-hashes --output-file requirements.txt
```

如果当前 uv 的参数名不同，以 `uv export --help` 显示的等价参数执行，并确认导出的文件仍包含 `rapidocr-onnxruntime`。

- [ ] **Step 4: 验证元数据和锁文件一致**

运行：

```powershell
uv lock --check
uv export --format requirements-txt --no-hashes --dry-run
```

确认两个命令退出码为 0；若失败，先修复元数据或导出参数，再进入 Task 2。

### Task 2: 更新当前使用文档

**Files:**
- Modify: `README.md`
- Modify: `config/pipelines/README.md`

- [ ] **Step 1: 替换安装和运行命令**

README 的当前安装流程改为：

```powershell
uv venv --python 3.12
uv sync --locked
uv run python main.py --check
uv run python main.py
```

测试和单次任务示例统一改为 `uv run python ...`。

- [ ] **Step 2: 加入迁移说明**

说明 `requirements.txt` 是兼容导出文件，新增或升级依赖必须修改 `pyproject.toml` 后重新运行 `uv lock` 和 `uv export`。

- [ ] **Step 3: 检查当前文档残留命令**

运行 `rg` 检查 README 和当前操作说明中是否仍把 `pip install -r requirements.txt` 当作主流程；历史计划文档不在本任务修改范围内。

### Task 3: 同步当前虚拟环境

**Files:**
- Modify: project `.venv` contents only through uv.

- [ ] **Step 1: 使用锁文件同步 `.venv`**

运行：

```powershell
uv sync --locked
```

不要手动调用 `pip install`，也不要删除项目数据目录或现有服务日志。

- [ ] **Step 2: 验证关键依赖导入发现**

运行：

```powershell
uv run python -c "import importlib.util; assert importlib.util.find_spec('rapidocr_onnxruntime'); print('rapidocr_onnxruntime=available')"
```

确认 RapidOCR 已进入由 uv 管理的 `.venv`。

### Task 4: 回归验证并保留 8787 状态

**Files:**
- No source changes expected.

- [ ] **Step 1: 运行编译检查**

```powershell
uv run python -m compileall -q src tests scripts
```

- [ ] **Step 2: 运行全量测试**

```powershell
uv run python -m unittest discover -q
```

预期退出码为 0；若失败，区分环境迁移问题和原有业务测试问题后再处理。

- [ ] **Step 3: 验证 8787 健康状态**

确认 `GET /api/status` 和 `GET /api/warehouse/status` 可响应，且不自动启动挂机。现有服务不因本次迁移被强制停止；如需让已运行服务使用新环境，另行执行受控重启。

- [ ] **Step 4: 记录迁移结果**

 记录 `uv` 版本、Python 版本、锁文件生成结果、RapidOCR 可用性、测试数量和 8787 状态；若 task7 的实机扫描仍需继续，下一步只需要重新点击一次仓库扫描。

## 当前执行记录（2026-08-10）

- Task 1 已完成：pyproject.toml、uv.lock 已生成，requirements.txt 已由 uv 导出，uv lock --check 通过。
- Task 2 已完成：README、Pipeline 说明、入口脚本和模板脚本已改用 uv run。
- Task 3 未完成：uv sync --locked 需要下载 rapidocr-onnxruntime 等 wheel；当前执行环境的网络审批被拒绝，离线缓存中没有 RapidOCR wheel，因此没有声称 .venv 已同步。
- Task 4 已完成当前可执行部分：uv run --no-sync 下编译通过、全量 164 项测试通过；8787 返回正常，running=false，模拟器仍在线且在主城。
