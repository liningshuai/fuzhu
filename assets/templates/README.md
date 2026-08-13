# 模板目录

分辨率基准：**1080 × 1920（竖屏）**。Windows 下请用项目内的读写函数，避免中文路径导致 OpenCV 读图失败。

## 已采集（自动领邮件）

| 文件名 | 说明 |
|--------|------|
| `nav_fief.png` | 底栏「封地」— 主城判定 |
| `nav_war.png` | 底栏「征战」— 后续过关斩将 |
| `btn_more.png` | 主城右下「更多」 |
| `btn_more_wide.png` | 更多按钮稍大版 |
| `more_title.png` | 更多弹窗标题 |
| `more_close.png` | 更多弹窗关闭 |
| `btn_mail.png` / `btn_mail_icon.png` | 更多里的「邮件」 |
| `mail_title.png` | 邮件界面标题 |
| `mail_read_all.png` / `mail_read_all_tight.png` | 「一键阅读」 |
| `mail_close.png` | 邮件关闭 X（可选，空白点击更稳） |

## 过关斩将

| 文件名 | 说明 |
|--------|------|
| `nav_war.png` | 底栏「征战」 |
| `war_title.png` | 征战列表标题 |
| `guoguan_entry_title.png` / `guoguan_entry.png` | 列表里过关斩将入口 |
| `guoguan_title.png` | 详情页标题 |
| `guoguan_start.png` / `guoguan_start_tight.png` | 准备页「开始挑战」(y≈1140) |
| `guoguan_form_title.png` | 创建编队弹窗标题 |
| `guoguan_form_start.png` / `guoguan_form_start_tight.png` | 编队弹窗里的「开始挑战」(y≈1580) |
| `guoguan_fighting.png` | 大字「战斗中」（战斗等待标志） |
| `guoguan_view_battle.png` | 「查看战斗」（**不要点击**，仅辅助识别） |
| `guoguan_reward*.png` | 「领取/获取奖励」（结束后再采） |
| `guoguan_add.png` | 购买次数「+」 |
| `guoguan_reward.png` | 「领取奖励」（首次战斗结束后可自动生成） |
| `ui_back.png` | 左上角返回 |

## 辎重站

| 文件名 | 说明 |
|--------|------|
| `nav_world.png` | 封地底栏「世界」，用于返回主城 |
| `zizhong_entry_icon.png` | 封地内辎重站上方入口图标 |
| `zizhong_entry_building.png` | 封地内辎重站对应建筑，图标入口失败时使用 |
| `zizhong_title.png` | 辎重站购买页标题 |
| `zizhong_free_buy.png` | 资源卡金色「免费购买」按钮 |
| `zizhong_ui_back.png` | 辎重站页左上返回按钮 |

## 比武大会

| 文件名 | 说明 |
|--------|------|
| `arena_wuguan_tab.png` | 征战页「武馆」Tab |
| `arena_entry_biwudahui.png` | 武馆页「比武大会」入口卡片标题 |
| `arena_title.png` | 比武大会页面标题 |
| `arena_tournament_title.png` | 当前比武大会轮次标题 |
| `arena_champion_like.png` | 冠军卡片「点赞」按钮 |
| `arena_signup.png` | 页面底部「报名」按钮 |

## 见证传奇

| 文件名 | 说明 |
|--------|------|
| `legend_explore_tab.png` | 征战页「探险」Tab |
| `legend_entry.png` | 探险页「见证传奇」入口 |
| `legend_title.png` | 见证传奇列表标题 |
| `legend_add.png` | 列表底部增加挑战次数的「+」 |
| `legend_buy_title.png` | 增加挑战次数提示标题 |
| `legend_buy_confirm_area.png` | 增加挑战次数弹窗完整「确定」按钮区域 |
| `legend_challenge.png` | 英雄详情「挑战」按钮 |
| `legend_form_title.png` | 英雄历练编队标题 |
| `legend_start_challenge_area.png` | 编队页面完整「开始挑战」按钮区域 |

## 名士拜访

| 文件名 | 说明 |
|--------|------|
| `nav_shop.png` | 主城底栏「商店」 |
| `shop_title.png` | 商店页面标题 |
| `shop_mingshi_tab.png` | 商店内「名士拜访」页签 |
| `mingshi_refresh.png` | 名士拜访页面「每日5:00刷新」标识 |
| `mingshi_coin_icon.png` | 商品购买按钮上的铜钱图标；只在商品按钮区域内匹配 |

## 夜观星象

| 文件名 | 说明 |
|--------|------|
| `stargaze_academy.png` | 封地内书院建筑稳定区域 |
| `stargaze_free_marker.png` | 书院上方的免费观星入口图标 |
| `stargaze_title.png` | 观星弹窗标题 |
| `stargaze_free_item.png` | 免费「星晷×1」按钮 |
| `stargaze_paid_observe.png` | 元宝观星按钮，仅用于确认付费状态，禁止点击 |
| `stargaze_close.png` | 观星弹窗左上角关闭按钮 |

观星奖励弹窗在当前采集资料中还没有独立截图，因此没有把未知模板列为必需模板；
代码会优先复用已有的「点击任意区域关闭」奖励提示模板，再尝试专用奖励模板和现有安全弹窗检测，
未识别时安全失败。

## 采集建议

1. 分辨率固定 **1080×1920 竖屏**，不要切换  
2. 模板尽量只裁按钮本体，少带背景  
3. 避免裁进会变动的数字/红点  
4. 灰/黄两态按钮可各采一张，或降低阈值

## 重复登录恢复

| 文件 | 用途 |
|------|------|
| `duplicate_login_message.png` | 重复登录提示文字裁剪 |
| `duplicate_login_confirm.png` | 重复登录弹窗“确定”按钮裁剪 |

会话恢复守卫只在 1080×1920 竖屏的中央 ROI
`(x=100, y=650, w=880, h=850)` 内搜索这两个模板，默认匹配阈值为
`0.78`。模板尽量只保留稳定的弹窗文字和按钮，避免依赖变化的游戏背景。

## 启动后进入主城

| 文件 | 用途 |
|------|------|
| `startup_announcement_claim.png` | 公告页“朕已阅”按钮 |
| `startup_enter_game.png` | 登录页“进入游戏”按钮 |
| `startup_permanent_claim.png` | 永久卡奖励“立即领取”按钮 |
| `startup_highlight_close_hint_reward.png` | 奖励弹窗中的高亮“点击任意区域关闭”提示 |
| `startup_highlight_close_hint.png` | 高亮弹窗“点击任意区域关闭”提示 |

这些模板只在启动状态收敛流程中使用，搜索区域为 1080×1920 全屏；只有模板命中才执行按钮点击或安全空白点击。

### 启动活动回放模板约定

| 文件 | 用途 |
|------|------|
| `startup_activity_current_poster.png` | 当前活动弹窗主体海报，用于确认活动面板仍在屏幕中央 |

- 活动回放截图统一放在 `assets/screenshots/startup_activity_replay.png`，分辨率固定为 **1080×1920 竖屏**。
- `startup_activity_*.png` 只负责识别活动面板；关闭动作固定点击安全空白点 **`(30, 500)`**，不要把关闭逻辑编码进模板名字。
- 当前 `startup_activity_current_poster.png` 的稳定裁剪基准为 `980×637`，对应回放图中的 `(left=49, top=723, right=1029, bottom=1360)`；这个取景用于避开屏幕外围、顶部状态区和其他不稳定区域。
- 裁剪时排除模拟器边框、动态倒计时、红点提示等不稳定元素，优先保留活动海报本体。
- 后续新增活动时，继续按 `startup_activity_*.png` 命名补充模板/回放资产即可，不需要新增 Python 分支。
