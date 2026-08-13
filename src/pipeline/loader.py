"""Pipeline YAML 加载与严格校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.pipeline.models import (
    ActionSpec,
    PipelineDefinition,
    PipelineNode,
    RecognizerSpec,
)


class PipelineConfigError(ValueError):
    """Pipeline 配置不合法。"""


_RECOGNIZER_TYPES = {"template", "ocr"}
_ACTION_TYPES = {
    "none",
    "tap_self",
    "tap",
    "back",
    "swipe",
    "wait",
    "success",
    "fail",
}
_TERMINAL_ACTIONS = {"success", "fail"}
_DETERMINISTIC_ACTIONS = {"back", "swipe", "wait", "tap", "none"}


def _fail(path: Path, node_id: str | None, field: str, message: str) -> None:
    location = str(path)
    if node_id:
        location += f" node={node_id}"
    raise PipelineConfigError(f"{location} field={field}: {message}")


def _mapping(value: Any, path: Path, node_id: str | None, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, node_id, field, "必须是对象")
    return value


def _string(value: Any, path: Path, node_id: str | None, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, node_id, field, "必须是非空字符串")
    return value.strip()


def _int(value: Any, path: Path, node_id: str | None, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, node_id, field, "必须是整数")
    return value


def _number(value: Any, path: Path, node_id: str | None, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, node_id, field, "必须是数字")
    return float(value)


def _point(
    value: Any,
    path: Path,
    node_id: str | None,
    field: str,
    coordinate_base: tuple[int, int],
) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail(path, node_id, field, "必须是 [x, y]")
    x = _int(value[0], path, node_id, f"{field}[0]")
    y = _int(value[1], path, node_id, f"{field}[1]")
    if not (0 <= x < coordinate_base[0] and 0 <= y < coordinate_base[1]):
        _fail(path, node_id, field, "坐标超出 coordinate_base")
    return x, y


def _rect(
    value: Any,
    path: Path,
    node_id: str | None,
    field: str,
    coordinate_base: tuple[int, int],
) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        _fail(path, node_id, field, "必须是 [x, y, width, height]")
    x = _int(value[0], path, node_id, f"{field}[0]")
    y = _int(value[1], path, node_id, f"{field}[1]")
    width = _int(value[2], path, node_id, f"{field}[2]")
    height = _int(value[3], path, node_id, f"{field}[3]")
    if width <= 0 or height <= 0:
        _fail(path, node_id, field, "宽高必须大于 0")
    if x < 0 or y < 0 or x + width > coordinate_base[0] or y + height > coordinate_base[1]:
        _fail(path, node_id, field, "矩形超出 coordinate_base")
    return x, y, width, height


def _task_list(
    value: Any,
    path: Path,
    node_id: str,
    field: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        _fail(path, node_id, field, "必须是任务名列表")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_string(item, path, node_id, f"{field}[{index}]") )
    return tuple(result)


def _parse_recognizer(
    raw: Any,
    path: Path,
    node_id: str,
    coordinate_base: tuple[int, int],
) -> RecognizerSpec | None:
    if raw is None:
        return None
    data = _mapping(raw, path, node_id, "recognize")
    kind = _string(data.get("type"), path, node_id, "recognize.type")
    if kind not in _RECOGNIZER_TYPES:
        _fail(path, node_id, "recognize.type", f"不支持 {kind!r}")

    roi = None
    if data.get("roi") is not None:
        roi = _rect(data["roi"], path, node_id, "recognize.roi", coordinate_base)

    threshold = _number(data.get("threshold", 0.82), path, node_id, "recognize.threshold")
    if not 0.0 <= threshold <= 1.0:
        _fail(path, node_id, "recognize.threshold", "必须在 0 到 1 之间")

    if kind == "template":
        template = _string(data.get("template"), path, node_id, "recognize.template")
        return RecognizerSpec(type="template", template=template, roi=roi, threshold=threshold)

    text = _string(data.get("text"), path, node_id, "recognize.text")
    return RecognizerSpec(type="ocr", text=text, roi=roi, threshold=threshold)


def _parse_action(
    raw: Any,
    path: Path,
    node_id: str,
    coordinate_base: tuple[int, int],
    recognize: RecognizerSpec | None,
) -> ActionSpec:
    if raw is None:
        data: dict[str, Any] = {"type": "none"}
    elif isinstance(raw, str):
        data = {"type": raw}
    else:
        data = _mapping(raw, path, node_id, "action")

    kind = _string(data.get("type"), path, node_id, "action.type")
    if kind not in _ACTION_TYPES:
        _fail(path, node_id, "action.type", f"不支持 {kind!r}")

    if kind == "tap_self" and recognize is None:
        _fail(path, node_id, "action.type", "tap_self 必须配置 recognize")

    point = None
    rect = None
    from_point = None
    to_point = None
    duration_ms = _int(data.get("duration_ms", 400), path, node_id, "action.duration_ms")
    seconds = _number(data.get("seconds", 0.0), path, node_id, "action.seconds")

    if kind == "tap":
        if data.get("point") is not None:
            point = _point(data["point"], path, node_id, "action.point", coordinate_base)
        elif data.get("rect") is not None:
            rect = _rect(data["rect"], path, node_id, "action.rect", coordinate_base)
        else:
            _fail(path, node_id, "action", "tap 必须配置 point 或 rect")
    elif kind == "swipe":
        from_point = _point(data.get("from"), path, node_id, "action.from", coordinate_base)
        to_point = _point(data.get("to"), path, node_id, "action.to", coordinate_base)
        if duration_ms <= 0:
            _fail(path, node_id, "action.duration_ms", "必须大于 0")
    elif kind == "wait":
        if seconds < 0:
            _fail(path, node_id, "action.seconds", "不能小于 0")
    elif kind in {"success", "fail"} and recognize is not None:
        _fail(path, node_id, "recognize", "终止节点不应配置识别器")

    return ActionSpec(
        type=kind,  # type: ignore[arg-type]
        point=point,
        rect=rect,
        from_point=from_point,
        to_point=to_point,
        duration_ms=duration_ms,
        seconds=seconds,
    )


def load_pipeline(path: Path) -> PipelineDefinition:
    """加载并校验一个 Pipeline YAML 文件。"""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise PipelineConfigError(f"{path}: 无法读取配置: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PipelineConfigError(f"{path}: YAML 解析失败: {exc}") from exc

    data = _mapping(raw, path, None, "root")
    pipeline_id = _string(data.get("id"), path, None, "id")
    start = _string(data.get("start"), path, None, "start")
    coordinate_raw = data.get("coordinate_base", [1080, 1920])
    if not isinstance(coordinate_raw, (list, tuple)) or len(coordinate_raw) != 2:
        _fail(path, None, "coordinate_base", "必须是 [width, height]")
    coordinate_base = (
        _int(coordinate_raw[0], path, None, "coordinate_base[0]"),
        _int(coordinate_raw[1], path, None, "coordinate_base[1]"),
    )
    if coordinate_base != (1080, 1920):
        _fail(path, None, "coordinate_base", "第一阶段只支持 [1080, 1920]")

    raw_nodes = _mapping(data.get("nodes"), path, None, "nodes")
    if not raw_nodes:
        _fail(path, None, "nodes", "至少需要一个节点")

    nodes: dict[str, PipelineNode] = {}
    for raw_node_id, raw_node in raw_nodes.items():
        node_id = _string(raw_node_id, path, None, "nodes key")
        node_data = _mapping(raw_node, path, node_id, "node")
        recognize = _parse_recognizer(
            node_data.get("recognize"), path, node_id, coordinate_base
        )
        action = _parse_action(
            node_data.get("action"), path, node_id, coordinate_base, recognize
        )
        next_nodes = _task_list(node_data.get("next"), path, node_id, "next")
        error_nodes = _task_list(node_data.get("error_next"), path, node_id, "error_next")

        if "max_times" not in node_data:
            if recognize is None and action.type not in _TERMINAL_ACTIONS:
                _fail(path, node_id, "max_times", "确定性非终止节点必须显式设置最大次数")
            max_times = 1
        else:
            max_times = _int(node_data["max_times"], path, node_id, "max_times")
            if max_times < 1:
                _fail(path, node_id, "max_times", "必须大于等于 1")

        delay = _number(node_data.get("delay", 0.0), path, node_id, "delay")
        if delay < 0:
            _fail(path, node_id, "delay", "不能小于 0")

        nodes[node_id] = PipelineNode(
            id=node_id,
            recognize=recognize,
            action=action,
            next=next_nodes,
            error_next=error_nodes,
            max_times=max_times,
            delay=delay,
        )

    if start not in nodes:
        _fail(path, None, "start", f"引用了不存在的节点 {start!r}")
    for node in nodes.values():
        for field, refs in (("next", node.next), ("error_next", node.error_next)):
            for ref in refs:
                if ref not in nodes:
                    _fail(path, node.id, field, f"引用了不存在的节点 {ref!r}")

    reachable: set[str] = set()
    stack = [start]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        node = nodes[node_id]
        stack.extend(node.next)
        stack.extend(node.error_next)
    if not any(nodes[node_id].action.type in _TERMINAL_ACTIONS for node_id in reachable):
        _fail(path, None, "nodes", "从 start 不可到达 success 或 fail 终止节点")

    return PipelineDefinition(
        id=pipeline_id,
        start=start,
        coordinate_base=coordinate_base,
        nodes=nodes,
    )


def validate_pipeline(definition: PipelineDefinition) -> None:
    """验证已解析的 Pipeline；Loader 已完成同样的检查。"""
    if not isinstance(definition, PipelineDefinition):
        raise PipelineConfigError("definition 必须是 PipelineDefinition")
