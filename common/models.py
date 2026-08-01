# -*- coding: utf-8 -*-
"""领域模型：任务键、Job 状态机、设备、执行结果。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskKey(str, Enum):
    """与 Web 开关、协议 mock、识图 yaml 对齐的稳定任务键。"""

    MAIL = "mail"
    ZHENGWU = "zhengwu"
    YIGUAN = "yiguan"


class TaskStatusCode(str, Enum):
    """业务结果码（与 Job 状态配合使用）。"""

    OK = "OK"
    NEED_RELOGIN = "NEED_RELOGIN"
    RISK = "RISK"
    TEMP_FAIL = "TEMP_FAIL"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"
    INVALID_CONFIG = "INVALID_CONFIG"
    BLOCKED = "BLOCKED"
    BUSY = "BUSY"


class TaskImpl(str, Enum):
    AUTO = "auto"
    PROTOCOL = "protocol"  # Phase1 仅 mock
    VISION = "vision"


class ExecRoute(str, Enum):
    PROTOCOL = "protocol"  # mock，不操作游戏
    VISION = "vision"  # 本地识图，操作模拟器


class JobStatus(str, Enum):
    """统一 Job 状态机。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    @classmethod
    def terminal(cls) -> set:
        return {cls.SUCCEEDED, cls.FAILED, cls.CANCELLED, cls.BLOCKED}


class ChannelLabel(str, Enum):
    """Web 展示用通道文案键。"""

    VISION = "vision_local"
    PROTOCOL_MOCK = "protocol_mock"
    UNAVAILABLE = "unavailable"


class TaskResult(BaseModel):
    """执行链返回结构。"""

    ok: bool
    code: TaskStatusCode = TaskStatusCode.OK
    message: str = ""
    task_key: Optional[TaskKey] = None
    route: Optional[ExecRoute] = None
    extras: Dict[str, Any] = Field(default_factory=dict)
    events: List[str] = Field(default_factory=list)
    screenshot_paths: List[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    def finish(self) -> "TaskResult":
        self.finished_at = utc_now()
        if self.started_at:
            delta = self.finished_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)
        return self

    def add_event(self, msg: str) -> None:
        self.events.append(msg)

    @classmethod
    def success(
        cls,
        message: str = "ok",
        *,
        task_key: Optional[TaskKey] = None,
        route: Optional[ExecRoute] = None,
        extras: Optional[Dict[str, Any]] = None,
        events: Optional[List[str]] = None,
        screenshot_paths: Optional[List[str]] = None,
    ) -> "TaskResult":
        return cls(
            ok=True,
            code=TaskStatusCode.OK,
            message=message,
            task_key=task_key,
            route=route,
            extras=extras or {},
            events=events or [],
            screenshot_paths=screenshot_paths or [],
        ).finish()

    @classmethod
    def fail(
        cls,
        code: TaskStatusCode,
        message: str,
        *,
        task_key: Optional[TaskKey] = None,
        route: Optional[ExecRoute] = None,
        extras: Optional[Dict[str, Any]] = None,
        events: Optional[List[str]] = None,
        screenshot_paths: Optional[List[str]] = None,
    ) -> "TaskResult":
        return cls(
            ok=False,
            code=code,
            message=message,
            task_key=task_key,
            route=route,
            extras=extras or {},
            events=events or [],
            screenshot_paths=screenshot_paths or [],
        ).finish()


class TaskMeta(BaseModel):
    key: TaskKey
    name: str
    description: str = ""
    category: str = "基础类"
    default_interval_minutes: int = 60
    protocol_ready: bool = False  # mock 是否注册
    vision_ready: bool = False


class DeviceTarget(BaseModel):
    """本阶段仅支持单设备。"""

    device_id: str
    adb_serial: str
    name: str = "本地雷电"
    created_at: datetime = Field(default_factory=utc_now)


class RoleContext(BaseModel):
    role_id: str
    role_name: str = ""
    server_id: str = ""
    server_name: str = ""
    device_id: Optional[str] = None  # 未绑定则 Vision 为 blocked
    # 禁止在 API/日志中输出 session 秘密；mock 仅内存/库内占位
    session: Dict[str, Any] = Field(default_factory=dict)
    params: Dict[str, Any] = Field(default_factory=dict)


class RoleTaskConfig(BaseModel):
    task_key: TaskKey
    enabled: bool = False
    interval_minutes: int = 60
    impl: TaskImpl = TaskImpl.AUTO
    params: Dict[str, Any] = Field(default_factory=dict)


class RoleTaskState(BaseModel):
    task_key: TaskKey
    last_run_at: Optional[datetime] = None
    last_status: Optional[TaskStatusCode] = None
    last_message: str = ""
    last_route: Optional[ExecRoute] = None
    last_job_id: Optional[str] = None
    last_job_status: Optional[JobStatus] = None
    last_extras: Dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    role_id: str
    device_id: Optional[str] = None
    task_key: TaskKey
    route: ExecRoute
    status: JobStatus = JobStatus.QUEUED
    message: str = ""
    result_code: Optional[TaskStatusCode] = None
    extras: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class JobEvent(BaseModel):
    id: Optional[int] = None
    job_id: str
    ts: datetime = Field(default_factory=utc_now)
    level: str = "info"  # info / warn / error
    message: str
    screenshot_path: Optional[str] = None


class TaskJob(BaseModel):
    """兼容旧名：调度消息。"""

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    role_id: str
    task_key: TaskKey
    route: ExecRoute = ExecRoute.PROTOCOL
    attempt: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    params: Dict[str, Any] = Field(default_factory=dict)
