"""Pipeline 识别器适配层。

识别器只负责在调用方提供的截图上做判断，不负责截图和输入操作。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import re
from typing import Any, Protocol

import numpy as np

from src.pipeline.models import RecognizerSpec


class RecognitionError(RuntimeError):
    """识别过程中的可控错误，例如模板缺失。"""


class OcrProviderUnavailable(RecognitionError):
    """OCR 依赖、模型或运行时不可用。"""


@dataclass(frozen=True)
class Recognition:
    type: str
    score: float
    point: tuple[int, int]
    rect: tuple[int, int, int, int] | None = None
    text: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class OcrText:
    text: str
    score: float
    rect: tuple[int, int, int, int] | None = None


class OcrBackend(Protocol):
    def recognize(
        self,
        image: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> list[OcrText]:
        """在截图或 ROI 上识别文字，返回截图坐标系中的矩形。"""


def _rect_center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    x, y, width, height = rect
    return x + width // 2, y + height // 2


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


class TemplateRecognizer:
    def __init__(self, spec: RecognizerSpec) -> None:
        if spec.type != "template" or not spec.template:
            raise ValueError("TemplateRecognizer 需要 template 类型和模板名")
        self.spec = spec

    def recognize(self, ctx: Any, screen: np.ndarray) -> Recognition | None:
        try:
            match = ctx.matcher.find(
                screen,
                self.spec.template,
                threshold=self.spec.threshold,
                region=self.spec.roi,
            )
        except FileNotFoundError as exc:
            raise RecognitionError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise RecognitionError(f"模板识别失败: {exc}") from exc
        if match is None:
            return None
        return Recognition(
            type="template",
            score=float(match.score),
            point=(int(match.x), int(match.y)),
            rect=(
                int(match.x - match.w // 2),
                int(match.y - match.h // 2),
                int(match.w),
                int(match.h),
            ),
            name=self.spec.template,
        )


class RapidOcrBackend:
    """rapidocr_onnxruntime 的懒加载适配器。"""

    def __init__(self) -> None:
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            module = importlib.import_module("rapidocr_onnxruntime")
            factory = getattr(module, "RapidOCR")
            self._engine = factory()
        except Exception as exc:  # noqa: BLE001
            raise OcrProviderUnavailable(
                f"OCR Provider 不可用，请安装 rapidocr_onnxruntime: {exc}"
            ) from exc
        return self._engine

    @staticmethod
    def _as_rect(box: Any) -> tuple[int, int, int, int] | None:
        values = np.asarray(box, dtype=float)
        if values.size == 8:
            points = values.reshape(4, 2)
            x_min, y_min = points.min(axis=0)
            x_max, y_max = points.max(axis=0)
            return (
                int(round(x_min)),
                int(round(y_min)),
                max(1, int(round(x_max - x_min))),
                max(1, int(round(y_max - y_min))),
            )
        if values.size == 4:
            x, y, width, height = values.tolist()
            return int(round(x)), int(round(y)), int(round(width)), int(round(height))
        return None

    def recognize(
        self,
        image: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> list[OcrText]:
        engine = self._get_engine()
        offset_x = offset_y = 0
        source = image
        if roi is not None:
            x, y, width, height = roi
            source = image[y : y + height, x : x + width]
            offset_x, offset_y = x, y

        try:
            raw = engine(source)
        except Exception as exc:  # noqa: BLE001
            raise RecognitionError(f"OCR 识别失败: {exc}") from exc

        items = raw[0] if isinstance(raw, tuple) else raw
        if not items:
            return []

        result: list[OcrText] = []
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            rect = self._as_rect(item[0])
            if rect is not None:
                rect = (rect[0] + offset_x, rect[1] + offset_y, rect[2], rect[3])
            try:
                result.append(OcrText(str(item[1]), float(item[2]), rect))
            except (TypeError, ValueError):
                continue
        return result


class OcrRecognizer:
    def __init__(self, spec: RecognizerSpec, backend: OcrBackend | None = None) -> None:
        if spec.type != "ocr" or not spec.text:
            raise ValueError("OcrRecognizer 需要 ocr 类型和目标文字")
        self.spec = spec
        self._backend = backend

    def recognize(self, ctx: Any, screen: np.ndarray) -> Recognition | None:
        if self._backend is None:
            self._backend = RapidOcrBackend()
        backend = self._backend
        items = backend.recognize(screen, self.spec.roi)
        target = _normalise_text(self.spec.text)
        candidates = [
            item
            for item in items
            if item.score >= self.spec.threshold
            and target in _normalise_text(item.text)
        ]
        if not candidates:
            return None
        item = max(candidates, key=lambda value: value.score)
        rect = item.rect
        if rect is None:
            rect = self.spec.roi
        if rect is None:
            height, width = screen.shape[:2]
            rect = (0, 0, int(width), int(height))
        return Recognition(
            type="ocr",
            score=float(item.score),
            point=_rect_center(rect),
            rect=rect,
            text=item.text,
        )
