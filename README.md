# 兵临天下辅助（自用版）

基于 **雷电模拟器 + ADB + 图像识别** 的本地挂机辅助，带简易 Web 控制面板。

> 仅供自己账号、自己电脑使用。使用自动化有封号风险，请自行承担。  
> **不会**把账号密码上传到任何第三方服务器。

---

## 和你买的「代练链接」有什么区别？

| | 市面代练链接 | 本项目 |
|---|---|---|
| 原理 | 服务端拿账号密码登录游戏协议/云端挂机 | 本机 ADB 操控你已登录的模拟器 |
| 账号安全 | 密码交给别人，风险高 | 密码只在你本地游戏里 |
| 费用 | 按月/按卡密 | 自用零成本 |
| 功能完整度 | 功能很多、成熟 | 框架已搭好，功能按需逐步加 |
| 依赖 | 对方服务器在线 | 雷电模拟器开着即可 |

市面那种 `http://IP:端口/dl?u=账号&m=token...` 是**云端代练后台**。  
我们做的是更安全的 **本地 ADB 脚本**，界面风格类似（挂机/停挂机/功能开关/日志），但技术路线不同。

---

## 环境要求

- Windows + 雷电模拟器 9/14
- ADB：`C:\leidian\LDPlayer14\adb.exe`（可在 `config/default.yaml` 修改）
- Python **3.10+**（推荐 3.12）
- 游戏包名：`com.sgbltx.goodgame`（三国兵临天下）
- 模拟器分辨率建议固定：**1920×1080**（改分辨率后模板要重采）

当前已检测到设备可连接：`127.0.0.1:5555` / `emulator-5554`。

---

## 快速开始

### 1. 安装依赖

在项目目录打开终端：

```powershell
cd "C:\Users\liningshuai\Desktop\code\兵临天下辅助"
uv venv --python 3.12
uv sync --locked
```

依赖声明和锁定结果由 pyproject.toml 与 uv.lock 管理。requirements.txt 仅作为兼容导出文件，由 uv export 生成，不要直接编辑。

### 2. 环境自检

```powershell
uv run python main.py --check
```

### 3. 启动控制面板

```powershell
uv run python main.py
```

浏览器打开：http://127.0.0.1:8787

### 4. 使用流程

1. 雷电模拟器启动，**手动登录**游戏到主城/大厅（竖屏 **1080×1920**）  
2. 面板确认「设备在线」（当前常用 `emulator-5554`）  
3. 打开需要的功能开关（先从「自动领邮件」练手）  
4. 点 **挂机**，或命令行单次测试：  
   `uv run python main.py --run auto_mail`  
5. 看「日志信息」是否 success  

**已实现：自动领邮件**  
路径：`主城 → 更多 → 邮件 → 一键阅读 → 侧边点击关闭`  

**已实现：过关斩将**  
路径：
1. 准备页「开始挑战」`(540,1265)`  
2. 创建编队再点「开始挑战」`(540,1565)`（不改阵容）  
3. 等战斗结束 → 领奖  

配置 `config/default.yaml` 或 `config/runtime.yaml` → `tasks.guoguan`：  
- `max_runs: 2` — 免费次数打几轮  
- `buy_extra: false` — **开关**：免费用完后是否点「+」花 200 元宝再买 1 次并再打  
- `battle_timeout: 900` — 单场最长等待秒  

```powershell
uv run python main.py --run guoguan
# 想买次数时，把 runtime/default 里 buy_extra 改成 true
```

**已实现：辎重站**  
路径：`主城 → 封地 → 辎重站 → 指定资源免费购买 3 次 → 返回 → 世界回主城`。四类资源共享免费次数，面板中只需选择铜钱、粮草、木材或生铁中的一种；任务不会点击付费购买。



---

## 功能开发顺序（建议）

市面面板里那些功能，我们按「收益高、流程短」优先：

1. **自动领邮件**（示例已写好，需采集模板）  
2. **每日许愿**（示例骨架已写好）  
3. **自动问道 / 夜观星象**  
4. **过关斩将 / 群雄比武**  
5. **镇魂塔 / 轮回 / 梦魇** 等长流程副本  

每个功能 = **模板图 + 一个 Python 任务类**。

---

## 如何新增一个功能（核心）

### 步骤 A：采集模板

1. 游戏停在目标界面  
2. 截图：

```powershell
uv run python main.py --screenshot
```

3. 用画图/PS 看按钮左上角坐标和宽高，裁剪：

```powershell
uv run python scripts/capture_template.py --name mail_icon --x 1700 --y 200 --w 90 --h 90
```

模板放到 `assets/templates/*.png`。

### 步骤 B：写任务逻辑

参考 `src/tasks/auto_mail.py`：

1. 新建 `src/tasks/xxx.py`，继承 `BaseTask`  
2. 在 `src/tasks/registry.py` 的 `IMPLEMENTED` 里注册  
3. 在 `config/default.yaml` 的 `tasks` 增加开关  

### 步骤 C：在面板启用并挂机

---

## 目录结构

```
兵临天下辅助/
├── main.py                 # 启动入口
├── requirements.txt
├── config/default.yaml     # 默认配置
├── assets/
│   ├── screenshots/        # 调试截图
│   └── templates/          # 按钮模板
├── src/
│   ├── adb/device.py       # ADB 封装
│   ├── vision/match.py     # 模板匹配
│   ├── tasks/              # 各功能任务
│   ├── bot/engine.py       # 挂机引擎
│   └── web/                # 控制面板
├── scripts/capture_template.py
└── logs/
```

---

## 风险与边界

1. **封号风险**：任何脚本都可能被检测，建议操作间隔随机、不要 24h 过激行为。  
2. **不要**把本机面板端口映射到公网。  
3. **不要**再把账号密码填给来路不明的代练站。  
4. 本项目不做游戏协议破解/外挂注入；只做模拟器 UI 自动化。  
5. 游戏更新 UI 后，需要重新采集模板。

---

## 常见问题

**Q: adb devices 是空的？**  
雷电设置里打开「ADB 调试」，或用雷电多开器看端口，把 `config/default.yaml` 里 `device.serial` 改成对应值。

**Q: 点了挂机没反应？**  
看日志是不是「缺少模板」。先采集 `mail_icon.png` 等文件。

**Q: 能做成手机浏览器打开的代练链接吗？**  
可以，但那是另一条「云端协议挂机」路线，开发量和风控都高得多。自用优先本机 ADB。

---

## 下一步你可以让我做的

1. 你打开游戏到主界面，我帮你截图并标定「邮件/许愿」等按钮模板  
2. 按你最常用的 3～5 个功能，逐个把完整流程写出来  
3. 加「每日定时任务」「多开多账号队列」
