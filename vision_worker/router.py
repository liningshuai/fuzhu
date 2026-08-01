# -*- coding: utf-8 -*-
"""按 RoleTaskConfig.impl 与任务目录能力选择 protocol / vision。"""
from __future__ import annotations

from common.models import (
    ExecRoute,
    RoleContext,
    RoleTaskConfig,
    TaskImpl,
    TaskKey,
    TaskResult,
    TaskStatusCode,
)
from common.registry_meta import get_task_meta
from protocol.runner import run_protocol_task
from vision_worker.runner import run_vision_task, vision_task_available


def resolve_route(task_key: TaskKey, cfg: RoleTaskConfig | None = None) -> ExecRoute:
    """决定实际执行通道。

    - protocol / vision：强制
    - auto：优先真实可用的识图（已就绪），否则协议（含 mock）
    """
    impl = (cfg.impl if cfg else TaskImpl.AUTO) or TaskImpl.AUTO
    meta = get_task_meta(task_key)

    if impl == TaskImpl.PROTOCOL:
        return ExecRoute.PROTOCOL
    if impl == TaskImpl.VISION:
        return ExecRoute.VISION

    # auto
    if meta.vision_ready and vision_task_available(task_key):
        return ExecRoute.VISION
    if meta.protocol_ready:
        return ExecRoute.PROTOCOL
    if vision_task_available(task_key):
        return ExecRoute.VISION
    return ExecRoute.PROTOCOL


def channel_display(route: ExecRoute, *, vision_ready: bool, protocol_ready: bool) -> str:
    """Web 展示用通道文案。"""
    if route == ExecRoute.VISION:
        return "本地识图执行" if vision_ready else "不可用"
    if route == ExecRoute.PROTOCOL:
        return "协议模拟（mock，不会操作游戏）" if protocol_ready else "不可用"
    return "不可用"


def run_task(
    task_key: TaskKey,
    ctx: RoleContext,
    cfg: RoleTaskConfig | None = None,
    *,
    force_route: ExecRoute | None = None,
) -> TaskResult:
    route = force_route or resolve_route(task_key, cfg)
    if route == ExecRoute.VISION:
        if not vision_task_available(task_key):
            return TaskResult.fail(
                TaskStatusCode.UNSUPPORTED,
                f"识图通道不可用: {task_key.value}",
                task_key=task_key,
                route=ExecRoute.VISION,
                events=[f"vision 不可用: {task_key.value}"],
            )
        return run_vision_task(task_key, ctx)
    result = run_protocol_task(task_key, ctx)
    # 明确标记 mock，避免 UI 误判
    if result.extras is not None and "mock" not in result.extras:
        result.extras = {**result.extras, "mock": True}
    if not result.events:
        result.events = [f"protocol mock 执行: {task_key.value}"]
    return result
