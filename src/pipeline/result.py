"""Pipeline 执行结果和步骤轨迹。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PipelineStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NOT_READY = "not_ready"
    STEP_LIMIT = "step_limit"


@dataclass(frozen=True)
class PipelineTrace:
    node_id: str
    recognition_type: str | None
    score: float | None
    point: tuple[int, int] | None
    action_type: str
    elapsed_ms: int
    error: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    status: PipelineStatus
    message: str
    trace: tuple[PipelineTrace, ...]
