"""挂机引擎：循环执行已启用任务。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from src.adb.device import AdbDevice
from src.config import config
from src.session.recovery import (
    GameSessionGuard,
    GameSessionRecoveryError,
    GameSessionRestarted,
)
from src.session.startup import GameStartupFlow
from src.tasks.base import TaskContext, TaskResult, TaskStatus
from src.tasks.registry import create_task, list_task_meta
from src.vision.match import TemplateMatcher


@dataclass
class BotState:
    running: bool = False
    started_at: Optional[str] = None
    last_loop_at: Optional[str] = None
    loop_count: int = 0
    last_message: str = "未启动"
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    device_online: bool = False
    game_foreground: bool = False


class BotEngine:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.state = BotState()
        self._lock = threading.Lock()
        self._starting = False
        self.device = AdbDevice()
        self.matcher = TemplateMatcher()
        self.session_guard = GameSessionGuard(self.device, self.matcher)

    def refresh_device(self) -> None:
        self.device = AdbDevice(
            adb_path=config.get("device", "adb_path"),
            serial=config.get("device", "serial"),
        )
        self.matcher = TemplateMatcher()
        self.session_guard.device = self.device
        self.session_guard.matcher = self.matcher

    def _new_task_context(self, previous: TaskContext | None = None) -> TaskContext:
        state = previous.state if previous is not None else {}
        return TaskContext(
            device=self.device,
            matcher=self.matcher,
            state=state,
            session_guard=self.session_guard,
        )

    def _stop_for_session_recovery(self, result: TaskResult) -> None:
        self._stop.set()
        with self._lock:
            self.state.last_message = result.message or "游戏会话恢复失败，已停止挂机"

    def _run_task_with_recovery(
        self,
        task_id: str,
        task: Any,
        ctx: TaskContext,
    ) -> TaskResult:
        while True:
            result = task.run(ctx)
            if result.data.get("session_recovered"):
                logger.warning("[{}] 会话已恢复，刷新设备上下文并重试当前任务", task_id)
                self.refresh_device()
                ctx = self._new_task_context(ctx)
                continue
            if result.data.get("session_recovery_exhausted"):
                logger.error("[{}] 会话恢复失败或达到上限，停止挂机", task_id)
                self._stop_for_session_recovery(result)
            return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            online = False
            foreground = False
            try:
                online = self.device.is_online()
                if online:
                    foreground = self.device.is_game_foreground()
            except Exception:  # noqa: BLE001
                online = False
            self.state.device_online = online
            self.state.game_foreground = foreground
            return {
                "running": self.state.running,
                "started_at": self.state.started_at,
                "last_loop_at": self.state.last_loop_at,
                "loop_count": self.state.loop_count,
                "last_message": self.state.last_message,
                "recent_results": list(self.state.recent_results[-30:]),
                "device_online": online,
                "game_foreground": foreground,
                "serial": self.device.serial,
                "tasks": list_task_meta(),
            }

    def start(self, ensure_game: bool = True) -> str:
        with self._lock:
            if self.state.running:
                return "已经在挂机中"
            if self._thread is not None and self._thread.is_alive():
                return "上一轮挂机线程仍在停止中"
            if self._starting:
                return "正在启动中"
            self._starting = True
            self._stop.clear()
            self.state.last_message = "正在启动游戏..."

        try:
            self.refresh_device()
            self.session_guard = GameSessionGuard(self.device, self.matcher)
            if not self.device.is_online():
                message = f"设备离线: {self.device.serial}，请检查雷电模拟器与 ADB"
                with self._lock:
                    self.state.last_message = message
                return message
            if ensure_game and not self.device.is_game_foreground():
                try:
                    self.device.start_game()
                except Exception as exc:  # noqa: BLE001
                    message = f"启动游戏失败: {exc}"
                    with self._lock:
                        self.state.last_message = message
                    return message
            try:
                GameStartupFlow(self.device, self.matcher).wait_until_main_city()
            except Exception as exc:  # noqa: BLE001
                message = f"启动游戏失败: {exc}"
                with self._lock:
                    self.state.last_message = message
                logger.error(message)
                return message

            with self._lock:
                if self._stop.is_set():
                    self.state.last_message = "已取消启动"
                    return "已取消启动"
                self.state = BotState(
                    running=True,
                    started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_message="挂机已启动",
                )
                self._thread = threading.Thread(
                    target=self._loop,
                    name="bot-loop",
                    daemon=True,
                )
                thread = self._thread
                # 在锁内提交线程启动，避免 stop() 先看到 running=True 并返回，
                # 随后启动线程才真正开始运行的竞态窗口。
                thread.start()
            logger.info("挂机引擎启动")
            return "挂机已启动"
        finally:
            with self._lock:
                self._starting = False

    def stop(self) -> str:
        with self._lock:
            if self._starting and not self.state.running:
                self._stop.set()
                self.state.last_message = "正在取消启动..."
                return "正在取消启动"
            if not self.state.running:
                return "当前未在挂机"
            self._stop.set()
            self.state.running = False
            self.state.last_message = "正在停止..."
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=8)
        with self._lock:
            self.state.last_message = "已停止挂机"
            if self._thread is thread and thread is not None and not thread.is_alive():
                self._thread = None
        logger.info("挂机引擎已停止")
        return "已停止挂机"

    def _append_result(self, task_id: str, name: str, result: TaskResult) -> None:
        item = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "task_id": task_id,
            "name": name,
            "status": result.status.value,
            "message": result.message,
        }
        # 挂机循环会反复执行已完成任务；连续相同结果只保留一条，避免
        # 「今日已完成」每隔几秒刷满面板日志。不同状态或不同消息仍会记录。
        def same_result(previous: dict[str, Any]) -> bool:
            return (
                previous.get("task_id") == item["task_id"]
                and previous.get("name") == item["name"]
                and previous.get("status") == item["status"]
                and previous.get("message") == item["message"]
            )

        if self.state.recent_results and same_result(self.state.recent_results[-1]):
            # 兼容本次修复前已经堆积的连续重复项，保留最早的一条。
            while (
                len(self.state.recent_results) > 1
                and same_result(self.state.recent_results[-2])
            ):
                self.state.recent_results.pop()
            return
        self.state.recent_results.append(item)
        if len(self.state.recent_results) > 100:
            self.state.recent_results = self.state.recent_results[-100:]

    def _loop(self) -> None:
        interval = float(config.get("bot", "loop_interval") or 3)
        while not self._stop.is_set():
            try:
                self._one_round()
            except Exception as exc:  # noqa: BLE001
                logger.exception("挂机循环异常")
                with self._lock:
                    self.state.last_message = f"循环异常: {exc}"
            # 可中断 sleep
            self._stop.wait(interval)
        with self._lock:
            self.state.running = False

    def _one_round(self) -> None:
        config.reload()
        self.refresh_device()
        if not self.device.is_online():
            with self._lock:
                self.state.last_message = "设备离线，等待重连..."
                self.state.device_online = False
            return

        ctx = self._new_task_context()
        # 全局：国家公告/系统「确定」弹窗可能在任意任务前弹出
        try:
            from src.tasks.navigation import dismiss_confirm_dialogs

            dismiss_confirm_dialogs(ctx, max_rounds=3)
        except GameSessionRestarted:
            self.refresh_device()
            ctx = self._new_task_context(ctx)
        except GameSessionRecoveryError as exc:
            self._stop_for_session_recovery(
                TaskResult(
                    TaskStatus.FAILED,
                    str(exc),
                    data={"session_recovery_exhausted": True},
                )
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("清理确定弹窗时忽略: {}", exc)

        task_ids = list((config.get("tasks") or {}).keys())
        ran_any = False
        for task_id in task_ids:
            if self._stop.is_set():
                break
            meta = (config.get("tasks") or {}).get(task_id) or {}
            if not meta.get("enabled"):
                continue
            # 每个任务开始前再清一次，避免上一轮或战斗中弹出的公告卡住
            while True:
                try:
                    from src.tasks.navigation import dismiss_confirm_dialogs

                    dismiss_confirm_dialogs(ctx, max_rounds=2)
                    break
                except GameSessionRestarted:
                    self.refresh_device()
                    ctx = self._new_task_context(ctx)
                except GameSessionRecoveryError as exc:
                    self._stop_for_session_recovery(
                        TaskResult(
                            TaskStatus.FAILED,
                            str(exc),
                            data={"session_recovery_exhausted": True},
                        )
                    )
                    return
                except Exception:  # noqa: BLE001
                    break
            task = create_task(task_id)
            result = self._run_task_with_recovery(task_id, task, ctx)
            with self._lock:
                self._append_result(task_id, task.name, result)
                if result.status != TaskStatus.SKIPPED:
                    ran_any = True
                    self.state.last_message = f"{task.name}: {result.message or result.status.value}"
            if self._stop.is_set():
                break

        with self._lock:
            self.state.loop_count += 1
            self.state.last_loop_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not ran_any:
                self.state.last_message = "本轮无已启用且可执行任务（检查开关/模板）"


# 全局单例，供 Web 与 CLI 共用
engine = BotEngine()
