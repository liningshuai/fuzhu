# fuzhu — 雷电模拟器游戏日常自动化脚本

基于 ADB + OpenCV 模板匹配的本地屏幕自动化框架，用于在雷电模拟器上
自动完成《三国兵临天下》的日常操作（领邮件、政务、驿馆等）。

**原理**：脚本通过 ADB 连接模拟器 → 截屏 → 图像识别定位按钮 → 模拟点击。
模拟器必须开着游戏才能工作（不是云端脱机挂机）。

> ⚠️ **风险提示**
>
> - 大多数手游用户协议禁止第三方自动化工具，使用可能导致封号，风险自负。
> - 本项目**不包含**、也不会加入任何对抗检测、修改客户端、真实协议抓包/签名、代理池或绕风控功能。
> - **Phase 1 仅限本机、单设备、已授权人工登录环境**；默认监听 `127.0.0.1`，勿对公网暴露。
> - `protocol/` 目录为 **mock（模拟）**，不会连接游戏服、不会操作游戏客户端。

## 环境要求

- Windows + 雷电模拟器 9/最新版（已在 14.0.21.0 规划）
- [uv](https://docs.astral.sh/uv/)（负责 Python 版本、虚拟环境和依赖，无需单独装 Python）
- 模拟器分辨率：雷电 1080P 即可；游戏《三国兵临天下》实际截图为竖屏 **1080x1920**

## 安装

```powershell
# 1. 安装 uv（只需一次，PowerShell 执行）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 克隆并安装依赖（uv 会自动创建 .venv 并按 uv.lock 精确还原）
git clone https://github.com/liningshuai/fuzhu.git
cd fuzhu
uv sync --extra dev
```

## Phase 1：单设备 Web 控制 MVP

验收说明见 **`docs/phase-1-acceptance.md`**。当前能力：

| 能力 | 说明 |
|------|------|
| 执行通道 | **本地识图执行**（ADB） / **协议模拟（mock，不会操作游戏）** / **不可用** |
| Job 状态机 | `queued` → `running` → `succeeded` / `failed` / `blocked` / `cancelled` |
| 单设备 FIFO | 同一 `device_id` 同时最多 1 个 Vision **running**；其它任务独立 Job 且 **queued**，按创建顺序串行 |
| 持久化 | SQLite：`data/fuzhu.db`（目录已 gitignore） |
| 监控 | Web 2.5s 轮询 Job 历史（状态/耗时/失败分类/排队位置），无需手动刷新 |
| Job 诊断 | `failure_code` + 中文 `user_message` + `retryable`；API 不返回堆栈/路径/口令 |
| 网络 | 默认 **127.0.0.1:8787**；局域网需 `allow_lan` + `admin_token`，且**仅**可通过请求头 `X-Admin-Token` 传口令（禁止 URL query） |

### Job 失败分类（`failure_code`）

| 代码 | 含义 | 典型 status | retryable |
|------|------|-------------|-----------|
| `DEVICE_NOT_BOUND` | 角色未绑定设备 | blocked | false |
| `DEVICE_BUSY_OR_QUEUED` | 设备忙/排队中（说明态，**不是 failed**） | queued | true |
| `PRECONDITION_NOT_MET` | 前置界面不满足 | blocked / failed | true |
| `TARGET_NOT_FOUND` | 预期目标未找到 | blocked / failed | true |
| `POSTCONDITION_NOT_MET` | 操作后验证失败 | failed | true |
| `EXECUTION_ERROR` | 本地执行异常 | failed | true |
| `RECOVERED_AFTER_RESTART` | 进程重启中断未完成 Job | failed | true |

成功或尚未失败时 `failure_code` 为空。Vision 队列：`queue_position` 对 running 固定为 `0`，对排队中为从 1 起的 FIFO 位次；非 Vision 为 `null`。

Job 详情 `events` 仅返回 `id` / `job_id` / `ts` / `level` / `message`（安全文案）；**永不**返回 `screenshot_path`、堆栈、凭据、ADB 命令或本机路径。`tech_summary` 仅库内受控元数据，API 不返回。

`jobs.extras_json` 仅允许固定 `{"channel":"vision"|"protocol_mock"}`（由 `job.route` 生成，从不复制 runner extras）。`GET /api/jobs`、`/api/jobs/{id}`、`/api/logs` 等**不返回** `extras` 字段；`channel_label` 仅由 `route` 推导。

### 启动 Web 控制台

```powershell
uv sync --extra dev
uv run fuzhu-api
# 浏览器打开 http://127.0.0.1:8787
```

可选：幂等初始化演示角色/设备（**不覆盖**已有数据）：

```powershell
uv run fuzhu-seed
```

### mock 与 Vision 的区别

| | 本地识图执行 (vision) | 协议模拟 (protocol mock) |
|--|----------------------|---------------------------|
| 是否操作模拟器 | 是（ADB 点击） | **否** |
| 是否连游戏服 | 否 | **否**（假数据） |
| 成功条件 | 前置界面确认 + 操作后验证 | mock 逻辑返回 OK |
| 适用 | 本机已登录游戏 | 接口/UI 联调 |

在 Web「执行通道偏好」中可切换 `auto` / `vision` / `protocol`。

### 测试

```powershell
uv sync --extra dev
uv run pytest tests/ -q
```

自动化测试使用 fake vision runner，**不会**连接 ADB、不会点击真实模拟器。

### 配置摘录（`config/config.yaml`）

```yaml
api:
  host: "127.0.0.1"
  port: 8787
  allow_lan: false          # true 时必须设置 admin_token，并绑定 0.0.0.0
  admin_token: ""           # 仅作服务端配置；客户端必须用请求头 X-Admin-Token
  db_path: "data/fuzhu.db"
  default_device_id: "local-ldplayer"
```

**LAN 鉴权（`allow_lan=true`）**：

- 管理口令**只能**通过 HTTP 请求头 `X-Admin-Token` 传递。
- **禁止**把 `admin_token` 写进 URL query（例如 `?admin_token=...`）、书签、截图、访问日志示例、前端 JS 常量。
- **WebUI**：打开页面后先探测 `/api/health`；LAN 模式下显示「管理口令」输入框（`type=password`），口令仅存当前页内存，验证成功后各 API 带 `X-Admin-Token`；刷新或 401 后需重新输入。不实现“记住口令”。
- API 示例：`curl -H "X-Admin-Token: <你的口令>" http://<lan-host>:8787/api/roles`
- `/api/health` 仍可匿名探活；其余 `/api/*` 均需上述请求头。

雷电设置里开启 ADB：`设置 → 其他设置 → ADB调试 → 开启本地连接`。

## 快速开始（CLI 识图）

所有命令用 `uv run` 执行，不需要手动激活虚拟环境：

```bash
# 1. 确认能连上模拟器、查游戏包名（先在模拟器里打开游戏）
uv run main.py info
#    把输出里 mCurrentFocus 的包名填入 config/config.yaml 的 game.package

# 2. 截一张游戏画面
uv run main.py shot

# 3. 从截图里裁剪按钮做成模板图
uv run tools/crop_template.py captures/screen_xxxx.png

# 4. 验证模板能被识别
uv run tools/test_match.py mail/mail_icon.png

# 5. 在 config/config.yaml 里把对应任务 enabled 改为 true，然后
uv run main.py run mail.yaml   # 单跑一个任务调试
uv run main.py once            # 所有启用任务跑一遍
uv run main.py loop            # 循环模式，按 interval_minutes 周期执行
```

换新机器移植：装好 uv → `git clone` → `uv sync`，环境即完全还原
（`uv.lock` 锁定了所有依赖的精确版本，务必保留在仓库里）。

## 目录结构

```
fuzhu/
├── main.py              CLI 入口：info / shot / once / loop / run
├── api/                 FastAPI + Job 执行 + SQLite
├── web/                 本机 WebUI
├── common/              领域模型（Job 状态机、角色、设备）
├── vision_worker/       识图执行适配
├── protocol/            协议任务（**仅 mock**）
├── core/                ADB / 视觉 / 任务引擎
├── tasks/*.yaml         识图步骤定义（含前后置验证）
├── templates/           模板图
├── data/                SQLite（本地，不入库）
├── docs/phase-1-acceptance.md
├── tests/               Phase1 自动化测试
├── config/config.yaml
└── pyproject.toml
```

## 添加新任务（不用写代码）

1. 在 `tasks/` 下新建一个 yaml，参考 `tasks/mail.yaml`；
2. 需要识别的按钮先截图裁成模板放入 `templates/`；
3. 在 `config/config.yaml` 的 `tasks` 列表里登记并 `enabled: true`；
4. 若走 Web：在 `common/registry_meta.py` 登记 TaskKey 元数据。

支持的步骤类型（action）：

| action        | 说明 |
|---------------|------|
| `tap_image`   | 找图并点击，`optional: true` 表示找不到就跳过；`on_missing: blocked` 可映射阻塞 |
| `tap_image_all` | 点击画面上所有匹配位置（如一排领取按钮） |
| `wait_image`  | 等待某图出现（不点击）— 常用作**前置确认** |
| `wait_gone`   | 等待某图消失 — 常用作**后置验证** |
| `tap_xy`      | 点击固定坐标 |
| `swipe`       | 滑动，`from: [x,y]` → `to: [x,y]` |
| `back`        | 按返回键，`times` 次数 |
| `sleep`       | 等待秒数 |
| `start_app` / `stop_app` | 启动/停止游戏 |
| `repeat`      | 循环；支持 `until_gone` / `empty_is_blocked` / `require_progress` |

各步骤通用参数：`threshold`（相似度阈值，默认 0.85）、`timeout`（等待秒数）、
`after_sleep`（执行后等待）、`region: [x1,y1,x2,y2]`（限定搜索区域）。

## 常见问题

- **连不上模拟器**：确认雷电 ADB 调试已开启；多开时第 2 个实例端口是
  `5557`，改 `config.yaml` 的 `serial`。系统 adb 和雷电 adb 版本冲突时，
  把 `adb_path` 指向雷电目录下的 `adb.exe`。
- **找不到图**：用 `tools/test_match.py` 看实际相似度，适当调低
  `threshold`（不建议低于 0.7）；检查分辨率是否和裁模板时一致。
- **中文路径**：代码已用 imdecode/imencode 处理，仓库放中文目录下没问题。
- **Web 重启丢数据？** Phase1 起写入 `data/fuzhu.db`，重启保留。
- **为什么邮件/政务失败而不是成功？** Phase1 要求可验证；无法确认领取/接受结果时返回 `failed`/`blocked`，禁止假成功。
