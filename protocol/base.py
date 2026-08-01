# -*- coding: utf-8 -*-
"""协议任务统一接口。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from common.models import RoleContext, TaskKey, TaskResult


@runtime_checkable
class ProtocolTask(Protocol):
    """所有协议任务实现此接口。"""

    key: TaskKey

    def run(self, ctx: RoleContext) -> TaskResult:
        ...
