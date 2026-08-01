# -*- coding: utf-8 -*-
"""协议任务入口：编排 / API 只依赖这一层。"""
from __future__ import annotations

from common.models import ExecRoute, RoleContext, TaskKey, TaskResult, TaskStatusCode
from protocol.registry import get_protocol_task


def run_protocol_task(task_key: TaskKey, ctx: RoleContext) -> TaskResult:
    task = get_protocol_task(task_key)
    if task is None:
        return TaskResult.fail(
            TaskStatusCode.UNSUPPORTED,
            f"协议未实现任务: {task_key.value}",
            task_key=task_key,
            route=ExecRoute.PROTOCOL,
        )
    result = task.run(ctx)
    if result.task_key is None:
        result.task_key = task_key
    if result.route is None:
        result.route = ExecRoute.PROTOCOL
    return result
