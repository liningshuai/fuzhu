"""名士拜访。

流程：主城 -> 商店 -> 名士拜访 -> 找到任意铜钱购买按钮 -> 购买一次 -> 返回主城。

名士拜访每天刷新一组不同的将领碎片，购买货币可能是元宝或铜钱。
本任务只寻找购买按钮上的铜钱图标，因此不会误买元宝商品。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from loguru import logger

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_main_city,
    ui_back,
)


SHOP_FALLBACK = (805, 1835)
SHOP_TAB_FALLBACK = (950, 495)
SHOP_BACK_FALLBACK = (72, 240)

# 1080x1920 竖屏中，名士拜访商品固定为两列四行；只在价格按钮区域搜索，
# 避免把顶部资源栏的铜钱图标识别成购买按钮。
BUY_BUTTON_REGIONS = (
    (250, 890, 300, 130),
    (760, 890, 300, 130),
    (250, 1150, 300, 130),
    (760, 1150, 300, 130),
    (250, 1410, 300, 130),
    (760, 1410, 300, 130),
    (250, 1670, 300, 130),
    (760, 1670, 300, 130),
)


def _today() -> str:
    return date.today().isoformat()


def _task_meta() -> dict[str, Any]:
    return (config.get("tasks") or {}).get("mingshi") or {}


def _task_opt(key: str, default: Any) -> Any:
    return _task_meta().get(key, default)


def _find(
    ctx: TaskContext,
    screen,
    name: str,
    threshold: float = 0.75,
    region=None,
):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold, region=region)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, point: tuple[int, int]) -> None:
    ctx.device.tap(int(point[0]), int(point[1]), jitter=False)


def _wait(ctx: TaskContext, predicate, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate(ctx):
            return True
        time.sleep(0.35)
    return predicate(ctx)


def is_shop_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find(
        ctx,
        screen,
        "shop_title",
        threshold=0.70,
        region=(380, 180, 360, 160),
    ) is not None


def is_mingshi_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find(
        ctx,
        screen,
        "mingshi_refresh",
        threshold=0.70,
        region=(0, 600, 520, 190),
    ) is not None


def open_shop(ctx: TaskContext) -> bool:
    if is_shop_page(ctx) or is_mingshi_page(ctx):
        return True
    if not ensure_main_city(ctx):
        return False

    screen = ctx.screenshot()
    hit = _find(
        ctx,
        screen,
        "nav_shop",
        threshold=0.68,
        region=(700, 1710, 300, 210),
    )
    point = (hit.x, hit.y) if hit else SHOP_FALLBACK
    logger.info("打开商店 @({}, {})", point[0], point[1])
    _tap(ctx, point)
    return _wait(ctx, is_shop_page, timeout=7.0)


def open_mingshi(ctx: TaskContext) -> bool:
    if is_mingshi_page(ctx):
        return True
    if not open_shop(ctx):
        logger.warning("无法打开商店")
        return False

    screen = ctx.screenshot()
    hit = _find(
        ctx,
        screen,
        "shop_mingshi_tab",
        threshold=0.68,
        region=(820, 350, 260, 300),
    )
    point = (hit.x, hit.y) if hit else SHOP_TAB_FALLBACK
    logger.info("打开名士拜访 @({}, {})", point[0], point[1])
    _tap(ctx, point)
    return _wait(ctx, is_mingshi_page, timeout=7.0)


def _find_coin_purchase(ctx: TaskContext, screen=None):
    """按商品从上到下、从左到右寻找铜钱购买按钮。"""
    screen = screen if screen is not None else ctx.screenshot()
    for region in BUY_BUTTON_REGIONS:
        hit = _find(
            ctx,
            screen,
            "mingshi_coin_icon",
            threshold=0.72,
            region=region,
        )
        if hit:
            logger.info(
                "找到铜钱购买按钮 @({}, {}) score={:.3f} region={}",
                hit.x,
                hit.y,
                hit.score,
                region,
            )
            return hit
    return None


def _purchase_once(ctx: TaskContext) -> bool:
    if not is_mingshi_page(ctx):
        return False
    before = ctx.screenshot()
    hit = _find_coin_purchase(ctx, before)
    if not hit:
        logger.warning("名士拜访当前没有可识别的铜钱购买按钮")
        return False

    logger.info("点击铜钱将领碎片购买一次 @({}, {})", hit.x, hit.y)
    _tap(ctx, (hit.x, hit.y))
    time.sleep(1.1)

    # 当前客户端购买后仍停留在名士拜访页；若出现通用确认弹窗，只关闭确认，
    # 不点击商品区域之外的未知位置。
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    if not _wait(ctx, is_mingshi_page, timeout=3.5):
        logger.warning("点击铜钱购买按钮后未回到名士拜访页面")
        return False
    return True


def _save_completed() -> None:
    config.set_task_option("mingshi", "last_purchase_date", _today())
    config.set_task_option("mingshi", "completed_today", True)
    config.save_runtime()


def _completed_today() -> bool:
    return (
        str(_task_opt("last_purchase_date", "") or "") == _today()
        and bool(_task_opt("completed_today", False))
    )


def _leave_to_main(ctx: TaskContext) -> bool:
    for _ in range(4):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return True
        dismiss_confirm_dialogs(ctx, max_rounds=1)
        _tap(ctx, SHOP_BACK_FALLBACK)
        time.sleep(0.9)
        if is_main_city(ctx):
            return True
        # 兼容部分客户端返回箭头位置变化的情况。
        ui_back(ctx)
    return ensure_main_city(ctx)


class MingshiTask(BaseTask):
    id = "mingshi"
    name = "名士拜访"
    description = "主城→商店→名士拜访→购买一次铜钱将领碎片→返回主城"
    required_templates = [
        "nav_fief",
        "nav_shop",
        "shop_title",
        "shop_mingshi_tab",
        "mingshi_refresh",
        "mingshi_coin_icon",
        "ui_back",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        if _completed_today():
            return TaskResult(TaskStatus.SKIPPED, "今日名士拜访已完成")

        if not open_mingshi(ctx):
            _leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法进入名士拜访界面")

        if not _purchase_once(ctx):
            _leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "未能购买铜钱将领碎片")

        _save_completed()
        returned = _leave_to_main(ctx)
        if not returned:
            return TaskResult(TaskStatus.FAILED, "购买成功但未能返回主城")
        return TaskResult(TaskStatus.SUCCESS, "名士拜访完成：已购买一次铜钱将领碎片")
