"""游戏会话被挤下线后的检测、限频和恢复。"""

from __future__ import annotations

from collections import deque
import time
from typing import Any, Callable

from loguru import logger

from src.session.startup import GameStartupFlow


class GameSessionRestarted(RuntimeError):
    """游戏已重启并回到主城，当前任务应从头重试。"""


class GameSessionRecoveryError(RuntimeError):
    """游戏会话恢复失败或已达到重启上限。"""


class GameSessionGuard:
    DUPLICATE_LOGIN_REGION = (100, 650, 880, 850)
    DUPLICATE_LOGIN_TEMPLATES = (
        ("duplicate_login_message", 0.78),
        ("duplicate_login_confirm", 0.78),
    )

    def __init__(
        self,
        device: Any,
        matcher: Any,
        *,
        max_restarts: int = 2,
        window_seconds: float = 600.0,
        startup_timeout: float = 45.0,
        poll_interval: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_restarts < 1:
            raise ValueError("max_restarts 必须大于等于 1")
        if window_seconds <= 0 or startup_timeout <= 0 or poll_interval < 0:
            raise ValueError("恢复时间参数无效")
        self.device = device
        self.matcher = matcher
        self.max_restarts = max_restarts
        self.window_seconds = float(window_seconds)
        self.startup_timeout = float(startup_timeout)
        self.poll_interval = float(poll_interval)
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self._restart_times: deque[float] = deque()

    def _prune_restart_times(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._restart_times and self._restart_times[0] <= cutoff:
            self._restart_times.popleft()

    def is_duplicate_login(self, screen: Any) -> bool:
        """只用专用模板判断重复登录弹窗，模板缺失时安全返回 False。"""
        for name, threshold in self.DUPLICATE_LOGIN_TEMPLATES:
            try:
                if self.matcher.find(
                    screen,
                    name,
                    threshold=threshold,
                    region=self.DUPLICATE_LOGIN_REGION,
                ) is not None:
                    return True
            except FileNotFoundError:
                logger.debug("重复登录模板不存在，跳过 {}", name)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.debug("检查重复登录模板 {} 失败: {}", name, exc)
        return False

    def check(self, screen: Any) -> None:
        if not self.is_duplicate_login(screen):
            return

        now = self.monotonic_fn()
        self._prune_restart_times(now)
        if len(self._restart_times) >= self.max_restarts:
            raise GameSessionRecoveryError(
                f"重复登录持续存在，{self.window_seconds:g} 秒内已自动重启 "
                f"{self.max_restarts} 次"
            )

        self._restart_times.append(now)
        logger.warning(
            "检测到重复登录弹窗，开始第 {}/{} 次自动恢复",
            len(self._restart_times),
            self.max_restarts,
        )
        self._restart_game_and_wait_for_main_city()
        raise GameSessionRestarted("游戏已重启并回到主城，准备重试当前任务")

    def _restart_game_and_wait_for_main_city(self) -> None:
        try:
            self.device.stop_game()
            self.sleep_fn(0.5)
            self.device.start_game()
        except Exception as exc:  # noqa: BLE001
            raise GameSessionRecoveryError(f"重启游戏失败: {exc}") from exc

        try:
            startup = GameStartupFlow(
                self.device,
                self.matcher,
                timeout_seconds=self.startup_timeout,
                poll_interval=self.poll_interval,
            )
            # 保留会话守卫的可控时钟，离线回放不会真的等待。
            startup.sleep_fn = self.sleep_fn
            startup.monotonic_fn = self.monotonic_fn
            startup.wait_until_main_city()
        except GameSessionRecoveryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GameSessionRecoveryError(
                f"游戏重启后进入主城失败: {exc}"
            ) from exc

        logger.info("游戏重启后已确认回到主城")
