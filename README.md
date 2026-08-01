# fuzhu — 雷电模拟器游戏日常自动化脚本

基于 ADB + OpenCV 模板匹配的本地屏幕自动化框架，用于在雷电模拟器上
自动完成《三国兵临天下》的日常操作（领邮件、政务、驿馆等）。

**原理**：脚本通过 ADB 连接模拟器 → 截屏 → 图像识别定位按钮 → 模拟点击。
模拟器必须开着游戏才能工作（不是云端脱机挂机）。

> ⚠️ 风险提示：大多数手游用户协议禁止第三方自动化工具，使用可能导致
> 封号，风险自负。本项目不包含、也不会加入任何对抗检测或修改游戏
> 客户端的功能。

## 环境要求

- Windows + 雷电模拟器 9/最新版（已在 14.0.21.0 规划）
- Python 3.9+
- 模拟器分辨率固定为 1920x1080（平板版），DPI 默认

## 安装

```bash
pip install -r requirements.txt
```

雷电设置里开启 ADB：`设置 → 其他设置 → ADB调试 → 开启本地连接`。

## 快速开始

```bash
# 1. 确认能连上模拟器、查游戏包名（先在模拟器里打开游戏）
python main.py info
#    把输出里 mCurrentFocus 的包名填入 config/config.yaml 的 game.package

# 2. 截一张游戏画面
python main.py shot

# 3. 从截图里裁剪按钮做成模板图
python tools/crop_template.py captures/screen_xxxx.png

# 4. 验证模板能被识别
python tools/test_match.py mail/mail_icon.png

# 5. 在 config/config.yaml 里把对应任务 enabled 改为 true，然后
python main.py run mail.yaml   # 单跑一个任务调试
python main.py once            # 所有启用任务跑一遍
python main.py loop            # 循环模式，按 interval_minutes 周期执行
```

## 目录结构

```
fuzhu/
├── main.py              入口：info / shot / once / loop / run
├── config/config.yaml   全局配置 + 任务开关
├── tasks/*.yaml         任务定义（步骤式，不用写代码）
├── templates/           模板图（自己裁剪，见 templates/README.md）
├── core/                框架代码（adb / vision / task / scheduler）
├── tools/               辅助工具（裁剪模板、测试匹配）
├── captures/            截图输出（不入库）
└── logs/                运行日志（不入库）
```

## 添加新任务（不用写代码）

1. 在 `tasks/` 下新建一个 yaml，参考 `tasks/mail.yaml`；
2. 需要识别的按钮先截图裁成模板放进 `templates/`；
3. 在 `config/config.yaml` 的 `tasks` 列表里登记并 `enabled: true`。

支持的步骤类型（action）：

| action        | 说明 |
|---------------|------|
| `tap_image`   | 找图并点击，`optional: true` 表示找不到就跳过 |
| `tap_image_all` | 点击画面上所有匹配位置（如一排领取按钮） |
| `wait_image`  | 等待某图出现（不点击） |
| `wait_gone`   | 等待某图消失（如加载画面） |
| `tap_xy`      | 点击固定坐标 |
| `swipe`       | 滑动，`from: [x,y]` → `to: [x,y]` |
| `back`        | 按返回键，`times` 次数 |
| `sleep`       | 等待秒数 |
| `start_app` / `stop_app` | 启动/停止游戏 |
| `repeat`      | 循环子步骤，直到 `until_gone` 的图消失或达到 `times`/`max_loops` |

各步骤通用参数：`threshold`（相似度阈值，默认 0.85）、`timeout`（等待秒数）、
`after_sleep`（执行后等待）、`region: [x1,y1,x2,y2]`（限定搜索区域）。

## 常见问题

- **连不上模拟器**：确认雷电 ADB 调试已开启；多开时第 2 个实例端口是
  `5557`，改 `config.yaml` 的 `serial`。系统 adb 和雷电 adb 版本冲突时，
  把 `adb_path` 指向雷电目录下的 `adb.exe`。
- **找不到图**：用 `tools/test_match.py` 看实际相似度，适当调低
  `threshold`（不建议低于 0.7）；检查分辨率是否和裁模板时一致。
- **中文路径**：代码已用 imdecode/imencode 处理，仓库放中文目录下没问题。
