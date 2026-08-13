# 仓库物品资料采集设计

**状态：** 已确认设计，等待实施。

## 1. 目标

新增一个由 8787 面板手动触发的“扫描仓库”工具，依次采集仓库中的五个分类：

1. 道具
2. 技能碎片
3. 军械碎片
4. 宝物碎片
5. 特产

采集结果写入本地 SQLite 数据库，同时保存每个物品的卡片截图和图标截图。该工具用于为后续功能建立统一的物品识别资料，不属于日常挂机任务，不加入任务注册表和挂机循环。

## 2. 范围与非目标

### 本次范围

- 从主城进入仓库。
- 依次进入五个分类并扫描全部可见页面。
- 使用 OCR 读取物品名称和数量文本。
- 保存物品卡片、图标、来源页面截图和 OCR 置信度。
- 通过页面指纹和物品指纹去重。
- 五个分类全部完成后返回主城。
- 在 8787 面板显示扫描状态、进度、数量和错误信息。

### 明确不做

- 不把仓库扫描作为每日任务。
- 不自动使用物品。
- 不自动购买、兑换或消耗资源。
- 不根据物品数量执行后续业务。
- 不在挂机线程运行时强行抢占设备。

## 3. 总体方案

采用“固定网格裁剪 + OCR + SQLite”的方案：

- 使用模板识别仓库入口、仓库标题、返回按钮和五个分类标签。
- 使用配置化的固定网格识别四列物品卡片；网格坐标从用户提供的 1080×1920 页面校准。
- 每个卡片拆分为图标区域和名称区域。
- OCR 只负责读取名称与数量，不负责决定点击坐标。
- 低置信度 OCR 结果仍保存，但标记 `needs_review=1`，不覆盖已有高置信度记录。
- 每页扫描后立刻写入数据库，保证中断后仍保留已完成部分。

## 4. 状态机

```text
IDLE
  ↓ 点击“扫描仓库”
PRECHECK
  ├─ 设备离线/挂机中/无法确认主城 → REJECTED
  └─ 通过 → OPEN_WAREHOUSE
OPEN_WAREHOUSE
  ├─ 找不到仓库入口 → FAILED
  └─ 成功 → SCAN_CATEGORY(道具)
SCAN_CATEGORY
  ├─ 识别当前页卡片
  ├─ 保存截图、图标、OCR 结果和观察记录
  ├─ 页面出现新内容 → 有界上滑，继续当前分类
  ├─ 页面重复/连续无新增 → 下一个分类
  ├─ 达到最大滑动次数 → PARTIAL，停止采集
  └─ 用户停止/设备异常 → STOPPING
NEXT_CATEGORY
  ├─ 还有分类 → SCAN_CATEGORY
  └─ 五个分类完成 → CLOSE_WAREHOUSE
CLOSE_WAREHOUSE
  ├─ 点击仓库左上角返回
  ├─ 验证主城锚点
  └─ 成功 → SUCCESS；失败 → PARTIAL
```

普通成功路径必须完成五个分类后才返回主城。异常路径会停止继续扫描，并在安全范围内尝试返回主城；数据库保留已完成的分类和页面。

## 5. 数据库设计

数据库路径：

```text
data/warehouse_catalog/catalog.db
```

### `scan_sessions`

记录一次扫描批次：

- `id`：扫描批次 UUID
- `started_at`、`finished_at`
- `status`：`running`、`success`、`partial`、`failed`、`stopped`
- `categories_completed`
- `items_found`
- `low_confidence_count`
- `error_message`

### `warehouse_items`

保存物品主记录：

- `id`
- `category_code`
- `name_raw`
- `name_normalized`
- `quantity_text`
- `ocr_confidence`
- `icon_path`
- `card_path`
- `icon_hash`
- `needs_review`
- `first_seen_at`、`last_seen_at`

物品去重键为：

```text
category_code + name_normalized + icon_hash
```

数量不参与物品身份判断。

### `warehouse_observations`

保存每次扫描实际观察到的结果：

- `scan_id`
- `item_id`
- `category_code`
- `page_index`
- `screen_path`
- `card_x`、`card_y`、`card_width`、`card_height`
- `observed_at`

这样既有稳定的物品目录，也能追溯物品来自哪一次扫描和哪一页。

## 6. 文件与资产

```text
data/warehouse_catalog/
  catalog.db
  scans/<scan_id>/
    category_page_001.png
    category_page_002.png
  cards/<category>/
    <item_id>.png
  icons/<category>/
    <item_id>.png
```

模板资产仍放在现有目录：

```text
assets/templates/warehouse_entry.png
assets/templates/warehouse_title.png
assets/templates/warehouse_back.png
assets/templates/warehouse_tab_*.png
```

网格布局、OCR 阈值、最大滑动次数等可调参数放入：

```text
config/warehouse.yaml
```

默认安全限制：

- 每分类最多上滑 `30` 次。
- 连续 `2` 页没有新页面内容时结束当前分类。
- OCR 置信度低于 `0.70` 时标记待复核。

## 7. 8787 控制面板

新增独立的“仓库资料采集”区域：

- `扫描仓库`
- `停止扫描`
- 当前状态
- 当前分类
- 当前页码
- 已完成分类数
- 已发现物品数
- OCR 待复核数
- 最近错误信息

启动扫描时，如果挂机正在运行，接口拒绝请求并提示先停止挂机。扫描过程中禁止重复启动第二个扫描线程。

## 8. 错误处理与安全边界

- 不识别仓库入口时不盲目点击。
- 不识别分类标签时停止，不继续猜测坐标。
- OCR 失败不丢弃卡片，保存截图并标记待复核。
- 页面重复时停止当前分类，不无限滑动。
- 达到滑动上限时记录 `partial`，不继续点击。
- 数据库每页提交一次事务。
- 扫描停止后不继续进入下一分类。
- 返回主城只使用模板识别、已有返回逻辑和主城锚点验证。

## 9. 验收标准

1. 8787 面板可以手动启动和停止扫描。
2. 扫描不会启动挂机，也不会注册为每日任务。
3. 五个分类按固定顺序完成扫描。
4. 页面内容多时可以有界滑动并识别重复页面。
5. 数据库保存分类、名称、OCR 置信度、图标路径和卡片路径。
6. 相同物品重复出现不会产生无穷重复记录。
7. OCR 低置信度记录可被单独识别。
8. 五个分类全部完成后自动返回主城。
9. 中途异常或手动停止不会卡死，并保留部分结果。
10. 离线单元测试、图片回放测试、编译检查和 8787 健康检查全部通过。
