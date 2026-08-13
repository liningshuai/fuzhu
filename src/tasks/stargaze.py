"""夜观星象：只使用免费「星晷」完成每日观星。"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Literal

from loguru import logger

from src.config import config
from src.session.activity_popup import ActivityPopupDetector
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    UI_BACK_FALLBACK,
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_main_city,
)


FIEF_FALLBACK = (80, 1820)
WORLD_FALLBACK = (80, 1820)
ACADEMY_SWIPES = 4
# 书院位于封地左侧：手指从左向右拖动，才能把左侧区域带入视野。
ACADEMY_SWIPE = (300, 960, 800, 960, 450)
WAIT_POLLS = 18
WAIT_INTERVAL = 0.25
MAX_REWARD_TAPS = 8
MAX_OBSERVATIONS = 3
PAID_ITEM_THRESHOLD = 0.80
SAFE_BLANK = (30, 500)

ACADEMY_REGION = (120, 260, 700, 900)
FREE_MARKER_REGION = (100, 240, 800, 850)
STARGAZE_DIALOG_REGION = (0, 160, 1080, 1650)
FREE_ITEM_REGION = (100, 1250, 430, 450)
PAID_ITEM_REGION = (600, 1250, 430, 450)


def _today() -> str:
    return date.today().isoformat()


def _task_meta() -> dict[str, Any]:
    return (config.get("tasks") or {}).get("stargaze") or {}


def _task_opt(key: str, default: Any) -> Any:
    return _task_meta().get(key, default)


def _find(
    ctx: TaskContext,
    screen: Any,
    name: str,
    threshold: float = 0.78,
    region: tuple[int, int, int, int] | None = None,
):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold, region=region)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, point: tuple[int, int]) -> None:
    ctx.device.tap(int(point[0]), int(point[1]), jitter=False)


def _wait_for(ctx: TaskContext, predicate, polls: int = WAIT_POLLS) -> bool:
    for _ in range(max(1, polls)):
        if predicate(ctx):
            return True
        time.sleep(WAIT_INTERVAL)
    return bool(predicate(ctx))


def is_stargaze_dialog(ctx: TaskContext, screen: Any = None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find(
        ctx,
        screen,
        "stargaze_title",
        threshold=0.82,
        region=STARGAZE_DIALOG_REGION,
    ) is not None


def open_fief(ctx: TaskContext) -> bool:
    """主城进入封地；只使用一次明确的封地入口点击。"""
    if not ensure_main_city(ctx):
        return False

    screen = ctx.screenshot()
    hit = _find(ctx, screen, "nav_fief", threshold=0.80)
    point = hit.center if hit is not None else FIEF_FALLBACK
    logger.info("打开封地 @({}, {})", point[0], point[1])
    _tap(ctx, point)
    time.sleep(0.8)
    return not is_main_city(ctx)


def find_and_open_academy(ctx: TaskContext) -> bool:
    """有限次向左滑动，找到带免费道具入口的书院后进入观星页。"""
    for attempt in range(ACADEMY_SWIPES + 1):
        screen = ctx.screenshot()
        academy = _find(
            ctx,
            screen,
            "stargaze_academy",
            threshold=0.82,
            region=ACADEMY_REGION,
        )
        marker = _find(
            ctx,
            screen,
            "stargaze_free_marker",
            threshold=0.84,
            region=FREE_MARKER_REGION,
        )
        if academy is not None and marker is not None:
            logger.info(
                "找到带免费观星入口的书院 attempt={} marker=({}, {}) score={:.3f}",
                attempt,
                marker.x,
                marker.y,
                marker.score,
            )
            _tap(ctx, marker.center)
            if _wait_for(ctx, is_stargaze_dialog):
                return True
            logger.warning("点击书院观星入口后未进入观星弹窗")
            return False

        if attempt >= ACADEMY_SWIPES:
            break
        logger.debug("未找到免费观星书院，执行第 {} 次有限滑动", attempt + 1)
        ctx.device.swipe(*ACADEMY_SWIPE)
        time.sleep(0.6)
    return False


def _observe_once(ctx: TaskContext) -> Literal["free", "paid", "unknown"]:
    """判断当前观星按钮状态；免费命中优先于付费命中。"""
    screen = ctx.screenshot()
    if not is_stargaze_dialog(ctx, screen):
        return "unknown"

    free = _find(
        ctx,
        screen,
        "stargaze_free_item",
        threshold=0.84,
        region=FREE_ITEM_REGION,
    )
    if free is not None:
        logger.info("识别到免费星晷，允许观星 @({}, {}) score={:.3f}", free.x, free.y, free.score)
        _tap(ctx, free.center)
        return "free"

    paid = _find(
        ctx,
        screen,
        "stargaze_paid_observe",
        threshold=PAID_ITEM_THRESHOLD,
        region=PAID_ITEM_REGION,
    )
    if paid is not None:
        logger.info("免费星晷已用尽，识别到元宝入口，停止且不点击")
        return "paid"

    logger.warning("观星弹窗既未识别到免费星晷，也未识别到元宝入口，安全停止")
    return "unknown"


def _is_reward_popup(ctx: TaskContext, screen: Any) -> bool:
    # 该模板是可选的：用户尚未提供奖励弹窗截图，因此不能把它列为
    # required_templates。若现场已有专用模板，优先使用专用模板。
    if _find(ctx, screen, "stargaze_reward_popup", threshold=0.82) is not None:
        return True

    # 观星奖励通常复用项目已有的「点击任意区域关闭」提示；先检查奖励态
    # 专用提示，再兼容普通提示，仍然只返回识别结果，不在这里点击。
    for name in (
        "startup_highlight_close_hint_reward",
        "startup_highlight_close_hint",
    ):
        if _find(ctx, screen, name, threshold=0.78) is not None:
            return True

    # 复用已有安全活动弹窗识别；识别不到时禁止盲点。
    try:
        return ActivityPopupDetector(ctx.matcher).detect(screen) is not None
    except Exception:  # noqa: BLE001
        return False


def _dismiss_reward_popup(ctx: TaskContext) -> bool:
    for _ in range(MAX_REWARD_TAPS):
        screen = ctx.screenshot()
        if _is_reward_popup(ctx, screen):
            _tap(ctx, SAFE_BLANK)
            # 每次点击后重新截图，确认奖励层已经消失，避免连续盲点
            # 或在奖励尚未关闭时进入下一轮观星。
            for _ in range(3):
                after = ctx.screenshot()
                if not _is_reward_popup(ctx, after):
                    time.sleep(0.35)
                    return True
                time.sleep(0.25)
            return False
        time.sleep(WAIT_INTERVAL)
    return False


def _close_stargaze(ctx: TaskContext) -> bool:
    screen = ctx.screenshot()
    hit = _find(ctx, screen, "stargaze_close", threshold=0.84, region=(0, 150, 180, 180))
    if hit is not None:
        _tap(ctx, hit.center)
    else:
        _tap(ctx, UI_BACK_FALLBACK)
    return _wait_for(ctx, lambda c: not is_stargaze_dialog(c))


def _leave_to_main(ctx: TaskContext) -> bool:
    """有限次关闭观星页并点击封地左下角世界返回主城。"""
    for _ in range(4):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return True

        dismiss_confirm_dialogs(ctx, max_rounds=1)
        if is_stargaze_dialog(ctx):
            _close_stargaze(ctx)
            continue

        screen = ctx.screenshot()
        world = _find(ctx, screen, "nav_world", threshold=0.80)
        _tap(ctx, world.center if world is not None else WORLD_FALLBACK)
        time.sleep(0.8)
        if is_main_city(ctx):
            return True
    return ensure_main_city(ctx, retries=2)


def _completed_today() -> bool:
    return (
        str(_task_opt("last_completed_date", "") or "") == _today()
        and bool(_task_opt("completed_today", False))
    )


def _save_completed() -> None:
    config.set_task_option("stargaze", "last_completed_date", _today())
    config.set_task_option("stargaze", "completed_today", True)
    config.save_runtime()


class StargazeTask(BaseTask):
    id = "stargaze"
    name = "夜观星象"
    description = "封地→书院→免费星晷观星，最多三次后返回主城"
    required_templates = [
        "nav_fief",
        "nav_world",
        "stargaze_academy",
        "stargaze_free_marker",
        "stargaze_title",
        "stargaze_free_item",
        "stargaze_paid_observe",
        "stargaze_close",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        if _completed_today():
            return TaskResult(TaskStatus.SKIPPED, "今日夜观星象已完成")

        try:
            max_observations = int(_task_opt("max_free_observations", MAX_OBSERVATIONS) or MAX_OBSERVATIONS)
        except (TypeError, ValueError):
            max_observations = MAX_OBSERVATIONS
        max_observations = max(1, min(MAX_OBSERVATIONS, max_observations))

        if not open_fief(ctx):
            _leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法进入封地")

        if not find_and_open_academy(ctx):
            returned = _leave_to_main(ctx)
            if returned:
                return TaskResult(TaskStatus.SKIPPED, "未发现免费星晷入口")
            return TaskResult(TaskStatus.FAILED, "未发现免费星晷入口且无法回主城")

        completed = 0
        stop_reason = "max_free_observations"
        for _ in range(max_observations):
            state = _observe_once(ctx)
            if state == "free":
                if not _dismiss_reward_popup(ctx):
                    _leave_to_main(ctx)
                    return TaskResult(TaskStatus.FAILED, "观星奖励弹窗未能安全识别")
                completed += 1
                continue
            if state == "paid":
                stop_reason = "paid_observe_detected"
                break

            _leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "观星状态无法安全识别")

        returned = _leave_to_main(ctx)
        if not returned:
            return TaskResult(TaskStatus.FAILED, "观星完成但未能回到主城")
        if completed == 0:
            return TaskResult(TaskStatus.SKIPPED, "今日没有可用的免费星晷")

        _save_completed()
        message = f"夜观星象完成：免费观星 {completed}/{max_observations} 次"
        if stop_reason == "paid_observe_detected":
            message += "；已识别元宝抽取，未消费元宝"
        return TaskResult(
            TaskStatus.SUCCESS,
            message,
            data={"observed_count": completed, "stop_reason": stop_reason},
        )
