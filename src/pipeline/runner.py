"""Pipeline 有限状态执行器。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from src.pipeline.actions import ActionExecutor
from src.pipeline.models import PipelineDefinition, PipelineNode, RecognizerSpec
from src.pipeline.recognizers import (
    OcrRecognizer,
    OcrProviderUnavailable,
    Recognition,
    RecognitionError,
    TemplateRecognizer,
)
from src.pipeline.result import PipelineResult, PipelineStatus, PipelineTrace


@dataclass(frozen=True)
class _Selection:
    node: PipelineNode | None
    recognition: Recognition | None = None
    screen: Any | None = None
    error: str | None = None


class PipelineRunner:
    def __init__(
        self,
        ctx: Any,
        max_steps: int = 100,
        action_executor: ActionExecutor | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须大于等于 1")
        self.ctx = ctx
        self.max_steps = max_steps
        self.action_executor = action_executor or ActionExecutor()
        self._recognizers: dict[str, Any] = {}

    def _get_recognizer(self, node: PipelineNode) -> Any:
        if node.id in self._recognizers:
            return self._recognizers[node.id]
        spec = node.recognize
        if spec is None:
            raise ValueError(f"节点没有识别器: {node.id}")
        recognizer = self._build_recognizer(spec)
        self._recognizers[node.id] = recognizer
        return recognizer

    def _build_recognizer(self, spec: RecognizerSpec) -> Any:
        if spec.type == "template":
            return TemplateRecognizer(spec)
        if spec.type == "ocr":
            return OcrRecognizer(spec)
        raise ValueError(f"未知识别器: {spec.type}")

    def _select(self, definition: PipelineDefinition, candidates: tuple[str, ...]) -> _Selection:
        if not candidates:
            return _Selection(None, error="候选节点列表为空")

        nodes = [definition.nodes[node_id] for node_id in candidates]
        has_recognizer = any(node.recognize is not None for node in nodes)
        screen = None
        if has_recognizer:
            try:
                screen = self.ctx.screenshot()
            except Exception as exc:  # noqa: BLE001
                return _Selection(None, error=f"截图失败: {exc}")

        for index, node in enumerate(nodes):
            if node.recognize is None:
                # 确定性节点只能作为候选列表的最后一项。
                if index == len(nodes) - 1:
                    return _Selection(node, screen=screen)
                continue
            try:
                recognition = self._get_recognizer(node).recognize(self.ctx, screen)
            except OcrProviderUnavailable as exc:
                return _Selection(None, error=f"OCR Provider 不可用: {exc}")
            except RecognitionError as exc:
                return _Selection(None, error=f"识别器不可用: {exc}")
            if recognition is not None:
                return _Selection(node, recognition=recognition, screen=screen)
        return _Selection(None, screen=screen, error="没有候选节点匹配当前画面")

    @staticmethod
    def _trace(
        node: PipelineNode,
        recognition: Recognition | None,
        started: float,
        error: str | None = None,
    ) -> PipelineTrace:
        return PipelineTrace(
            node_id=node.id,
            recognition_type=recognition.type if recognition else None,
            score=recognition.score if recognition else None,
            point=recognition.point if recognition else None,
            action_type=node.action.type,
            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
            error=error,
        )

    def run(self, definition: PipelineDefinition) -> PipelineResult:
        trace: list[PipelineTrace] = []
        visits: dict[str, int] = {}
        candidates = (definition.start,)
        fallback_source = definition.start
        error_transition = False

        while True:
            if len(trace) >= self.max_steps:
                return PipelineResult(
                    PipelineStatus.STEP_LIMIT,
                    f"超过 Pipeline 全局最大步骤数: {self.max_steps}",
                    tuple(trace),
                )

            selection = self._select(definition, candidates)
            if selection.error:
                # 环境故障不通过无条件点击兜底，直接报告未就绪。
                if selection.error.startswith(("截图失败:", "OCR Provider 不可用:", "识别器不可用:")):
                    return PipelineResult(
                        PipelineStatus.NOT_READY,
                        selection.error,
                        tuple(trace),
                    )
                source = definition.nodes[fallback_source]
                if not error_transition and source.error_next:
                    candidates = source.error_next
                    fallback_source = source.id
                    error_transition = True
                    continue
                return PipelineResult(
                    PipelineStatus.FAILED,
                    selection.error,
                    tuple(trace),
                )

            node = selection.node
            if node is None:
                return PipelineResult(
                    PipelineStatus.FAILED,
                    "Pipeline 未选择到节点",
                    tuple(trace),
                )

            started = time.monotonic()
            visits[node.id] = visits.get(node.id, 0) + 1
            if visits[node.id] > node.max_times:
                message = f"节点 {node.id} 超过 max_times={node.max_times}"
                trace.append(self._trace(node, selection.recognition, started, message))
                if node.error_next:
                    candidates = node.error_next
                    fallback_source = node.id
                    error_transition = True
                    continue
                return PipelineResult(PipelineStatus.FAILED, message, tuple(trace))

            action_result = self.action_executor.execute(
                self.ctx,
                node.action,
                recognition=selection.recognition,
            )
            if action_result.terminal == "success":
                trace.append(self._trace(node, selection.recognition, started))
                return PipelineResult(PipelineStatus.SUCCESS, "Pipeline 执行成功", tuple(trace))
            if action_result.terminal == "fail":
                message = action_result.message or f"Pipeline 在节点 {node.id} 失败"
                trace.append(self._trace(node, selection.recognition, started, message))
                return PipelineResult(PipelineStatus.FAILED, message, tuple(trace))
            if not action_result.ok:
                message = action_result.message or f"节点 {node.id} 动作失败"
                trace.append(self._trace(node, selection.recognition, started, message))
                if node.error_next:
                    candidates = node.error_next
                    fallback_source = node.id
                    error_transition = True
                    continue
                return PipelineResult(PipelineStatus.FAILED, message, tuple(trace))

            trace.append(self._trace(node, selection.recognition, started))
            if node.delay:
                time.sleep(node.delay)
            if node.next:
                candidates = node.next
                fallback_source = node.id
                error_transition = False
                continue
            return PipelineResult(
                PipelineStatus.FAILED,
                f"节点 {node.id} 执行成功但没有 next 或终止动作",
                tuple(trace),
            )
