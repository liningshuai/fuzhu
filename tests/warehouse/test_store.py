from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from src.warehouse.models import ItemObservation
from src.warehouse.store import WarehouseCatalogStore


class WarehouseCatalogStoreTests(unittest.TestCase):
    def test_open_creates_required_schema_with_foreign_keys_and_unique_item_key(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "warehouse-test.sqlite3"
            store = WarehouseCatalogStore(db_path)

            store.open()
            try:
                connection = sqlite3.connect(db_path)
                try:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                    indexes = {
                        row[1]
                        for row in connection.execute(
                            "PRAGMA index_list('warehouse_items')"
                        )
                    }
                    assert store.connection is not None
                    foreign_keys = store.connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]

                    self.assertIn("scan_sessions", tables)
                    self.assertIn("scan_category_completions", tables)
                    self.assertIn("warehouse_items", tables)
                    self.assertIn("warehouse_observations", tables)
                    self.assertEqual(foreign_keys, 1)
                    self.assertIn("ux_warehouse_items_identity", indexes)
                finally:
                    connection.close()
            finally:
                store.close()

    def test_upsert_observation_creates_one_item_and_one_observation_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()
                store.upsert_observation(scan_id, self._observation())
                result = store.finish_scan(scan_id)
                items = store.get_items()

                self.assertEqual(result.status, "success")
                self.assertEqual(result.scan_id, scan_id)
                self.assertEqual(result.categories_completed, 0)
                self.assertEqual(result.items_found, 1)
                self.assertEqual(result.low_confidence_count, 0)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["category_code"], "resource")
                self.assertEqual(items[0]["name_normalized"], "wood")
                self.assertEqual(items[0]["screen_path"], "runs/warehouse/page-1.png")
                self.assertEqual(
                    items[0]["icon_path"],
                    "artifacts/warehouse/icons/resource/hash-wood.bin",
                )
                self.assertEqual(
                    items[0]["card_path"],
                    "artifacts/warehouse/cards/resource/hash-wood.bin",
                )

                counts = self._counts(store)
                self.assertEqual(counts["warehouse_items"], 1)
                self.assertEqual(counts["warehouse_observations"], 1)
            finally:
                store.close()

    def test_repeated_same_key_updates_last_seen_without_duplicate_items(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()
                store.upsert_observation(scan_id, self._observation(quantity_text="10"))
                first_seen = store.get_items()[0]["last_seen_at"]

                time.sleep(0.01)
                store.upsert_observation(scan_id, self._observation(quantity_text="12"))
                result = store.finish_scan(scan_id)
                items = store.get_items("resource")

                self.assertEqual(result.items_found, 1)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["quantity_text"], "12")
                self.assertGreater(items[0]["last_seen_at"], first_seen)

                counts = self._counts(store)
                self.assertEqual(counts["warehouse_items"], 1)
                self.assertEqual(counts["warehouse_observations"], 2)
            finally:
                store.close()

    def test_upsert_page_is_atomic_for_all_observations_on_a_page(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()

                with self.assertRaisesRegex(ValueError, "project-relative"):
                    store.upsert_page(
                        scan_id,
                        [
                            self._observation(name_normalized="wood", icon_hash="hash-wood"),
                            self._observation(
                                name_normalized="stone",
                                icon_hash="hash-stone",
                                screen_path="C:/outside-project/page-1.png",
                            ),
                        ],
                    )

                counts = self._counts(store)
                self.assertEqual(counts["warehouse_items"], 0)
                self.assertEqual(counts["warehouse_observations"], 0)
            finally:
                store.close()

    def test_finish_scan_counts_explicitly_completed_empty_categories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()
                store.record_category_completion(scan_id, "resource")

                result = store.finish_scan(scan_id)

                self.assertEqual(result.status, "success")
                self.assertEqual(result.categories_completed, 1)
                self.assertEqual(result.items_found, 0)
                self.assertEqual(result.low_confidence_count, 0)
            finally:
                store.close()

    def test_finish_scan_persists_requested_non_success_status_and_message(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()
                store.record_category_completion(scan_id, "resource")

                result = store.finish_scan(
                    scan_id,
                    status="partial",
                    message="Scan finished but could not verify return to main city.",
                )

                self.assertEqual(result.status, "partial")
                self.assertEqual(
                    result.message,
                    "Scan finished but could not verify return to main city.",
                )
                assert store.connection is not None
                session_row = store.connection.execute(
                    """
                    SELECT status, message, categories_completed, items_found, low_confidence_count
                    FROM scan_sessions
                    WHERE scan_id = ?
                    """,
                    (scan_id,),
                ).fetchone()
                self.assertEqual(session_row["status"], "partial")
                self.assertEqual(
                    session_row["message"],
                    "Scan finished but could not verify return to main city.",
                )
                self.assertEqual(session_row["categories_completed"], 1)
                self.assertEqual(session_row["items_found"], 0)
                self.assertEqual(session_row["low_confidence_count"], 0)
            finally:
                store.close()

    def test_finish_scan_rejects_unknown_final_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()

                with self.assertRaisesRegex(ValueError, "Invalid final scan status"):
                    store.finish_scan(scan_id, status="cancelled")
            finally:
                store.close()

    def test_finish_scan_counts_low_confidence_items_needing_review(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()
                store.upsert_observation(
                    scan_id,
                    self._observation(
                        name_raw="???",
                        name_normalized="unknown",
                        ocr_confidence=0.42,
                        icon_hash="hash-unknown",
                        needs_review=True,
                    ),
                )
                result = store.finish_scan(scan_id)

                self.assertEqual(result.low_confidence_count, 1)
            finally:
                store.close()

    def test_upsert_observation_rejects_absolute_screen_path_outside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = WarehouseCatalogStore(Path(tmp_dir) / "warehouse-test.sqlite3")
            store.open()
            try:
                scan_id = store.start_scan()

                with self.assertRaisesRegex(ValueError, "project-relative"):
                    store.upsert_observation(
                        scan_id,
                        self._observation(screen_path="C:/outside-project/page-1.png"),
                    )
            finally:
                store.close()

    def _observation(self, **overrides) -> ItemObservation:
        values = {
            "category_code": "resource",
            "name_raw": "Wood",
            "name_normalized": "wood",
            "quantity_text": "10",
            "ocr_confidence": 0.93,
            "icon_bytes": b"icon",
            "card_bytes": b"card",
            "icon_hash": "hash-wood",
            "page_index": 1,
            "screen_path": "runs/warehouse/page-1.png",
            "bbox": (10, 20, 30, 40),
            "needs_review": False,
        }
        values.update(overrides)
        return ItemObservation(**values)

    def _counts(self, store: WarehouseCatalogStore) -> dict[str, int]:
        assert store.connection is not None
        return {
            table: store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "scan_category_completions",
                "warehouse_items",
                "warehouse_observations",
            )
        }


if __name__ == "__main__":
    unittest.main()
