# -*- coding: utf-8 -*-
"""任务目录：Web 开关列表的权威来源。"""
from __future__ import annotations

from typing import Dict, List

from common.models import TaskKey, TaskMeta

TASK_CATALOG: Dict[TaskKey, TaskMeta] = {
    TaskKey.MAIL: TaskMeta(
        key=TaskKey.MAIL,
        name="自动领邮件",
        description="更多 → 邮件 → 一键阅读 → 关闭（需验证离开邮件界面）",
        category="基础类",
        default_interval_minutes=120,
        protocol_ready=True,  # mock only
        vision_ready=True,
    ),
    TaskKey.ZHENGWU: TaskMeta(
        key=TaskKey.ZHENGWU,
        name="自动政务",
        description="任务 → 政务 → 接受任务 → 返回（需验证结束条件）",
        category="基础类",
        default_interval_minutes=30,
        protocol_ready=True,  # mock only
        vision_ready=True,
    ),
    TaskKey.YIGUAN: TaskMeta(
        key=TaskKey.YIGUAN,
        name="自动驿馆",
        description="封地 → 驿馆（开发中）",
        category="基础类",
        default_interval_minutes=60,
        protocol_ready=True,  # mock only
        vision_ready=False,
    ),
}


def get_task_meta(key: TaskKey) -> TaskMeta:
    return TASK_CATALOG[key]


def list_task_meta() -> List[TaskMeta]:
    return list(TASK_CATALOG.values())
