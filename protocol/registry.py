# -*- coding: utf-8 -*-
"""协议任务注册表。"""
from __future__ import annotations

from typing import Dict, List

from common.models import TaskKey
from protocol.base import ProtocolTask
from protocol.tasks.mail import MailProtocolTask
from protocol.tasks.yiguan import YiguanProtocolTask
from protocol.tasks.zhengwu import ZhengwuProtocolTask

PROTOCOL_TASKS: Dict[TaskKey, ProtocolTask] = {
    TaskKey.MAIL: MailProtocolTask(),
    TaskKey.ZHENGWU: ZhengwuProtocolTask(),
    TaskKey.YIGUAN: YiguanProtocolTask(),
}


def get_protocol_task(key: TaskKey) -> ProtocolTask | None:
    return PROTOCOL_TASKS.get(key)


def list_protocol_tasks() -> List[TaskKey]:
    return list(PROTOCOL_TASKS.keys())
