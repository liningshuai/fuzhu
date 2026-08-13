"""Data models for the manual warehouse catalog utility."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WarehouseCategory:
    code: str
    label: str
    order: int


@dataclass(frozen=True)
class ItemObservation:
    category_code: str
    name_raw: str
    name_normalized: str
    quantity_text: str
    ocr_confidence: float
    icon_bytes: bytes
    card_bytes: bytes
    icon_hash: str
    page_index: int
    screen_path: str
    bbox: tuple[int, int, int, int]
    needs_review: bool


@dataclass(frozen=True)
class WarehouseScanResult:
    status: str
    scan_id: str
    categories_completed: int
    items_found: int
    low_confidence_count: int
    message: str
