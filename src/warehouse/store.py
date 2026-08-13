"""SQLite store for manual warehouse catalog scans."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.warehouse.models import ItemObservation, WarehouseScanResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINAL_SCAN_STATUSES = frozenset({"success", "partial", "failed", "stopped"})


class WarehouseCatalogStore:
    """Persist warehouse item observations in a local SQLite database."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def start_scan(self) -> str:
        connection = self._require_connection()
        scan_id = uuid.uuid4().hex
        now = _utc_now()
        with connection:
            connection.execute(
                """
                INSERT INTO scan_sessions (
                    scan_id,
                    status,
                    started_at,
                    categories_completed,
                    items_found,
                    low_confidence_count,
                    message
                )
                VALUES (?, 'running', ?, 0, 0, 0, '')
                """,
                (scan_id, now),
            )
        return scan_id

    def upsert_observation(self, scan_id: str, observation: ItemObservation) -> None:
        self.upsert_page(scan_id, [observation])

    def upsert_page(self, scan_id: str, observations: Iterable[ItemObservation]) -> None:
        connection = self._require_connection()
        now = _utc_now()
        prepared_observations = [
            _PreparedObservation.from_observation(observation)
            for observation in observations
        ]

        if not prepared_observations:
            return

        with connection:
            for prepared in prepared_observations:
                connection.execute(
                    """
                    INSERT INTO warehouse_items (
                        category_code,
                        name_raw,
                        name_normalized,
                        quantity_text,
                        ocr_confidence,
                        icon_bytes,
                        card_bytes,
                        icon_hash,
                        icon_path,
                        card_path,
                        first_seen_at,
                        last_seen_at,
                        page_index,
                        screen_path,
                        bbox_left,
                        bbox_top,
                        bbox_right,
                        bbox_bottom,
                        needs_review
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category_code, name_normalized, icon_hash)
                    DO UPDATE SET
                        name_raw = excluded.name_raw,
                        quantity_text = excluded.quantity_text,
                        ocr_confidence = excluded.ocr_confidence,
                        icon_bytes = excluded.icon_bytes,
                        card_bytes = excluded.card_bytes,
                        icon_path = excluded.icon_path,
                        card_path = excluded.card_path,
                        last_seen_at = excluded.last_seen_at,
                        page_index = excluded.page_index,
                        screen_path = excluded.screen_path,
                        bbox_left = excluded.bbox_left,
                        bbox_top = excluded.bbox_top,
                        bbox_right = excluded.bbox_right,
                        bbox_bottom = excluded.bbox_bottom,
                        needs_review = excluded.needs_review
                    """,
                    (
                        prepared.category_code,
                        prepared.name_raw,
                        prepared.name_normalized,
                        prepared.quantity_text,
                        prepared.ocr_confidence,
                        prepared.icon_bytes,
                        prepared.card_bytes,
                        prepared.icon_hash,
                        prepared.icon_path,
                        prepared.card_path,
                        now,
                        now,
                        prepared.page_index,
                        prepared.screen_path,
                        prepared.bbox_left,
                        prepared.bbox_top,
                        prepared.bbox_right,
                        prepared.bbox_bottom,
                        int(prepared.needs_review),
                    ),
                )
                item_id = connection.execute(
                    """
                    SELECT id
                    FROM warehouse_items
                    WHERE category_code = ?
                      AND name_normalized = ?
                      AND icon_hash = ?
                    """,
                    (
                        prepared.category_code,
                        prepared.name_normalized,
                        prepared.icon_hash,
                    ),
                ).fetchone()["id"]
                connection.execute(
                    """
                    INSERT INTO warehouse_observations (
                        scan_id,
                        item_id,
                        observed_at,
                        category_code,
                        name_raw,
                        name_normalized,
                        quantity_text,
                        ocr_confidence,
                        icon_hash,
                        page_index,
                        screen_path,
                        bbox_left,
                        bbox_top,
                        bbox_right,
                        bbox_bottom,
                        needs_review
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        item_id,
                        now,
                        prepared.category_code,
                        prepared.name_raw,
                        prepared.name_normalized,
                        prepared.quantity_text,
                        prepared.ocr_confidence,
                        prepared.icon_hash,
                        prepared.page_index,
                        prepared.screen_path,
                        prepared.bbox_left,
                        prepared.bbox_top,
                        prepared.bbox_right,
                        prepared.bbox_bottom,
                        int(prepared.needs_review),
                    ),
                )

    def record_category_completion(self, scan_id: str, category_code: str) -> None:
        connection = self._require_connection()
        now = _utc_now()

        with connection:
            connection.execute(
                """
                INSERT INTO scan_category_completions (
                    scan_id,
                    category_code,
                    completed_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(scan_id, category_code)
                DO UPDATE SET completed_at = excluded.completed_at
                """,
                (scan_id, category_code, now),
            )

    def finish_scan(
        self,
        scan_id: str,
        status: str = "success",
        message: str | None = None,
    ) -> WarehouseScanResult:
        connection = self._require_connection()
        if status not in FINAL_SCAN_STATUSES:
            raise ValueError(
                "Invalid final scan status. Expected one of: success, partial, failed, stopped."
            )
        now = _utc_now()
        row = connection.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM scan_category_completions
                    WHERE scan_id = ?
                ) AS categories_completed,
                COUNT(DISTINCT item_id) AS items_found,
                COUNT(DISTINCT CASE WHEN needs_review = 1 THEN item_id END)
                    AS low_confidence_count
            FROM warehouse_observations
            WHERE scan_id = ?
            """,
            (scan_id, scan_id),
        ).fetchone()
        categories_completed = int(row["categories_completed"])
        items_found = int(row["items_found"])
        low_confidence_count = int(row["low_confidence_count"])
        final_message = (
            _default_finish_message(status, items_found)
            if message is None
            else str(message)
        )

        with connection:
            connection.execute(
                """
                UPDATE scan_sessions
                SET status = ?,
                    finished_at = ?,
                    categories_completed = ?,
                    items_found = ?,
                    low_confidence_count = ?,
                    message = ?
                WHERE scan_id = ?
                """,
                (
                    status,
                    now,
                    categories_completed,
                    items_found,
                    low_confidence_count,
                    final_message,
                    scan_id,
                ),
            )

        return WarehouseScanResult(
            status=status,
            scan_id=scan_id,
            categories_completed=categories_completed,
            items_found=items_found,
            low_confidence_count=low_confidence_count,
            message=final_message,
        )

    def get_items(self, category_code: str | None = None) -> list[dict[str, Any]]:
        connection = self._require_connection()
        query = """
            SELECT
                id,
                category_code,
                name_raw,
                name_normalized,
                quantity_text,
                ocr_confidence,
                icon_hash,
                icon_path,
                card_path,
                first_seen_at,
                last_seen_at,
                page_index,
                screen_path,
                bbox_left,
                bbox_top,
                bbox_right,
                bbox_bottom,
                needs_review
            FROM warehouse_items
        """
        params: tuple[Any, ...] = ()
        if category_code is not None:
            query += " WHERE category_code = ?"
            params = (category_code,)
        query += " ORDER BY category_code, name_normalized, id"

        rows = connection.execute(query, params).fetchall()
        return [_item_row_to_dict(row) for row in rows]

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _create_schema(self) -> None:
        connection = self._require_connection()
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scan_sessions (
                    scan_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    categories_completed INTEGER NOT NULL DEFAULT 0,
                    items_found INTEGER NOT NULL DEFAULT 0,
                    low_confidence_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS warehouse_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_code TEXT NOT NULL,
                    name_raw TEXT NOT NULL,
                    name_normalized TEXT NOT NULL,
                    quantity_text TEXT NOT NULL,
                    ocr_confidence REAL NOT NULL,
                    icon_bytes BLOB NOT NULL,
                    card_bytes BLOB NOT NULL,
                    icon_hash TEXT NOT NULL,
                    icon_path TEXT NOT NULL,
                    card_path TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    screen_path TEXT NOT NULL,
                    bbox_left INTEGER NOT NULL,
                    bbox_top INTEGER NOT NULL,
                    bbox_right INTEGER NOT NULL,
                    bbox_bottom INTEGER NOT NULL,
                    needs_review INTEGER NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ux_warehouse_items_identity
                ON warehouse_items(category_code, name_normalized, icon_hash);

                CREATE TABLE IF NOT EXISTS warehouse_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    category_code TEXT NOT NULL,
                    name_raw TEXT NOT NULL,
                    name_normalized TEXT NOT NULL,
                    quantity_text TEXT NOT NULL,
                    ocr_confidence REAL NOT NULL,
                    icon_hash TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    screen_path TEXT NOT NULL,
                    bbox_left INTEGER NOT NULL,
                    bbox_top INTEGER NOT NULL,
                    bbox_right INTEGER NOT NULL,
                    bbox_bottom INTEGER NOT NULL,
                    needs_review INTEGER NOT NULL,
                    FOREIGN KEY(scan_id) REFERENCES scan_sessions(scan_id),
                    FOREIGN KEY(item_id) REFERENCES warehouse_items(id)
                );

                CREATE TABLE IF NOT EXISTS scan_category_completions (
                    scan_id TEXT NOT NULL,
                    category_code TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(scan_id, category_code),
                    FOREIGN KEY(scan_id) REFERENCES scan_sessions(scan_id)
                );
                """
            )

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("WarehouseCatalogStore is not open.")
        return self.connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_finish_message(status: str, items_found: int) -> str:
    if status == "success":
        return f"Completed scan with {items_found} item(s)."
    return f"Finished scan with status '{status}' after recording {items_found} item(s)."


def _relative_project_path(path: str) -> str:
    raw_path = Path(path)
    if not raw_path.is_absolute():
        return raw_path.as_posix()
    try:
        return raw_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        raise ValueError(
            f"Stored image paths must be project-relative; got outside-root path: {path}"
        ) from None


def _evidence_path(kind: str, category_code: str, icon_hash: str) -> str:
    return Path("artifacts", "warehouse", kind, category_code, f"{icon_hash}.bin").as_posix()


def _item_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["bbox"] = (
        result.pop("bbox_left"),
        result.pop("bbox_top"),
        result.pop("bbox_right"),
        result.pop("bbox_bottom"),
    )
    result["needs_review"] = bool(result["needs_review"])
    return result


class _PreparedObservation:
    def __init__(
        self,
        *,
        category_code: str,
        name_raw: str,
        name_normalized: str,
        quantity_text: str,
        ocr_confidence: float,
        icon_bytes: bytes,
        card_bytes: bytes,
        icon_hash: str,
        page_index: int,
        screen_path: str,
        bbox_left: int,
        bbox_top: int,
        bbox_right: int,
        bbox_bottom: int,
        needs_review: bool,
        icon_path: str,
        card_path: str,
    ) -> None:
        self.category_code = category_code
        self.name_raw = name_raw
        self.name_normalized = name_normalized
        self.quantity_text = quantity_text
        self.ocr_confidence = ocr_confidence
        self.icon_bytes = icon_bytes
        self.card_bytes = card_bytes
        self.icon_hash = icon_hash
        self.page_index = page_index
        self.screen_path = screen_path
        self.bbox_left = bbox_left
        self.bbox_top = bbox_top
        self.bbox_right = bbox_right
        self.bbox_bottom = bbox_bottom
        self.needs_review = needs_review
        self.icon_path = icon_path
        self.card_path = card_path

    @classmethod
    def from_observation(cls, observation: ItemObservation) -> "_PreparedObservation":
        bbox_left, bbox_top, bbox_right, bbox_bottom = observation.bbox
        return cls(
            category_code=observation.category_code,
            name_raw=observation.name_raw,
            name_normalized=observation.name_normalized,
            quantity_text=observation.quantity_text,
            ocr_confidence=observation.ocr_confidence,
            icon_bytes=observation.icon_bytes,
            card_bytes=observation.card_bytes,
            icon_hash=observation.icon_hash,
            page_index=observation.page_index,
            screen_path=_relative_project_path(observation.screen_path),
            bbox_left=bbox_left,
            bbox_top=bbox_top,
            bbox_right=bbox_right,
            bbox_bottom=bbox_bottom,
            needs_review=observation.needs_review,
            icon_path=_evidence_path(
                "icons", observation.category_code, observation.icon_hash
            ),
            card_path=_evidence_path(
                "cards", observation.category_code, observation.icon_hash
            ),
        )
