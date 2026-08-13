# Task 2 Report — 活动回放资产、模板和资产测试

- Date: 2026-08-07
- Task: 加入活动回放资产、模板和资产测试
- commit: none

## Scope

按简报要求，仅修改以下范围：

- `tests/session/test_startup_template_assets.py`
- `assets/screenshots/startup_activity_replay.png`
- `assets/templates/startup_activity_current_poster.png`
- `assets/templates/README.md`

未修改：

- `src/session/startup.py`
- 任何其他业务代码

## TDD 记录

### RED：先补失败断言

在 `tests/session/test_startup_template_assets.py` 新增了两项断言：

1. `startup_activity_replay.png` 必须存在、可读，且尺寸为 `(1920, 1080)`（即 1080×1920 竖屏）。
2. `startup_activity_current_poster.png` 必须存在、可读，并且在回放图上以 `threshold=0.90` 能匹配到，且匹配中心位于活动面板内。

失败验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

失败结果要点：

- `startup_activity_replay.png` 不存在，`test_activity_replay_is_normalized_and_assets_are_readable` 失败。
- `test_activity_template_matches_replay_inside_activity_panel` 因缺少回放文件报错。

### GREEN：补资产与文档

数据来源：

- 原始截图：`C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-ac5950d9-c369-46df-b686-8292b53c946b.png`
- 原始尺寸：`733 × 1303`

处理结果：

1. 将原始截图规范化为 `1080 × 1920` 竖屏，输出到：
   - `assets/screenshots/startup_activity_replay.png`
2. 从规范化后的回放图中裁出当前活动海报主体，输出到：
   - `assets/templates/startup_activity_current_poster.png`

裁剪区域（基于规范化后的 1080×1920 图）：

- left=`49`
- top=`723`
- right=`1029`
- bottom=`1360`
- template size=`980 × 637`

裁剪时保留活动面板主体，排除了模拟器边框、顶部状态区、地图红点等不稳定元素。

### README 更新

在 `assets/templates/README.md` 增补了“启动活动回放模板约定”：

- `startup_activity_*.png` 用于识别活动面板
- 关闭动作固定点击安全空白点 `(30, 500)`
- 活动回放统一使用 `assets/screenshots/startup_activity_replay.png`
- 后续新增活动时，只需补充 `startup_activity_*.png` 资产，不需要新增 Python 分支

## 验证结果

复跑命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

结果：

- Exit code: `0`
- 5 tests passed

关键匹配证据：

- 模板：`startup_activity_current_poster`
- 阈值：`0.90`
- 匹配分数：`1.000`
- 匹配中心：`(539, 1041)`

活动面板边界断言：

- `x` in `[40, 1040]`
- `y` in `[700, 1380]`

结论：

- 匹配中心 `(539, 1041)` 位于活动面板边界内，满足“模板匹配中心位于活动面板内”的要求。

## Final status

- Task 2 completed within allowed scope
- commit: none

## Review fix follow-up (2026-08-07)

### Reviewed feedback

审查意见指出，上一版 `test_activity_template_matches_replay_inside_activity_panel` 只验证：

- 模板能在同一张回放图上自匹配；
- 匹配中心落在较宽的活动面板边界内。

这个结论是成立的。它不足以拦截下面几类错误：

1. 模板裁剪位置明显偏移，但中心点仍在面板内部；
2. 模板把屏幕外围、顶部状态区等外围内容一并裁入；
3. 模板尺寸极端失真（过大/过小），但依旧能在同图自匹配。

### TDD redo

#### RED

先在 `tests/session/test_startup_template_assets.py` 增加两类新测试：

1. `test_activity_template_crop_geometry_is_stable`
   - 约束当前活动模板的稳定几何：
   - 尺寸必须为 `980×637`
   - 宽高比必须与 `980/637` 一致
   - 回放图匹配后的 `top_left/right/bottom` 必须对应当前稳定裁剪框
     `(49, 723, 1029, 1360)`
2. `test_activity_template_policy_rejects_bad_candidate_crops`
   - 用合成坏候选验证回归保护：
   - `full_screen`
   - `outer_chrome_wide_crop`
   - `shifted_left_same_size`
   - `shifted_up_same_size`

先只写测试调用，不写裁剪契约辅助断言实现，验证新增测试确实失败。

失败命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

失败现象：

- `test_activity_template_crop_geometry_is_stable` 报 `AttributeError`
- `test_activity_template_policy_rejects_bad_candidate_crops` 的 4 个子用例同样报 `AttributeError`

这说明新增测试已真正进入 RED，而不是继续停留在“同图自匹配即可通过”的旧保护上。

#### GREEN

随后只在测试文件内补上 `assert_activity_template_crop_contract(...)`，不修改
`startup.py` 或其他业务代码。

这个辅助断言对当前真实资产增加了三层保护：

1. 几何保护
   - 宽=`980`
   - 高=`637`
   - 宽高比固定
2. 取景保护
   - 裁剪框必须精确落在 `(49, 723, 1029, 1360)`
   - 因而不能向左漂移、向上吃进顶部状态区，也不能扩成全屏/超宽模板
3. 面板保护
   - 裁剪框仍必须完整位于活动面板边界内

同时在 `assets/templates/README.md` 追加了这组稳定裁剪几何：

- `980×637`
- `(left=49, top=723, right=1029, bottom=1360)`

用于说明这组约束为什么能排除外围区域与不稳定元素。

### Why the new regression tests protect stability

新增的坏候选并不依赖“当前截图里某个像素值”：

- `full_screen`：拦截把整张回放图误当模板的极端尺寸错误；
- `outer_chrome_wide_crop`：拦截把左右外围/UI 外框带入模板的过宽取景；
- `shifted_left_same_size`：拦截尺寸没变但左侧明显漂移、吃入外围区域；
- `shifted_up_same_size`：拦截尺寸没变但向上漂移、吃入顶部状态区/不稳定区域。

因此这些测试保护的是“结构与区域契约”，不是某一帧的偶然像素。

### Final verification

最终验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.session.test_startup_template_assets -v
```

结果：

- Exit code: `0`
- `7` tests passed

关键证据：

- `startup_activity_current_poster` 在 `startup_activity_replay.png` 上
  `threshold=0.90` 匹配成功
- score=`1.000`
- center=`(539, 1041)`
- 对应稳定裁剪框：
  - left=`49`
  - top=`723`
  - right=`1029`
  - bottom=`1360`

### Scope check

本轮按要求仅处理 Task 2 允许范围内的文件：

- `tests/session/test_startup_template_assets.py`
- `assets/templates/README.md`
- `.superpowers/sdd/2026-08-07-activity-popup-dismissal/task-2-report.md`

未修改 `src/session/startup.py` 或其他业务代码。

### commit

- commit: none
