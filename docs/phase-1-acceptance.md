# Phase 1 / 1.1 验收说明：单设备 Web 控制 + FIFO 队列

> 范围：本机 + 单已授权设备 + 可证明成功/失败 + SQLite 持久化 + **单设备串行队列**
>
> **不在范围**：真实游戏协议、多账号并发、云手机、远程集群、反检测

---

## 1. 架构边界

```text
浏览器 (默认 127.0.0.1)
        │  HTTP 2～3s 轮询
        ▼
   FastAPI (api/)  ── SQLite data/fuzhu.db
        │
        ├─ Job 状态机 + 单 device FIFO 队列（原子领取）
        │
        ├─ route=vision ──► vision_worker + core/ADB  ──► 本地雷电（人工登录）
        │                   ※ 同设备同时仅 1 个 running
        │
        └─ route=protocol ──► protocol/* **mock only**
```

| 允许 | 禁止 |
|------|------|
| 本机 Web 开关任务 | 真实协议/抓包/签名/Token 提取 |
| 单 device 串行队列 | 多 Vision 并行点同一设备 |
| 每任务独立 Job + queued | 用 task A 的 job_id 顶替 task B |
| Protocol **mock** | 把 mock 展示成真实游戏执行 |

**单设备是串行队列，不是并行执行。**

---

## 2. 单设备 FIFO 队列模型

1. 每个执行请求（若未复用）创建 **独立** `Job` 行，`task_key` = 请求任务。
2. 同一 `device_id` 上 Vision：
   - 至多 **1** 条 `status=running`；
   - 其余为 `queued`，**不**启动 ADB、**不**占进程设备锁；
   - running 结束后，dispatcher **原子**领取该设备 `created_at, job_id` 最早的 queued Vision → running。
3. Protocol mock **不**占用 Vision 设备队列，可立即执行。

### Job 去重与复用规则

| 场景 | 行为 |
|------|------|
| 同 `role_id` + 同 `task_key` 已有 queued/running | **复用**该 Job（`reused=true`） |
| 同设备、不同 `task_key` | **必须新建** Job；后来者 `queued` |
| 禁止 | 返回其它 task 的 `job_id` 充当本任务 |

### `run-enabled` 精确定义

- 对该角色每个 `enabled=true` 的任务调用一次入队逻辑；
- 返回 `jobs[]` 中 **每个 enabled 任务恰好对应一个 Job**（新建或同 task 复用）；
- `count == len(jobs) ==` 本批独立 Job 数；
- 若 mail 与 zhengwu 均启用且均走 vision：必须各有一个 job，且 `task_key` 分别为 `mail` / `zhengwu`，`job_id` 不同；至多一个 `running`，另一个 `queued`。

### 重启策略

- 启动时 `mark_interrupted_jobs()`：所有 `queued`/`running` → **`failed`** + `failure_code=RECOVERED_AFTER_RESTART`；
- **不得**标为 `succeeded`。

### 状态机

```text
queued → running → succeeded | failed | blocked | cancelled
```

不允许其它跳转；queued 不是完成态。

### 诊断字段（Phase 1.5）

Job API 返回：`created_at` / `started_at` / `finished_at` / `duration_ms` / `status` / `failure_code` / `user_message` / `retryable` / `queue_position`。

- `duration_ms` 仅在可计算时返回（缺开始或结束则为 null）。
- `user_message` 为中文固定安全提示，不含堆栈、口令、路径、ADB 原文。
- `tech_summary` 仅由 `failure_code`/`result_code`/`error_type` 白名单构造，**API 不返回**。
- `GET /api/jobs/{id}` 的 `events` 经 `_job_event_dict`：仅 `id,job_id,ts,level,message`；无 `screenshot_path`；历史脏数据输出时亦过滤。
- `jobs.extras_json` 仅写 `channel=vision|protocol_mock`；Job/logs API **省略** `extras`；历史脏 `extras_json` 不输出。

### 队列位置

- Vision **running**：`queue_position = 0`
- Vision **queued**：同设备 queued 中 FIFO 的 1-based 位次
- 非 Vision：`null`
- 仅快照，不承诺完成时间

---

## 3. API 要点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/roles/{id}/tasks/{key}/run` | 返回 `created` / `reused` / `queued` / `queue_position` / `running_job_id` + `job`（含诊断字段） |
| POST | `/api/roles/{id}/run-enabled` | 见上节；`count` 与独立 Job 一致 |
| GET | `/api/devices/{device_id}/queue` | 设备 FIFO 快照 |
| GET | `/api/jobs/{id}` | Job 详情 + events；不存在 404 |
| GET | `/api/jobs` | Job 列表（含诊断字段） |

默认监听 **127.0.0.1:8787**。

**LAN 鉴权（`allow_lan=true`）**：

- 必须配置服务端 `admin_token`；客户端**只能**通过请求头 **`X-Admin-Token`** 提交口令。
- **禁止**使用 URL query（不得使用任何 `?admin_token=...` 形式）、body、cookie 传口令。
- **禁止**把管理口令写入书签、截图、日志、示例链接、前端 JavaScript 常量、localStorage / sessionStorage / Cookie / IndexedDB。
- **WebUI**：`/api/health` 探测 `allow_lan` → 为 true 时先显示口令区（password 输入）→ 口令仅页面内存 → 受保护 API 注入 `X-Admin-Token` → 401 或刷新清除内存并回到输入态。`allow_lan=false` 不显示口令区、不发送该头。
- `/api/health` 允许匿名；其余 `/api/*` 无有效 `X-Admin-Token` 时返回 401（响应不回显口令）。

会话字段仅允许 **`mock_session`**（布尔）；禁止 token/cookie/password 等字段名。

---

## 4. 数据库

表：`devices` / `roles` / `role_task_configs` / `role_task_states` / `jobs` / `job_events`

路径：`data/fuzhu.db`（gitignore）。

领取使用 SQLite `BEGIN IMMEDIATE` 事务，保证并发 HTTP 下不双开 running。

---

## 5. 手工验收（≤8 步）

1. `uv run fuzhu-api` → http://127.0.0.1:8787
2. 启用 mail + zhengwu，通道 vision，点「跑已启用」
3. 确认返回/UI：两个不同 `job_id`，一个 running、一个 queued（排队≠完成）
4. 等第一个结束后第二个自动 running→终态
5. 连点同一任务「立即执行」→ 复用同 task job_id，不生成跨 task 引用
6. 重启 API → 原 queued/running 均为 failed
7. `uv run pytest tests/ -q` 零 warning 全绿
8. （可选）真机 vision 路径见「未验收」

---

## 6. 测试覆盖表

| 要求 | 测试 |
|------|------|
| run-enabled 两任务独立 FIFO | `tests/test_queue_fifo.py::test_run_enabled_mail_zhengwu_independent_fifo` |
| 20 并发、running≤1 | `test_20_concurrent_requests_at_most_one_running` / `test_concurrent_claim_never_double_running` |
| 同 task 复用不跨 task | `test_same_task_reuse_not_cross_task` |
| 邮件 YAML 语义 | `tests/test_yaml_semantics.py` |
| 政务 YAML 语义 | 同上 zhengwu_* |
| 本机 / allow_lan+口令 | `tests/test_settings_security.py` |
| LAN WebUI 安全契约 | `tests/test_web_lan_auth.py` |
| 健康/SQLite/mock/fake vision | `tests/test_phase1.py` |
| 重启 failed | `test_restart_marks_queued_running_failed` |
| Job 诊断/失败分类/队列位 | `tests/test_job_diagnostics.py` |

全部使用 fake vision / 脚本化找图，**不连接真实 ADB**。

---

## 7. 已知限制与未验收

- **真机 Vision 邮件/政务仍需人工登录游戏后验证**（自动化不点模拟器）。
- Protocol 永远是 mock。
- 仅单设备；无 WebSocket。
- 界面改版会导致识图 failed/blocked（正确行为）。
