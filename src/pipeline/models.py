"""Pipeline 配置的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RecognizerType = Literal["template", "ocr"]
ActionType = Literal[
    "none",
    "tap_self",
    "tap",
    "back",
    "swipe",
    "wait",
    "success",
    "fail",
]


@dataclass(frozen=True)
class RecognizerSpec:
    type: RecognizerType
    template: str | None = None
    text: str | None = None
    roi: tuple[int, int, int, int] | None = None
    threshold: float = 0.82


@dataclass(frozen=True)
class ActionSpec:
    type: ActionType
    point: tuple[int, int] | None = None
    rect: tuple[int, int, int, int] | None = None
    from_point: tuple[int, int] | None = None
    to_point: tuple[int, int] | None = None
    duration_ms: int = 400
    seconds: float = 0.0


@dataclass(frozen=True)
class PipelineNode:
    id: str
    recognize: RecognizerSpec | None
    action: ActionSpec
    next: tuple[str, ...] = ()
    error_next: tuple[str, ...] = ()
    max_times: int = 1
    delay: float = 0.0


@dataclass(frozen=True)
class PipelineDefinition:
    id: str
    start: str
    coordinate_base: tuple[int, int]
    nodes: dict[str, PipelineNode]
