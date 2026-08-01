# -*- coding: utf-8 -*-
"""识图执行 Worker：把 common.TaskKey 映射到 tasks/*.yaml 并返回 TaskResult。"""

from vision_worker.runner import run_vision_task, vision_task_available
from vision_worker.router import resolve_route, run_task

__all__ = [
    "run_vision_task",
    "vision_task_available",
    "resolve_route",
    "run_task",
]
