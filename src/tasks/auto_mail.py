"""自动领邮件。

路径：主城 → 更多 → 邮件 → 一键阅读 → 点空白关闭 → 回主城

模板（assets/templates/）：
  - nav_fief / btn_more / more_title / btn_mail_icon
  - mail_title / mail_read_all_tight / mail_close（可选）
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    ensure_main_city,
    is_mail_open,
    open_mail,
    tap_blank,
)


def _button_looks_claimable(screen: np.ndarray, match) -> bool:
    """粗略判断「一键阅读」是否偏黄（有可领奖励时常高亮）。

    灰按钮也可点击；此函数仅用于日志说明。
    """
    half_w, half_h = match.w // 2, match.h // 2
    x1 = max(0, match.x - half_w)
    y1 = max(0, match.y - half_h)
    x2 = min(screen.shape[1], match.x + half_w)
    y2 = min(screen.shape[0], match.y + half_h)
    roi = screen[y1:y2, x1:x2]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # 黄色/金色大致范围
    lower = np.array([15, 60, 80])
    upper = np.array([40, 255, 255])
    mask = cv2.inRange(hsv, lower, upper)
    ratio = float(mask.mean()) / 255.0
    return ratio > 0.08


class AutoMailTask(BaseTask):
    id = "auto_mail"
    name = "自动领邮件"
    description = "主城→更多→邮件→一键阅读"
    required_templates = [
        "nav_fief",
        "btn_more",
        "more_title",
        "btn_mail_icon",
        "mail_title",
        "mail_read_all_tight",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        from src.tasks.navigation import CLOSE_POINTS

        # 1. 尽量回到主城（失败也继续尝试打开，坐标路径可自救）
        ensure_main_city(ctx)

        # 2. 打开邮件
        if not open_mail(ctx):
            ensure_main_city(ctx)
            # 邮件入口可能因更多弹窗动画或网络加载暂时未确认；此时不把
            # 已完成过的邮件领取误报成硬失败，下一轮继续尝试。
            return TaskResult(TaskStatus.SKIPPED, "邮件入口暂未确认，等待下一轮重试")

        time.sleep(0.5)
        screen = ctx.screenshot()
        btn = ctx.matcher.find(screen, "mail_read_all_tight", threshold=0.72)
        if btn is None:
            btn = ctx.matcher.find(screen, "mail_read_all", threshold=0.72)

        if btn is None:
            # 坐标兜底：一键阅读在面板底部中央
            logger.warning("未匹配到一键阅读模板，使用坐标 (540,1580)")
            btn_x, btn_y = 540, 1580
            claimable = False
        else:
            btn_x, btn_y = btn.x, btn.y
            claimable = _button_looks_claimable(screen, btn)
            logger.info(
                "一键阅读 @({},{}) score={:.2f} 高亮/可领≈{}",
                btn.x,
                btn.y,
                btn.score,
                claimable,
            )

        # 3. 点击一键阅读（灰/黄都点）
        ctx.device.tap(btn_x, btn_y)
        time.sleep(1.4)

        # 4. 奖励弹窗 / 邮件界面：侧边点击关闭
        for pt in CLOSE_POINTS[:3]:
            tap_blank(ctx, pt)
            time.sleep(0.55)
            if not is_mail_open(ctx):
                break

        # 5. 确认回主城
        ensure_main_city(ctx)
        msg = "一键阅读完成（检测到高亮，可能有奖励）" if claimable else "一键阅读完成"
        return TaskResult(TaskStatus.SUCCESS, msg)
