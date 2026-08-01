# -*- coding: utf-8 -*-
"""跨执行链共享契约。"""

from common.models import (
    ChannelLabel,
    DeviceTarget,
    ExecRoute,
    Job,
    JobEvent,
    JobStatus,
    RoleContext,
    RoleTaskConfig,
    RoleTaskState,
    TaskImpl,
    TaskJob,
    TaskKey,
    TaskMeta,
    TaskResult,
    TaskStatusCode,
)
from common.registry_meta import TASK_CATALOG, get_task_meta, list_task_meta

__all__ = [
    "ChannelLabel",
    "DeviceTarget",
    "ExecRoute",
    "Job",
    "JobEvent",
    "JobStatus",
    "RoleContext",
    "RoleTaskConfig",
    "RoleTaskState",
    "TaskImpl",
    "TaskJob",
    "TaskKey",
    "TaskMeta",
    "TaskResult",
    "TaskStatusCode",
    "TASK_CATALOG",
    "get_task_meta",
    "list_task_meta",
]
