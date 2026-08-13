"""任务基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger

from src.adb.device import AdbDevice
from src.session.recovery import (
    GameSessionGuard,
    GameSessionRecoveryError,
    GameSessionRestarted,
)
from src.vision.match import TemplateMatcher


class TaskStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    NOT_READY = "not_ready"  # 模板/界面未就绪


@dataclass
class TaskResult:
    status: TaskStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    device: AdbDevice
    matcher: TemplateMatcher
    # 本轮循环共享状态
    state: dict[str, Any] = field(default_factory=dict)
    session_guard: GameSessionGuard | None = None
    _task_active: bool = field(default=False, init=False, repr=False)
    _popup_cleanup_active: bool = field(default=False, init=False, repr=False)

    def screenshot(self):
        screen = self.device.screenshot()
        if self.session_guard is not None:
            self.session_guard.check(screen)

        # Command-order overlays can appear after a task has already started.
        # Keep this hook narrow and re-entrant-safe: it only handles the three
        # safe-to-skip command pages and never owns task purchase/reward dialogs.
        if self._task_active and not self._popup_cleanup_active:
            self._popup_cleanup_active = True
            try:
                from src.tasks.navigation import dismiss_command_order_popups

                if dismiss_command_order_popups(self, max_rounds=1, screen=screen):
                    screen = self.device.screenshot()
                    if self.session_guard is not None:
                        self.session_guard.check(screen)
            except (GameSessionRestarted, GameSessionRecoveryError):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("任务中命令弹窗清理失败: {}", exc)
            finally:
                self._popup_cleanup_active = False
        return screen

    def tap_template(
        self,
        name: str,
        threshold: Optional[float] = None,
        region=None,
    ) -> bool:
        screen = self.screenshot()
        match = self.matcher.find(screen, name, threshold=threshold, region=region)
        if not match:
            return False
        self.device.tap(match.x, match.y)
        return True

    def wait_and_tap(
        self,
        name: str,
        retries: int = 5,
        interval: float = 1.0,
        threshold: Optional[float] = None,
    ) -> bool:
        import time

        for _ in range(retries):
            if self.tap_template(name, threshold=threshold):
                return True
            time.sleep(interval)
        return False

    def exists(self, name: str, threshold: Optional[float] = None) -> bool:
        try:
            screen = self.screenshot()
            return self.matcher.find(screen, name, threshold=threshold) is not None
        except FileNotFoundError:
            return False


class BaseTask(ABC):
    """所有自动化任务继承此类。"""

    id: str = "base"
    name: str = "基础任务"
    description: str = ""
    # 需要的模板文件名（不含路径），用于启动前检查
    required_templates: list[str] = []

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def can_run(self, ctx: TaskContext) -> tuple[bool, str]:
        missing = []
        for t in self.required_templates:
            try:
                ctx.matcher._load(t)
            except FileNotFoundError:
                missing.append(t)
        if missing:
            return False, f"缺少模板: {', '.join(missing)}"
        return True, ""

    def run(self, ctx: TaskContext) -> TaskResult:
        if not self.enabled:
            return TaskResult(TaskStatus.SKIPPED, "未启用")
        ok, reason = self.can_run(ctx)
        if not ok:
            logger.warning("[{}] 无法执行: {}", self.id, reason)
            return TaskResult(TaskStatus.NOT_READY, reason)
        try:
            # 全局：国家公告 / 系统「确定」弹窗可能随时挡住任意任务
            try:
                from src.tasks.navigation import dismiss_confirm_dialogs

                dismiss_confirm_dialogs(ctx, max_rounds=2)
            except (GameSessionRestarted, GameSessionRecoveryError):
                raise
            except Exception:  # noqa: BLE001
                pass
            logger.info("[{}] 开始执行: {}", self.id, self.name)
            ctx._task_active = True
            try:
                result = self.execute(ctx)
            finally:
                ctx._task_active = False
            logger.info("[{}] 结束: {} - {}", self.id, result.status, result.message)
            return result
        except GameSessionRestarted as exc:
            logger.warning("[{}] 会话已恢复，交由引擎重试当前任务: {}", self.id, exc)
            return TaskResult(
                TaskStatus.FAILED,
                str(exc),
                data={"session_recovered": True},
            )
        except GameSessionRecoveryError as exc:
            logger.error("[{}] 会话恢复达到上限或失败，停止挂机: {}", self.id, exc)
            return TaskResult(
                TaskStatus.FAILED,
                str(exc),
                data={"session_recovery_exhausted": True},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[{}] 异常", self.id)
            return TaskResult(TaskStatus.FAILED, str(exc))

    @abstractmethod
    def execute(self, ctx: TaskContext) -> TaskResult:
        raise NotImplementedError
