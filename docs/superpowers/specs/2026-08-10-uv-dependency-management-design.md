# uv 依赖管理迁移设计

## 目标

将项目的 Python 虚拟环境和第三方依赖统一交给 `uv` 管理，降低新机器部署和后续依赖升级的成本，同时保持旧环境可以通过 `requirements.txt` 继续迁移。

## 设计决策

### 1. 依赖单一来源

新增 `pyproject.toml`，项目依赖从现有 `requirements.txt` 迁移到 `[project.dependencies]`。`uv.lock` 保存当前解析结果并作为可复现安装依据。

`requirements.txt` 保留为兼容导出文件，由 `uv export` 生成，不再手工维护。这样既避免旧用户无法迁移，也避免两个依赖文件长期出现版本漂移。

### 2. 虚拟环境约定

统一使用项目根目录的 `.venv`。新环境执行：

```powershell
uv venv --python 3.12
uv sync --locked
```

`uv sync` 会复用或创建 `.venv`，不会把依赖安装到全局 Python。项目声明 Python `>=3.10,<3.13`，当前验证版本为 Python 3.12。

### 3. 日常命令

README 统一改为 `uv run ...`，包括环境自检、启动 8787、单次任务和测试。历史设计/实施计划保留当时的命令上下文，不作为当前安装说明。

### 4. 验证与失败策略

迁移完成后依次验证：

1. `uv lock --check` 能确认锁文件与项目元数据一致。
2. `uv sync --locked` 能在当前 `.venv` 完成同步。
3. `rapidocr_onnxruntime` 可被当前环境发现，解决 task7 的实机扫描阻塞。
4. 编译检查和全量 `unittest` 通过。
5. 8787 服务可以使用 `uv run python main.py` 启动；不在迁移过程中自动启动挂机。

如果索引访问或包安装失败，保留已经生成的配置文件，报告具体失败包和命令，不用未声明的替代依赖绕过锁文件。

## 范围

- 包含：`pyproject.toml`、`uv.lock`、兼容 `requirements.txt`、README 当前安装/运行/测试命令、当前虚拟环境同步。
- 不包含：业务逻辑改造、任务行为变更、模板变更、强制重启正在运行的 8787 服务。
