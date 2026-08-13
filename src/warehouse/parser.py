"""Warehouse card parsing helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from src.warehouse.models import ItemObservation

if TYPE_CHECKING:
    from src.pipeline.recognizers import OcrBackend, OcrText


def normalise_item_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub(r"\s*([(){}\[\]/\\\-+·:：,，.。!?！？])\s*", r"\1", text)
    text = re.sub(r"\s+", "", text)
    return text.casefold().strip()


def sha256_icon(image: np.ndarray) -> str:
    if image.size == 0:
        raise ValueError("icon image must not be empty")
    resized = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
    payload = _encode_png(resized)
    return hashlib.sha256(payload).hexdigest()


def parse_visible_cards(
    screen: np.ndarray,
    layout: dict[str, Any],
    ocr_backend: OcrBackend,
) -> list[ItemObservation]:
    grid = layout["grid"]
    rois = layout["rois"]
    columns = int(grid["columns"])
    rows = int(grid["rows"])
    origin_x, origin_y = _as_box(grid["origin"], expected=2)
    card_width, card_height = _as_box(grid["card_size"], expected=2)
    column_gap = int(grid.get("column_gap", 0))
    row_gap = int(grid.get("row_gap", 0))
    category_code = str(layout["category_code"])
    page_index = int(layout.get("page_index", 0))
    screen_path = str(layout.get("screen_path", ""))
    threshold = float(layout.get("ocr_threshold", 0.70))

    observations: list[ItemObservation] = []
    for row in range(rows):
        for column in range(columns):
            card_bbox = (
                origin_x + column * (card_width + column_gap),
                origin_y + row * (card_height + row_gap),
                card_width,
                card_height,
            )
            card_crop = _crop(screen, card_bbox)
            if card_crop.size == 0:
                continue

            icon_bbox = _offset_roi(card_bbox, rois["icon"])
            name_bbox = _offset_roi(card_bbox, rois["name"])
            quantity_bbox = _offset_roi(card_bbox, rois["quantity"])
            icon_crop = _crop(screen, icon_bbox)
            if "text" in rois:
                text_roi = _offset_roi(card_bbox, rois["text"])
            else:
                text_roi = _union_roi(name_bbox, quantity_bbox)

            ocr_items = ocr_backend.recognize(screen, text_roi)
            name_item = _select_text(ocr_items, name_bbox)
            quantity_item = _select_text(ocr_items, quantity_bbox)

            name_raw = name_item.text if name_item is not None else ""
            quantity_text = (quantity_item.text if quantity_item is not None else "").strip()
            if not name_raw.strip():
                name_raw = ""
            name_confidence = (
                float(name_item.score) if name_item is not None and name_raw else 0.0
            )
            name_normalized = normalise_item_name(name_raw)

            has_card_content = bool(quantity_text or name_raw or np.any(icon_crop))
            if not has_card_content:
                continue

            observations.append(
                ItemObservation(
                    category_code=category_code,
                    name_raw=name_raw,
                    name_normalized=name_normalized,
                    quantity_text=quantity_text,
                    ocr_confidence=name_confidence,
                    icon_bytes=_encode_png(icon_crop),
                    card_bytes=_encode_png(card_crop),
                    icon_hash=sha256_icon(icon_crop),
                    page_index=page_index,
                    screen_path=screen_path,
                    bbox=card_bbox,
                    needs_review=not name_normalized or name_confidence < threshold,
                )
            )
    return observations


def _as_box(values: Any, expected: int) -> tuple[int, ...]:
    if not isinstance(values, (list, tuple)) or len(values) != expected:
        raise ValueError(f"expected {expected} coordinates, got {values!r}")
    return tuple(int(value) for value in values)


def _offset_roi(
    card_bbox: tuple[int, int, int, int],
    roi: Any,
) -> tuple[int, int, int, int]:
    x, y, width, height = _as_box(roi, expected=4)
    return card_bbox[0] + x, card_bbox[1] + y, width, height


def _union_roi(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    x1 = min(left[0], right[0])
    y1 = min(left[1], right[1])
    x2 = max(left[0] + left[2], right[0] + right[2])
    y2 = max(left[1] + left[3], right[1] + right[3])
    return x1, y1, x2 - x1, y2 - y1


def _crop(image: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = roi
    max_y, max_x = image.shape[:2]
    left = max(0, min(x, max_x))
    top = max(0, min(y, max_y))
    right = max(left, min(x + width, max_x))
    bottom = max(top, min(y + height, max_y))
    return image[top:bottom, left:right]


def _encode_png(image: np.ndarray) -> bytes:
    if image.size == 0:
        raise ValueError("cannot encode empty image")
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("failed to encode png")
    return bytes(buffer)


def _select_text(
    items: list[OcrText],
    roi: tuple[int, int, int, int],
) -> OcrText | None:
    matched = [
        item
        for item in items
        if item.rect is not None and _intersects(item.rect, roi)
    ]
    if not matched:
        return None
    return sorted(
        matched,
        key=lambda item: (
            -float(item.score),
            item.rect[1] if item.rect is not None else 0,
            item.rect[0] if item.rect is not None else 0,
            item.text,
        ),
    )[0]


def _intersects(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> bool:
    return (
        left[0] < right[0] + right[2]
        and right[0] < left[0] + left[2]
        and left[1] < right[1] + right[3]
        and right[1] < left[1] + left[3]
    )
