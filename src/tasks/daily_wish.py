"""每日许愿。

流程：
  主城 → 精彩活动（左侧入口，位置可能被限时活动挤偏）
       → 每日许愿页 → 点「许愿」打开选择奖励
       → 按面板配置点选 4 个奖励 → 再点「许愿」确认
       → 若连续登录 7/7 可点紫宝箱领奖（点空白关闭）
       → 左上返回主城

奖励格子按从左到右、从上到下编号（共 14 个），与常见辅助一致。
"""

from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np
from loguru import logger

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    UI_BACK_FALLBACK,
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_main_city,
    ui_back,
)

# ------------------------------------------------------------------ #
# 奖励目录（固定 14 格：从左到右、从上到下）
# 以游戏「选择奖励」弹窗为准（非其它辅助文案）
# 第1行：铜钱5000、铜钱5000、粮草10000、粮草10000
# 第2行：木材5000、木材10000、生铁5000、生铁10000
# 第3行：佳酿*5、锦囊*5、黄金沙漏*1、黄金科研令*1
# 第4行：黄金募令*1、洗炼石宝箱*10
# 坐标按 1080×1920 实测（奖励格中心）
# ------------------------------------------------------------------ #
_XS = (258, 445, 632, 819)  # 四列中心 x
_YS = (583, 768, 950, 1128)  # 四行中心 y（按选中绿框标定）

REWARD_CATALOG: list[dict[str, Any]] = [
    # row 0
    {"id": "coin_5k_1", "name": "铜钱5000", "x": _XS[0], "y": _YS[0]},
    {"id": "coin_5k_2", "name": "铜钱5000", "x": _XS[1], "y": _YS[0]},
    {"id": "food_10k_1", "name": "粮草10000", "x": _XS[2], "y": _YS[0]},
    {"id": "food_10k_2", "name": "粮草10000", "x": _XS[3], "y": _YS[0]},
    # row 1
    {"id": "wood_5k", "name": "木材5000", "x": _XS[0], "y": _YS[1]},
    {"id": "wood_10k", "name": "木材10000", "x": _XS[1], "y": _YS[1]},
    {"id": "iron_5k", "name": "生铁5000", "x": _XS[2], "y": _YS[1]},
    {"id": "iron_10k", "name": "生铁10000", "x": _XS[3], "y": _YS[1]},
    # row 2
    {"id": "wine_5", "name": "佳酿*5", "x": _XS[0], "y": _YS[2]},
    {"id": "bag_5", "name": "锦囊*5", "x": _XS[1], "y": _YS[2]},
    {"id": "hourglass_1", "name": "黄金沙漏*1", "x": _XS[2], "y": _YS[2]},
    {"id": "research_1", "name": "黄金科研令*1", "x": _XS[3], "y": _YS[2]},
    # row 3（仅 2 格）
    {"id": "recruit_1", "name": "黄金募令*1", "x": _XS[0], "y": _YS[3]},
    {"id": "refine_box_10", "name": "洗炼石宝箱*10", "x": _XS[1], "y": _YS[3]},
]

REWARD_BY_ID = {r["id"]: r for r in REWARD_CATALOG}
# 面板展示名：同名格子加位置后缀，避免两个「铜钱5000」分不清
REWARD_LABELS: dict[str, str] = {
    "coin_5k_1": "铜钱5000①",
    "coin_5k_2": "铜钱5000②",
    "food_10k_1": "粮草10000①",
    "food_10k_2": "粮草10000②",
}

# 兼容旧配置 id → 新 id
_LEGACY_REWARD_MAP = {
    "coin_5k": "coin_5k_1",
    "coin_10k": "coin_5k_2",  # 旧「铜钱10000」实为第二格铜钱5000
    "food_5k": "food_10k_1",  # 旧「粮草5000」实为第一格粮草10000
    "food_10k": "food_10k_2",
}

DEFAULT_REWARDS = ["food_10k_1", "food_10k_2", "recruit_1", "refine_box_10"]

# 用于在长期运行的 Web 进程日志中确认实际加载的代码版本。
DAILY_WISH_IMPL_VERSION = "2026-08-05-fixed-v3"

# 精彩活动入口：左侧竖排，可能被限时活动挤上下偏移
ACTIVITY_ENTRY_POINTS = (
    (90, 480),
    (90, 430),
    (90, 530),
    (90, 380),
    (90, 580),
    (110, 500),
    (70, 460),
    (90, 620),
    (90, 340),
)

# 活动页底部「许愿」（打开选奖弹层）
WISH_BUTTON = (540, 1655)
# 选奖弹层内金色「许愿」（选满 4/4 后点一次）
# 截图标定：按钮框约为 x=405..675、y=1534..1610。
WISH_CONFIRM = (540, 1572)
# 每日许愿 Tab（活动页顶部第一项）
WISH_TAB = (175, 420)
# 连续登录 7 日紫宝箱（精彩活动-每日许愿页左侧大紫箱）
# 模板实测中心（wish_login_chest.png）：(280, 900)
LOGIN_CHEST = (280, 900)
# 奖励弹层外的空白位置，只点一次关闭，不再轮流点击多个位置。
REWARD_POPUP_DISMISS = (1020, 1700)

# 选中状态的绿色勾位于奖励格右上角；只检查这个小区域，
# 避免把佳酿等物品本身的绿色品质边框误判为已选。
_SELECT_BADGE_REGION = (25, -92, 95, -22)  # left, top, right, bottom，相对格子中心


def _task_opt(key: str, default):
    meta = (config.get("tasks") or {}).get("daily_wish") or {}
    return meta.get(key, default)


def _find(ctx: TaskContext, screen, name: str, threshold: float = 0.75):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, xy: tuple[int, int]) -> None:
    # 许愿页所有坐标均按 1080x1920 截图标定，关键点击禁止随机抖动。
    ctx.device.tap(int(xy[0]), int(xy[1]), jitter=False)


def _selected_badge_score(screen: np.ndarray, item: dict[str, Any]) -> tuple[int, int]:
    """返回奖励格右上角绿色勾区域的 (绿色像素数, 白色像素数)。"""
    x = int(item["x"])
    y = int(item["y"])
    left, top, right, bottom = _SELECT_BADGE_REGION
    roi = screen[y + top : y + bottom, x + left : x + right]
    if roi.size == 0:
        return 0, 0

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # 绿色勾底与绿色选中框的颜色范围；白色像素用于确认这里确实有勾。
    green = (
        (hsv[:, :, 0] >= 35)
        & (hsv[:, :, 0] <= 95)
        & (hsv[:, :, 1] >= 100)
        & (hsv[:, :, 2] >= 120)
    )
    white = (hsv[:, :, 1] <= 80) & (hsv[:, :, 2] >= 180)
    return int(green.sum()), int(white.sum())


def _is_reward_selected(screen: np.ndarray, item: dict[str, Any]) -> bool:
    """只根据奖励格右上角的绿色勾判断是否已选。"""
    green_count, white_count = _selected_badge_score(screen, item)
    # 普通绿色品质框通常没有右上角白色勾，绿色与白色需同时达到阈值。
    return green_count >= 500 and white_count >= 40


def _selected_reward_ids(screen: np.ndarray) -> set[str]:
    return {
        item["id"]
        for item in REWARD_CATALOG
        if _is_reward_selected(screen, item)
    }


def get_selected_rewards() -> list[str]:
    """从配置读取玩家自选的最多 4 个奖励 id。"""
    raw = _task_opt("selected_rewards", None)
    if not raw:
        raw = DEFAULT_REWARDS
    ids: list[str] = []
    for item in raw:
        rid = str(item).strip()
        rid = _LEGACY_REWARD_MAP.get(rid, rid)
        if rid in REWARD_BY_ID and rid not in ids:
            ids.append(rid)
        if len(ids) >= 4:
            break
    return ids


def reward_display_name(rid: str) -> str:
    if rid in REWARD_LABELS:
        return REWARD_LABELS[rid]
    item = REWARD_BY_ID.get(rid)
    return item["name"] if item else rid


def is_activity_hub(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "activity_title", 0.78):
        return True
    # 标题匹配不到时：顶部有「精彩活动」样式 + 有许愿按钮区域
    if _find(ctx, screen, "wish_tab", 0.75) or _find(ctx, screen, "wish_button", 0.78):
        return True
    return False


def is_wish_select_open(ctx: TaskContext, screen=None) -> bool:
    """「选择奖励」弹层是否打开。"""
    screen = screen if screen is not None else ctx.screenshot()
    # 只用弹层标题确认状态，避免用颜色/绿勾推测导致误判。
    # 活动页本身也有相似背景，实测匹配约 0.63；真实弹层约 0.78+。
    return _find(ctx, screen, "wish_select_title", 0.72) is not None


def open_activity_hub(ctx: TaskContext) -> bool:
    """主城 → 精彩活动。入口可能上下偏移，多点尝试 + 模板。"""
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    if is_activity_hub(ctx):
        return True

    ensure_main_city(ctx)
    dismiss_confirm_dialogs(ctx, max_rounds=1)

    # 1) 模板
    for thr in (0.72, 0.65):
        if ctx.wait_and_tap("activity_entry", retries=1, interval=0.4, threshold=thr):
            time.sleep(1.2)
            if is_activity_hub(ctx):
                return True

    # 2) 左侧多点扫描（应对限时活动把入口挤偏）
    logger.info("精彩活动入口模板未命中，左侧多点尝试…")
    for pt in ACTIVITY_ENTRY_POINTS:
        if is_activity_hub(ctx):
            return True
        if is_main_city(ctx):
            logger.info("点击精彩活动候选 {}", pt)
            _tap(ctx, pt)
            time.sleep(1.1)
            if is_activity_hub(ctx):
                logger.info("已进入精彩活动 @{}", pt)
                return True
            # 误点其它入口则返回再试
            if not is_main_city(ctx) and not is_activity_hub(ctx):
                ui_back(ctx)
                time.sleep(0.6)

    return is_activity_hub(ctx)


def ensure_wish_tab(ctx: TaskContext) -> bool:
    """保证在「每日许愿」子页（活动页顶部第一项）。"""
    if not is_activity_hub(ctx):
        return False
    # 已有底部大「许愿」按钮则多半已在许愿页
    screen = ctx.screenshot()
    if _find(ctx, screen, "wish_button", 0.78):
        return True
    # 点每日许愿 Tab
    hit = _find(ctx, screen, "wish_tab", 0.72)
    if hit:
        logger.info("点击每日许愿 Tab @({},{})", hit.x, hit.y)
        _tap(ctx, (hit.x, hit.y))
    else:
        logger.info("坐标点击每日许愿 Tab {}", WISH_TAB)
        _tap(ctx, WISH_TAB)
    time.sleep(1.0)
    return True


def _click_wish_open(ctx: TaskContext) -> bool:
    """点主页「许愿」打开选择奖励弹层。"""
    logger.info("打开选奖：坐标点击主页「许愿」 {}", WISH_BUTTON)
    _tap(ctx, WISH_BUTTON)
    time.sleep(1.3)
    return is_wish_select_open(ctx)


def _wait_reward_selected(
    ctx: TaskContext,
    reward_id: str,
    expected: bool,
    timeout: float = 2.5,
) -> bool:
    """等待某个奖励格的绿色勾状态变成 expected。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = REWARD_BY_ID[reward_id]
        selected = _is_reward_selected(ctx.screenshot(), item)
        if selected == expected:
            return True
        time.sleep(0.18)
    return _is_reward_selected(ctx.screenshot(), REWARD_BY_ID[reward_id]) == expected


def _sync_selected_rewards(ctx: TaskContext, reward_ids: list[str]) -> bool:
    """把当前弹层选择同步成目标集合，只点击奖励网格中的物品本身。

    已选错误项：点击对应奖励格取消。
    未选目标项：点击对应奖励格加入。
    底部预览只用于展示，不参与清理，避免预览槽移动造成误点。
    """
    target_ids = set(reward_ids)
    screen = ctx.screenshot()
    selected_ids = _selected_reward_ids(screen)
    logger.info(
        "当前已选奖励: {}",
        [reward_display_name(rid) for rid in sorted(selected_ids)],
    )

    # 先取消错误选项。每次点击后重新识别，避免状态动画或漏点时继续盲点。
    wrong_ids = [rid for rid in selected_ids if rid not in target_ids]
    for rid in wrong_ids:
        item = REWARD_BY_ID[rid]
        logger.info("取消错误奖励 {} @({},{})", item["name"], item["x"], item["y"])
        _tap(ctx, (int(item["x"]), int(item["y"])))
        if not _wait_reward_selected(ctx, rid, expected=False):
            logger.warning("取消奖励后仍检测为已选: {}", item["name"])
            return False

    # 再补选目标中尚未选中的项目。
    screen = ctx.screenshot()
    selected_ids = _selected_reward_ids(screen)
    for rid in reward_ids:
        if rid in selected_ids:
            continue
        item = REWARD_BY_ID[rid]
        logger.info("补选目标奖励 {} @({},{})", item["name"], item["x"], item["y"])
        _tap(ctx, (int(item["x"]), int(item["y"])))
        if not _wait_reward_selected(ctx, rid, expected=True):
            logger.warning("补选奖励后未检测到绿色勾: {}", item["name"])
            return False
        selected_ids.add(rid)

    final_ids = _selected_reward_ids(ctx.screenshot())
    if final_ids != target_ids:
        logger.warning(
            "选奖状态不符合目标: 当前={} 目标={}",
            [reward_display_name(rid) for rid in sorted(final_ids)],
            [reward_display_name(rid) for rid in reward_ids],
        )
        return False
    logger.info("选奖状态已确认: {}", [reward_display_name(rid) for rid in reward_ids])
    return True


def _select_rewards(ctx: TaskContext, reward_ids: list[str]) -> bool:
    """同步选奖状态：只取消错误格，再补选缺失目标。"""
    want_list = list(reward_ids[:4])
    if len(want_list) != 4 or any(rid not in REWARD_BY_ID for rid in want_list):
        return False
    names = [REWARD_BY_ID[r]["name"] for r in want_list if r in REWARD_BY_ID]
    logger.info("开始选奖（将选）: {}", names)
    return _sync_selected_rewards(ctx, want_list)


def _confirm_wish(ctx: TaskContext) -> bool:
    """选满后只点一次弹层金色「许愿」。"""
    logger.info("坐标点击弹层「许愿」 {}", WISH_CONFIRM)
    _tap(ctx, WISH_CONFIRM)
    time.sleep(1.5)
    # 只报告结果，不因为失败再次点击，避免重复许愿或继续误点。
    return not is_wish_select_open(ctx)


def _dismiss_reward_popups(ctx: TaskContext) -> None:
    """领奖后点空白关闭。"""
    logger.info("点空白关闭奖励弹层 {}", REWARD_POPUP_DISMISS)
    _tap(ctx, REWARD_POPUP_DISMISS)
    time.sleep(0.7)


def _wait_back_to_wish_page(ctx: TaskContext, timeout: float = 6.0) -> bool:
    """许愿后等选奖弹层关掉，回到精彩活动/许愿页。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_activity_hub(ctx) and not is_wish_select_open(ctx):
            return True
        if is_wish_select_open(ctx):
            # 若还在弹层，可能许愿没点上，交给上层
            time.sleep(0.4)
            continue
        time.sleep(0.4)
    return is_activity_hub(ctx)


def _try_claim_login_chest(ctx: TaskContext) -> bool:
    """连续登录 7/7：在每日许愿页点左侧紫宝箱。"""
    # 确保在活动页且不在选奖弹层
    if is_wish_select_open(ctx):
        _tap(ctx, UI_BACK_FALLBACK)
        time.sleep(0.8)
    if not is_activity_hub(ctx):
        logger.warning("不在精彩活动页，跳过七日宝箱")
        return False

    ensure_wish_tab(ctx)
    time.sleep(0.4)
    logger.info("坐标点击七日登录宝箱 {}", LOGIN_CHEST)
    _tap(ctx, LOGIN_CHEST)

    time.sleep(1.2)
    _dismiss_reward_popups(ctx)
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    logger.info("七日宝箱流程结束")
    return True


def exit_activity_to_main(ctx: TaskContext) -> None:
    """精彩活动 → 返回主城。"""
    for _ in range(6):
        dismiss_confirm_dialogs(ctx, max_rounds=1)
        if is_main_city(ctx):
            logger.info("已回到主城")
            return
        if is_wish_select_open(ctx):
            _tap(ctx, UI_BACK_FALLBACK)
            time.sleep(0.7)
            continue
        if is_activity_hub(ctx):
            ui_back(ctx)
            continue
        ui_back(ctx)
    ensure_main_city(ctx)


class DailyWishTask(BaseTask):
    id = "daily_wish"
    name = "每日许愿"
    description = "精彩活动→自选4奖励→许愿→七日宝箱→回主城"
    required_templates: list[str] = []

    def execute(self, ctx: TaskContext) -> TaskResult:
        logger.info("每日许愿实现版本: {}", DAILY_WISH_IMPL_VERSION)
        dismiss_confirm_dialogs(ctx, max_rounds=2)
        rewards = get_selected_rewards()
        if len(rewards) != 4:
            return TaskResult(
                TaskStatus.FAILED,
                f"请在面板恰好选择 4 个许愿奖励（当前 {len(rewards)} 个）",
            )
        names = [REWARD_BY_ID[r]["name"] for r in rewards if r in REWARD_BY_ID]
        logger.info("今日许愿目标(顺序无关): {}", names)

        if not open_activity_hub(ctx):
            exit_activity_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法打开精彩活动")

        ensure_wish_tab(ctx)
        messages: list[str] = [f"目标:{','.join(names)}"]

        # 1) 打开选择奖励
        if not is_wish_select_open(ctx):
            if not _click_wish_open(ctx):
                logger.warning("未打开选奖弹层，尝试只领宝箱")
                messages.append("未打开选奖(或今日已许愿)")
                if _task_opt("claim_login_chest", True):
                    _try_claim_login_chest(ctx)
                    messages.append("已点七日宝箱")
                exit_activity_to_main(ctx)
                return TaskResult(TaskStatus.SUCCESS, "；".join(messages))

        # 2) 取消错误格 → 补选目标格 → 一次「许愿」
        if not _select_rewards(ctx, rewards):
            exit_activity_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "许愿奖励配置无效")
        time.sleep(0.3)
        final_selected = _selected_reward_ids(ctx.screenshot())
        if final_selected != set(rewards):
            logger.error(
                "提交前选奖状态不安全，停止点击许愿: 当前={} 目标={}",
                [reward_display_name(rid) for rid in sorted(final_selected)],
                [reward_display_name(rid) for rid in rewards],
            )
            exit_activity_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "提交前未确认 4 个目标奖励，已停止操作")
        logger.info("选奖完成，点一次「许愿」")
        if not _confirm_wish(ctx):
            messages.append("许愿确认未完成")
            exit_activity_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "；".join(messages))
        messages.append("已点许愿")

        # 3) 等弹层关闭
        _wait_back_to_wish_page(ctx, timeout=5.0)
        _dismiss_reward_popups(ctx)

        # 4) 七日宝箱（必须在许愿页点紫箱）
        if _task_opt("claim_login_chest", True):
            ok_chest = _try_claim_login_chest(ctx)
            messages.append("已点七日宝箱" if ok_chest else "七日宝箱未确认")

        # 5) 回主城
        exit_activity_to_main(ctx)
        if not is_main_city(ctx):
            ensure_main_city(ctx)

        return TaskResult(TaskStatus.SUCCESS, "每日许愿完成；" + "；".join(messages))
