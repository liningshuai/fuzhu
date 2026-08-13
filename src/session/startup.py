"""游戏启动后收敛到主城的状态流程。"""

from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger

from .activity_popup import ActivityPopupDetector


STARTUP_REGION = (0, 0, 1080, 1920)
HIGHLIGHT_CLOSE_POINT = (30, 500)


class GameStartupTimeout(RuntimeError):
    """在限定时间内未能进入主城。"""


class GameStartupFlow:
    """处理启动页、登录页和启动后弹窗，直到主城可识别。"""

    TEMPLATE_ACTIONS = (
        ("startup_announcement_claim", "公告页", "match"),
        ("startup_enter_game", "登录页", "match"),
        ("startup_permanent_claim", "永久卡奖励", "match"),
        ("startup_highlight_close_hint_reward", "奖励高亮弹窗", "blank"),
        ("startup_highlight_close_hint", "高亮弹窗", "blank"),
    )

    def __init__(
        self,
        device: Any,
        matcher: Any,
        *,
        timeout_seconds: float = 60.0,
        poll_interval: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        activity_detector: ActivityPopupDetector | None = None,
        max_activity_dismissals: int = 8,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval < 0:
            raise ValueError("启动流程时间参数无效")
        if max_activity_dismissals < 0:
            raise ValueError("活动弹窗关闭上限无效")
        self.device = device
        self.matcher = matcher
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval = float(poll_interval)
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.activity_detector = (
            activity_detector
            if activity_detector is not None
            else ActivityPopupDetector(matcher)
        )
        self.max_activity_dismissals = int(max_activity_dismissals)

    def _find(self, screen: Any, name: str, threshold: float = 0.78):
        try:
            return self.matcher.find(
                screen,
                name,
                threshold=threshold,
                region=STARTUP_REGION,
            )
        except FileNotFoundError:
            logger.debug("启动流程模板不存在，跳过 {}", name)
            return None

    def _handle_one_action(self, screen: Any) -> bool:
        for name, label, action in self.TEMPLATE_ACTIONS:
            hit = self._find(screen, name)
            if hit is None:
                continue
            if action == "match":
                self.device.tap(hit.x, hit.y)
                logger.info("启动流程处理{} @({}, {})", label, hit.x, hit.y)
            else:
                self.device.tap(*HIGHLIGHT_CLOSE_POINT)
                logger.info("启动流程关闭{}", label)
            return True
        return False

    def _device_ready(self) -> bool:
        """启动后先确认设备在线且游戏在前台（测试替身可不提供这些方法）。"""
        for method_name in ("is_online", "is_game_foreground"):
            method = getattr(self.device, method_name, None)
            if method is None:
                continue
            try:
                if not method():
                    return False
            except Exception as exc:  # noqa: BLE001
                logger.debug("启动流程检查设备状态失败 {}: {}", method_name, exc)
                return False
        return True

    def wait_until_main_city(self) -> None:
        deadline = self.monotonic_fn() + self.timeout_seconds
        activity_dismissals = 0
        while self.monotonic_fn() <= deadline:
            if not self._device_ready():
                self.sleep_fn(self.poll_interval)
                continue
            screen = self.device.screenshot()
            if self._handle_one_action(screen):
                continue

            activity_match = self.activity_detector.detect(screen)
            if activity_match is not None:
                if activity_dismissals >= self.max_activity_dismissals:
                    raise GameStartupTimeout(
                        "启动后活动弹窗关闭次数达到上限 "
                        f"{self.max_activity_dismissals}；"
                        f"last_activity_source={activity_match.source}；"
                        f"last_activity_reason={activity_match.reason}"
                    )
                self.device.tap(*HIGHLIGHT_CLOSE_POINT)
                activity_dismissals += 1
                logger.info(
                    "启动流程关闭活动弹窗 source={} reason={} score={:.3f} count={}/{}",
                    activity_match.source,
                    activity_match.reason,
                    activity_match.confidence,
                    activity_dismissals,
                    self.max_activity_dismissals,
                )
                continue

            if self._find(screen, "nav_fief") is not None:
                logger.info("启动流程已确认回到主城")
                return

            self.sleep_fn(self.poll_interval)

        raise GameStartupTimeout(
            f"启动后未能在 {self.timeout_seconds:g} 秒内进入主城"
        )
