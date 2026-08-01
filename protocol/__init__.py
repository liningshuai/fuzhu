# -*- coding: utf-8 -*-
"""协议执行层骨架。

当前：mock 实现，不访问真实游戏服。
后续：在 session/ / api/ / crypto/ 中落地真实协议，tasks/ 保持同一接口。
"""

from protocol.registry import PROTOCOL_TASKS, get_protocol_task, list_protocol_tasks
from protocol.runner import run_protocol_task

__all__ = [
    "PROTOCOL_TASKS",
    "get_protocol_task",
    "list_protocol_tasks",
    "run_protocol_task",
]
