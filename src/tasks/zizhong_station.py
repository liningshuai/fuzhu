"""辎重站免费购买。

流程：
  主城 -> 封地 -> 辎重站（优先上方图标，失败后点建筑）
       -> 按配置选择资源 -> 同一资源最多购买 3 次免费次数
       -> 左上返回封地 -> 底部「世界」回主城

四张资源卡显示的免费次数属于同一个共享次数池，因此本任务只记录当天
已经成功执行的总次数，不把四张卡当成各自 3 次。任务完成日期和次数写入
runtime 配置，避免挂机循环在同一天重复购买。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import numpy as np
from loguru import logger

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    NAV_FIEF_FALLBACK,
    UI_BACK_FALLBACK,
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_main_city,
    ui_back,
)


MAX_FREE_PURCHASES = 3

# 1080x1920 截图基准。按钮中心由用户提供的辎重站页面标定。
RESOURCE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "coin",
        "name": "铜钱",
        "buy_region": (0, 820, 540, 360),
        "state_region": (0, 820, 540, 120),
        "fallback": (280, 990),
    },
    {
        "id": "food",
        "name": "粮草",
        "buy_region": (540, 820, 540, 360),
        "state_region": (540, 820, 540, 120),
        "fallback": (805, 990),
    },
    {
        "id": "wood",
        "name": "木材",
        "buy_region": (0, 1560, 540, 360),
        "state_region": (0, 1560, 540, 120),
        "fallback": (280, 1749),
    },
    {
        "id": "iron",
        "name": "生铁",
        "buy_region": (540, 1560, 540, 360),
        "state_region": (540, 1560, 540, 120),
        "fallback": (805, 1749),
    },
]
RESOURCE_BY_ID = {item["id"]: item for item in RESOURCE_CATALOG}

# 封地页面：辎重站上方图标、对应建筑、底部世界按钮。
FIEF_ENTRY_POINTS = (
    (197, 485),
    (235, 612),
)
WORLD_FALLBACK = NAV_FIEF_FALLBACK


def _today() -> str:
    return date.today().isoformat()


def _task_meta() -> dict[str, Any]:
    return (config.get("tasks") or {}).get("zizhong_station") or {}


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


def _tap(ctx: TaskContext, xy: tuple[int, int]) -> None:
    # 关键按钮按截图坐标点击，不使用随机抖动，避免点到相邻资源卡。
    ctx.device.tap(int(xy[0]), int(xy[1]), jitter=False)


def is_fief_page(ctx: TaskContext, screen=None) -> bool:
    """识别封地页：底栏显示「世界」或地图上的辎重站入口。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "nav_world", threshold=0.68, region=(0, 1640, 230, 280)):
        return True
    if _find(ctx, screen, "zizhong_entry_icon", threshold=0.68, region=(40, 250, 430, 700)):
        return True
    return _find(
        ctx,
        screen,
        "zizhong_entry_building",
        threshold=0.62,
        region=(40, 350, 430, 760),
    ) is not None


def is_zizhong_page(ctx: TaskContext, screen=None) -> bool:
    """识别辎重站购买页。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "zizhong_title", threshold=0.64, region=(250, 170, 580, 190)):
        return True
    return _find(ctx, screen, "zizhong_free_buy", threshold=0.72) is not None


def open_fief(ctx: TaskContext) -> bool:
    """主城 -> 封地。"""
    if is_fief_page(ctx):
        return True
    if not ensure_main_city(ctx):
        return False

    screen = ctx.screenshot()
    hit = _find(ctx, screen, "nav_fief", threshold=0.72, region=(0, 1660, 230, 260))
    if hit:
        logger.info("点击底栏「封地」@({},{})", hit.x, hit.y)
        _tap(ctx, (hit.x, hit.y))
    else:
        logger.info("坐标点击底栏「封地」{}", NAV_FIEF_FALLBACK)
        _tap(ctx, NAV_FIEF_FALLBACK)
    time.sleep(1.2)
    return is_fief_page(ctx)


def open_zizhong(ctx: TaskContext) -> bool:
    """封地 -> 辎重站，优先图标，随后建筑和坐标兜底。"""
    if is_zizhong_page(ctx):
        return True
    if not open_fief(ctx):
        logger.error("无法打开封地")
        return False

    for name, threshold, region, label in (
        (
            "zizhong_entry_icon",
            0.68,
            (40, 250, 430, 700),
            "辎重站上方图标",
        ),
        (
            "zizhong_entry_building",
            0.62,
            (40, 350, 430, 760),
            "辎重站建筑",
        ),
    ):
        hit = _find(ctx, ctx.screenshot(), name, threshold=threshold, region=region)
        if not hit:
            continue
        logger.info("点击{}@({},{})", label, hit.x, hit.y)
        _tap(ctx, (hit.x, hit.y))
        time.sleep(1.1)
        if is_zizhong_page(ctx):
            return True

    for point in FIEF_ENTRY_POINTS:
        logger.info("坐标尝试进入辎重站 {}", point)
        _tap(ctx, point)
        time.sleep(1.0)
        if is_zizhong_page(ctx):
            return True
    return False


def _selected_resource() -> dict[str, Any]:
    resource_id = str(_task_opt("resource", "food") or "food").strip()
    return RESOURCE_BY_ID.get(resource_id, RESOURCE_BY_ID["food"])


def _purchased_today() -> int:
    if _task_opt("last_purchase_date", "") != _today():
        return 0
    try:
        return max(0, min(MAX_FREE_PURCHASES, int(_task_opt("purchased_count", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _save_purchase_progress(count: int) -> None:
    config.set_task_option("zizhong_station", "last_purchase_date", _today())
    config.set_task_option("zizhong_station", "purchased_count", count)
    config.save_runtime()


def _find_free_buy(ctx: TaskContext, resource: dict[str, Any]):
    return _find(
        ctx,
        ctx.screenshot(),
        "zizhong_free_buy",
        threshold=0.72,
        region=resource["buy_region"],
    )


def _purchase_state_changed(
    before: np.ndarray,
    after: np.ndarray,
    resource: dict[str, Any],
) -> bool:
    """判断资源卡免费次数/数值区域是否在点击后发生变化。"""
    x, y, w, h = resource["state_region"]
    old = before[y : y + h, x : x + w]
    new = after[y : y + h, x : x + w]
    if old.shape != new.shape or old.size == 0:
        return False
    delta = np.abs(new.astype(np.int16) - old.astype(np.int16))
    changed = np.any(delta >= 12, axis=2)
    return float(changed.mean()) >= 0.003


def _wait_purchase_state_change(
    ctx: TaskContext,
    before: np.ndarray,
    resource: dict[str, Any],
    timeout: float = 2.5,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        after = ctx.screenshot()
        if _purchase_state_changed(before, after, resource):
            return True
        time.sleep(0.18)
    return _purchase_state_changed(before, ctx.screenshot(), resource)


def _dismiss_purchase_result_dialog(ctx: TaskContext) -> bool:
    """关闭购买成功后的结果确认弹窗。

    辎重站购买后弹窗的「确定」通常位于 (x≈803, y≈1004)，低于通用
    弹窗处理使用的 y 范围。只在辎重站购买流程的局部区域查找，避免
    把资源卡按钮误当成系统弹窗。
    """
    screen = ctx.screenshot()
    for threshold in (0.76, 0.70):
        hit = _find(
            ctx,
            screen,
            "dialog_confirm",
            threshold=threshold,
            region=(500, 760, 580, 520),
        )
        if hit and hit.x >= 650 and 850 <= hit.y <= 1250:
            logger.info("检测到辎重站购买结果弹窗，点击确定@({},{})", hit.x, hit.y)
            _tap(ctx, (hit.x, hit.y))
            time.sleep(0.7)
            return True
    return False


def _wait_purchase_success(
    ctx: TaskContext,
    before: np.ndarray,
    resource: dict[str, Any],
    timeout: float = 5.0,
) -> bool:
    """确认一次购买成功：资源卡变化或出现购买结果弹窗均算成功。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _dismiss_purchase_result_dialog(ctx):
            return True
        after = ctx.screenshot()
        if _purchase_state_changed(before, after, resource):
            # 有些设备先刷新资源卡，再弹结果确认；弹窗存在时顺手关掉。
            _dismiss_purchase_result_dialog(ctx)
            return True
        time.sleep(0.18)

    # 最后一轮再处理一次延迟弹窗，覆盖网络/动画较慢的情况。
    if _dismiss_purchase_result_dialog(ctx):
        return True
    return _purchase_state_changed(before, ctx.screenshot(), resource)


def buy_free_resource(ctx: TaskContext, resource: dict[str, Any], already: int) -> int:
    """购买当天剩余免费次数，只允许点击「免费购买」。"""
    count = already
    while count < MAX_FREE_PURCHASES:
        before = ctx.screenshot()
        hit = _find(
            ctx,
            before,
            "zizhong_free_buy",
            threshold=0.72,
            region=resource["buy_region"],
        )
        if not hit:
            logger.info("{}卡未识别到「免费购买」，停止以避免误买", resource["name"])
            break

        logger.info(
            "购买{}第 {}/{} 次，点击「免费购买」@({},{})",
            resource["name"],
            count + 1,
            MAX_FREE_PURCHASES,
            hit.x,
            hit.y,
        )
        _tap(ctx, (hit.x, hit.y))
        if not _wait_purchase_success(ctx, before, resource):
            logger.warning("点击购买后未确认成功，停止后续点击")
            break

        count += 1
        _save_purchase_progress(count)

    return count


def leave_zizhong_to_main(ctx: TaskContext) -> None:
    """辎重站 -> 封地 -> 世界 -> 主城。"""
    for _ in range(6):
        dismiss_confirm_dialogs(ctx, max_rounds=1)
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return
        if is_zizhong_page(ctx, screen):
            logger.info("点击辎重站左上角返回")
            # 辎重站页只点一次专用返回区域，避免通用 ui_back 在返回后再次误点。
            hit = _find(
                ctx,
                screen,
                "zizhong_ui_back",
                threshold=0.64,
                region=(0, 150, 230, 230),
            )
            _tap(ctx, (hit.x, hit.y) if hit else UI_BACK_FALLBACK)
            time.sleep(1.0)
            continue
        if is_fief_page(ctx, screen):
            hit = _find(ctx, screen, "nav_world", threshold=0.68, region=(0, 1640, 230, 280))
            point = (hit.x, hit.y) if hit else WORLD_FALLBACK
            logger.info("点击封地底部「世界」{}", point)
            _tap(ctx, point)
            time.sleep(1.2)
            continue
        # 发生加载遮挡或状态识别失败时，先使用左上返回回退一层。
        _tap(ctx, UI_BACK_FALLBACK)
        time.sleep(0.8)
    ensure_main_city(ctx)


class ZizhongStationTask(BaseTask):
    id = "zizhong_station"
    name = "辎重站"
    description = "封地→辎重站→指定资源免费购买3次→返回世界"
    required_templates: list[str] = []

    def execute(self, ctx: TaskContext) -> TaskResult:
        dismiss_confirm_dialogs(ctx, max_rounds=2)
        resource = _selected_resource()
        already = _purchased_today()

        if already >= MAX_FREE_PURCHASES:
            logger.info("今日辎重站免费购买已完成，跳过重复执行")
            if not is_main_city(ctx):
                leave_zizhong_to_main(ctx)
            return TaskResult(TaskStatus.SUCCESS, "今日辎重站免费购买已完成")

        if not open_zizhong(ctx):
            leave_zizhong_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法打开辎重站")

        purchased = buy_free_resource(ctx, resource, already)
        leave_zizhong_to_main(ctx)

        if purchased >= MAX_FREE_PURCHASES:
            return TaskResult(
                TaskStatus.SUCCESS,
                f"辎重站已完成{resource['name']}免费购买{MAX_FREE_PURCHASES}次",
            )
        if purchased > already:
            return TaskResult(
                TaskStatus.FAILED,
                f"辎重站仅完成{resource['name']}免费购买{purchased}/{MAX_FREE_PURCHASES}次",
            )
        return TaskResult(TaskStatus.FAILED, "未识别到辎重站免费购买按钮")
