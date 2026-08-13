"""比武大会报名。

流程：
  主城 -> 征战 -> 武馆 -> 比武大会
       -> 若冠军「点赞」按钮高亮则点赞
       -> 若「报名」按钮高亮则报名
       -> 确认报名成功 -> 返回主城

按钮是否可用通过高亮/金色区域判断。任务只在按钮可用时点击，避免在
比赛尚未开放、已经报名或今日流程已完成时重复操作。
"""

from __future__ import annotations

import time
from datetime import date
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
    open_war_list,
    ui_back,
)


WUGUAN_TAB = (460, 331)
BIWU_ENTRY = (552, 909)
CHAMPION_LIKE = (762, 817)
SIGNUP = (552, 1669)

# 只检查按钮本体，不能把冠军头像/卡片背景的金色算作按钮高亮。
# 区域与高亮模板 arena_champion_like / arena_signup 对齐。
LIKE_REGION = (626, 766, 273, 103)
SIGNUP_REGION = (383, 1621, 339, 96)


def _today() -> str:
    return date.today().isoformat()


def _task_meta() -> dict[str, Any]:
    return (config.get("tasks") or {}).get("heroes_arena") or {}


def _task_opt(key: str, default: Any) -> Any:
    return _task_meta().get(key, default)


def _find(ctx: TaskContext, screen, name: str, threshold: float = 0.75, region=None):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold, region=region)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, xy: tuple[int, int]) -> None:
    ctx.device.tap(int(xy[0]), int(xy[1]), jitter=False)


def is_war_hall(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find(ctx, screen, "war_title", 0.72) is not None


def is_wuguan_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    # 征战页本身也有「武馆」Tab，不能把 Tab 的存在当成已进入武馆。
    return _find(
        ctx,
        screen,
        "arena_entry_biwudahui",
        0.62,
        region=(80, 700, 920, 500),
    ) is not None


def is_biwu_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "arena_title", 0.65, region=(250, 150, 600, 180)):
        return True
    return _find(ctx, screen, "arena_tournament_title", 0.65, region=(100, 350, 900, 250)) is not None


def _gold_ratio(screen: np.ndarray, region: tuple[int, int, int, int]) -> float:
    x, y, w, h = region
    roi = screen[y : y + h, x : x + w]
    if roi.size == 0:
        return 0.0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gold = (
        (hsv[:, :, 0] >= 8)
        & (hsv[:, :, 0] <= 42)
        & (hsv[:, :, 1] >= 70)
        & (hsv[:, :, 2] >= 100)
    )
    return float(gold.mean())


def _is_button_highlighted(screen: np.ndarray, region: tuple[int, int, int, int]) -> bool:
    return _gold_ratio(screen, region) >= 0.10


def _find_like(ctx: TaskContext, screen):
    return _find(ctx, screen, "arena_champion_like", 0.60, region=LIKE_REGION)


def _find_signup(ctx: TaskContext, screen):
    return _find(ctx, screen, "arena_signup", 0.60, region=SIGNUP_REGION)


def is_like_highlighted(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    hit = _find_like(ctx, screen)
    if not hit:
        return False
    return _is_button_highlighted(screen, LIKE_REGION)


def is_signup_highlighted(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    hit = _find_signup(ctx, screen)
    if not hit:
        return False
    return _is_button_highlighted(screen, SIGNUP_REGION)


def _wait_page(ctx: TaskContext, predicate, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate(ctx):
            return True
        time.sleep(0.4)
    return predicate(ctx)


def open_wuguan(ctx: TaskContext) -> bool:
    if is_wuguan_page(ctx):
        return True
    if not open_war_list(ctx):
        return False

    hit = _find(ctx, ctx.screenshot(), "arena_wuguan_tab", 0.62, region=(180, 220, 700, 230))
    _tap(ctx, (hit.x, hit.y) if hit else WUGUAN_TAB)
    return _wait_page(ctx, is_wuguan_page, timeout=8.0)


def open_biwu(ctx: TaskContext) -> bool:
    if is_biwu_page(ctx):
        return True
    if not open_wuguan(ctx):
        return False

    hit = _find(
        ctx,
        ctx.screenshot(),
        "arena_entry_biwudahui",
        0.62,
        region=(80, 700, 920, 500),
    )
    _tap(ctx, (hit.x, hit.y) if hit else BIWU_ENTRY)
    return _wait_page(ctx, is_biwu_page, timeout=8.0)


def _save_completed() -> None:
    config.set_task_option("heroes_arena", "last_completed_date", _today())
    config.save_runtime()


def _completed_today() -> bool:
    return str(_task_opt("last_completed_date", "") or "") == _today()


def _wait_signup_result(ctx: TaskContext, before: np.ndarray, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        screen = ctx.screenshot()
        if not is_biwu_page(ctx, screen):
            return True
        # 报名成功可能先弹出通用确认提示；只在点击报名后的等待窗口内处理。
        confirm = _find(ctx, screen, "dialog_confirm", 0.72, region=(250, 800, 650, 600))
        if confirm and 850 <= confirm.y <= 1400:
            logger.info("检测到报名结果提示，点击确定@({},{})", confirm.x, confirm.y)
            _tap(ctx, (confirm.x, confirm.y))
            time.sleep(0.7)
            return True
        # 报名后按钮通常变灰/不可用；按钮模板消失也视为成功信号。
        if _find_signup(ctx, screen) is None:
            return True
        if not is_signup_highlighted(ctx, screen):
            return True
        time.sleep(0.3)
    return not is_signup_highlighted(ctx)


def leave_to_main(ctx: TaskContext) -> None:
    for _ in range(6):
        dismiss_confirm_dialogs(ctx, max_rounds=1)
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return
        if is_biwu_page(ctx, screen) or is_wuguan_page(ctx, screen) or is_war_hall(ctx, screen):
            ui_back(ctx)
            continue
        _tap(ctx, UI_BACK_FALLBACK)
        time.sleep(0.8)
    ensure_main_city(ctx)


class HeroesArenaTask(BaseTask):
    id = "heroes_arena"
    name = "比武大会"
    description = "征战→武馆→比武大会→冠军点赞→报名"
    required_templates = [
        "nav_war",
        "war_title",
        "arena_wuguan_tab",
        "arena_entry_biwudahui",
        "arena_title",
        "arena_tournament_title",
        "arena_champion_like",
        "arena_signup",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        dismiss_confirm_dialogs(ctx, max_rounds=2)
        if _completed_today():
            return TaskResult(TaskStatus.SUCCESS, "今日比武大会已完成")

        if not open_biwu(ctx):
            leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法进入比武大会")

        screen = ctx.screenshot()
        liked = False
        like_hit = _find_like(ctx, screen)
        if like_hit and is_like_highlighted(ctx, screen):
            logger.info("冠军点赞按钮高亮，点击点赞@({},{})", like_hit.x, like_hit.y)
            before = screen
            _tap(ctx, (like_hit.x, like_hit.y))
            time.sleep(0.8)
            liked = not is_like_highlighted(ctx)
        else:
            logger.info("冠军点赞按钮未高亮，跳过点赞")

        screen = ctx.screenshot()
        signup_hit = _find_signup(ctx, screen)
        if not signup_hit or not is_signup_highlighted(ctx, screen):
            leave_to_main(ctx)
            return TaskResult(
                TaskStatus.SKIPPED,
                "报名按钮未高亮，等待下一轮重试" + ("；冠军点赞已处理" if liked else ""),
            )

        logger.info("报名按钮高亮，点击报名@({},{})", signup_hit.x, signup_hit.y)
        before = screen
        _tap(ctx, (signup_hit.x, signup_hit.y))
        if not _wait_signup_result(ctx, before):
            leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "已点击报名但未确认报名成功")

        _save_completed()
        leave_to_main(ctx)
        return TaskResult(TaskStatus.SUCCESS, "比武大会报名成功" + ("，已点赞冠军" if liked else ""))
