"""Pipeline 动作执行器。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from src.pipeline.models import ActionSpec
from src.pipeline.recognizers import Recognition


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str = ""
    terminal: str | None = None


class ActionExecutor:
    def execute(
        self,
        ctx: Any,
        spec: ActionSpec,
        recognition: Recognition | None = None,
    ) -> ActionResult:
        try:
            if spec.type == "none":
                return ActionResult(ok=True)
            if spec.type == "tap_self":
                if recognition is None:
                    return ActionResult(False, "tap_self 缺少识别结果")
                ctx.device.tap(*recognition.point, jitter=True)
                return ActionResult(ok=True)
            if spec.type == "tap":
                point = spec.point
                if point is None and spec.rect is not None:
                    x, y, width, height = spec.rect
                    point = x + width // 2, y + height // 2
                if point is None:
                    return ActionResult(False, "tap 缺少 point 或 rect")
                ctx.device.tap(*point, jitter=True)
                return ActionResult(ok=True)
            if spec.type == "back":
                ctx.device.back()
                return ActionResult(ok=True)
            if spec.type == "swipe":
                if spec.from_point is None or spec.to_point is None:
                    return ActionResult(False, "swipe 缺少 from 或 to")
                ctx.device.swipe(
                    *spec.from_point,
                    *spec.to_point,
                    duration_ms=spec.duration_ms,
                )
                return ActionResult(ok=True)
            if spec.type == "wait":
                time.sleep(spec.seconds)
                return ActionResult(ok=True)
            if spec.type == "success":
                return ActionResult(ok=True, terminal="success")
            if spec.type == "fail":
                return ActionResult(ok=True, terminal="fail")
            return ActionResult(False, f"未知动作: {spec.type}")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(False, str(exc))
