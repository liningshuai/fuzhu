# Task 1 Report: Define warehouse models and SQLite store

## 修改文件

- `src/warehouse/__init__.py`
  - 新增仓库目录包导出。
- `src/warehouse/models.py`
  - 新增 `WarehouseCategory`、`ItemObservation`、`WarehouseScanResult` 数据类。
- `src/warehouse/store.py`
  - 新增 `WarehouseCatalogStore(path: Path)`。
  - 实现 `open()`、`start_scan()`、`upsert_observation()`、`finish_scan()`、`get_items(category_code: str | None = None)`、`close()`。
  - 使用 SQLite 表 `scan_sessions`、`warehouse_items`、`warehouse_observations`。
  - 启用外键，使用 UTC ISO 时间戳。
  - 在 `warehouse_items(category_code, name_normalized, icon_hash)` 上创建唯一索引 `ux_warehouse_items_identity`。
  - `upsert_observation()` 通过唯一键更新已有物品的 `last_seen_at` 和最新字段，同时为每次观察保留一条 `warehouse_observations` 记录。
  - 将传入的项目内绝对 `screen_path` 转成相对项目根目录路径；已经是相对路径时原样保存为 POSIX 风格。
- `tests/warehouse/__init__.py`
  - 新增测试包标记。
- `tests/warehouse/test_store.py`
  - 新增 SQLite store 聚焦测试。

## 测试命令 / 结果

### RED

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
```

结果：失败，符合预期。失败原因为实现模块尚不存在：

```text
ModuleNotFoundError: No module named 'src.warehouse'
FAILED (errors=1)
```

### GREEN

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
```

结果：通过。

```text
Ran 4 tests in 0.201s

OK
```

### 最终验证

命令：

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_store -v
```

结果：通过。

```text
test_finish_scan_counts_low_confidence_items_needing_review ... ok
test_open_creates_required_schema_with_foreign_keys_and_unique_item_key ... ok
test_repeated_same_key_updates_last_seen_without_duplicate_items ... ok
test_upsert_observation_creates_one_item_and_one_observation_row ... ok

Ran 4 tests in 0.214s

OK
```

## 覆盖点

- schema 创建：确认存在 `scan_sessions`、`warehouse_items`、`warehouse_observations`。
- 外键：确认 store 当前连接启用了 `PRAGMA foreign_keys = ON`。
- 唯一键：确认 `warehouse_items` 存在唯一索引 `ux_warehouse_items_identity`。
- 单次观察：确认创建 1 条 item 和 1 条 observation。
- 重复同键观察：确认不重复创建 item，更新 `last_seen_at` 和最新数量，同时保留 observation 历史记录。
- 扫描结果：确认 `finish_scan()` 返回 `WarehouseScanResult`，并统计分类数、物品数、需复核数。
- 临时数据库：测试全部使用 `tempfile.TemporaryDirectory()` 下的 SQLite 文件，没有创建生产数据库路径。

## 遗留疑问 / 关注点

- 简报要求“Commit one transaction per page through the store API”，但给定接口只有单条 `upsert_observation()`，没有 page 级批量 API。本实现采用每次 `upsert_observation()` 一个事务；如果后续扫描器会按页产生多条观察，建议 Task 2 或后续任务明确是否需要新增 page 级批量写入接口。
- `WarehouseCategory` 已按接口定义为模型，但简报未要求分类表，因此本任务未额外创建分类表，避免超出需求。
- 测试运行产生了 `src/warehouse/__pycache__` 和 `tests/warehouse/__pycache__`。尝试清理这两个明确缓存目录时被工具安全策略拦截，未继续做额外文件操作。
- 未启动 8787，未操作雷电模拟器，未初始化 Git、未创建 worktree、未提交。

---

## 2026-08-09 Task 1 fix round

### Review findings addressed
- Added page-atomic write API `upsert_page(scan_id, observations)` and changed `upsert_observation()` into a compatibility wrapper over that API.
- Added explicit category completion persistence via `scan_category_completions` and `record_category_completion(scan_id, category_code)`.
- Enforced project-relative image paths: in-root absolute paths normalize to POSIX-relative paths; outside-root absolute paths now raise `ValueError`.
- Aligned successful scan/session status from `completed` to `success`.
- Preserved `icon_bytes` / `card_bytes` and added relative `icon_path` / `card_path` persistence on `warehouse_items`.

### Changed files
- `src/warehouse/store.py`
- `tests/warehouse/test_store.py`

### TDD evidence
RED command:
```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
```
Observed expected failures before the fix:
- missing `upsert_page`
- missing `record_category_completion`
- missing `scan_category_completions`
- wrong final status `completed`
- outside-root absolute path accepted instead of rejected

GREEN command:
```powershell
.\.venv\Scripts\python.exe -m unittest tests.warehouse.test_store -v
```
Result:
```text
Ran 7 tests in 0.408s

OK
```

Final verification:
```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.warehouse.test_store -v
```
Result:
```text
Ran 7 tests in 0.393s

OK
```

### Concerns
- This round stays within Task 1 data-layer scope, so `icon_path` / `card_path` are persisted metadata only; no file-writing workflow was added here.
- Scanner/controller code is out of scope here, so later tasks still need to call `upsert_page()` and `record_category_completion()` to use the new semantics end to end.
