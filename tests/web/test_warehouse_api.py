from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import src.web.app as web_app


class WarehouseApiTests(unittest.TestCase):
    def test_status_returns_idle_snapshot(self):
        controller = _FakeController(
            snapshot={
                "status": "idle",
                "scan_id": None,
                "category": None,
                "page": None,
                "categories_completed": 0,
                "items_found": 0,
                "low_confidence_count": 0,
                "message": "Warehouse scan idle.",
            }
        )

        with self._patched_app(controller=controller):
            response = web_app.api_warehouse_status()

        self.assertEqual(response["status"], "idle")
        self.assertEqual(response["message"], "Warehouse scan idle.")

    def test_scan_starts_manual_scan_without_starting_engine(self):
        engine = _FakeEngine(status_payload={"running": False, "device_online": True})
        controller = _FakeController(
            snapshot=_snapshot("idle", "Warehouse scan idle.")
        )

        with self._patched_app(engine=engine, controller=controller):
            response = web_app.api_warehouse_scan()

        self.assertEqual(response["status"], "running")
        self.assertEqual(response["message"], "Warehouse scan started.")
        self.assertEqual(controller.start_calls, 1)
        self.assertEqual(engine.start_calls, 0)

    def test_scan_rejects_duplicate_scan_with_conflict_payload(self):
        engine = _FakeEngine(status_payload={"running": False, "device_online": True})
        controller = _FakeController(
            snapshot=_snapshot("running", "Warehouse scan started.")
        )

        with self._patched_app(engine=engine, controller=controller):
            with self.assertRaises(HTTPException) as cm:
                web_app.api_warehouse_scan()

        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["error"], "warehouse_scan_conflict")
        self.assertEqual(cm.exception.detail["controller_status"], "running")
        self.assertEqual(cm.exception.detail["snapshot"], controller.snapshot_payload)
        self.assertEqual(controller.start_calls, 0)
        self.assertEqual(engine.start_calls, 0)

    def test_scan_rejects_when_bot_engine_is_running(self):
        engine = _FakeEngine(status_payload={"running": True, "device_online": True})
        controller = _FakeController(
            snapshot=_snapshot("idle", "Warehouse scan idle.")
        )

        with self._patched_app(engine=engine, controller=controller):
            with self.assertRaises(HTTPException) as cm:
                web_app.api_warehouse_scan()

        self.assertEqual(cm.exception.status_code, 409)
        detail = cm.exception.detail
        self.assertEqual(detail["error"], "warehouse_scan_conflict")
        self.assertTrue(detail["engine_running"])
        self.assertEqual(controller.start_calls, 0)
        self.assertEqual(engine.start_calls, 0)

    def test_scan_rejects_when_device_is_offline_before_controller_start(self):
        engine = _FakeEngine(status_payload={"running": False, "device_online": False})
        controller = _FakeController(
            snapshot=_snapshot("idle", "Warehouse scan idle.")
        )

        with self._patched_app(engine=engine, controller=controller):
            with self.assertRaises(HTTPException) as cm:
                web_app.api_warehouse_scan()

        self.assertEqual(cm.exception.status_code, 503)
        detail = cm.exception.detail
        self.assertEqual(detail["error"], "warehouse_scan_unavailable")
        self.assertFalse(detail["device_online"])
        self.assertEqual(controller.start_calls, 0)
        self.assertEqual(engine.start_calls, 0)

    def test_stop_requests_active_scan(self):
        controller = _FakeController(
            snapshot=_snapshot("running", "Warehouse scan started.")
        )

        with self._patched_app(controller=controller):
            response = web_app.api_warehouse_stop()

        self.assertEqual(response["status"], "stopping")
        self.assertEqual(response["message"], "Warehouse scan stop requested.")
        self.assertEqual(controller.stop_calls, 1)

    def test_stop_returns_conflict_when_scan_becomes_terminal_before_stop_completes(self):
        controller = _FakeController(
            snapshot=_snapshot("running", "Warehouse scan started."),
            stop_message="No warehouse scan running.",
            stop_snapshot=_snapshot("success", "Completed successfully."),
        )

        with self._patched_app(controller=controller):
            with self.assertRaises(HTTPException) as cm:
                web_app.api_warehouse_stop()

        self.assertEqual(cm.exception.status_code, 409)
        detail = cm.exception.detail
        self.assertEqual(detail["error"], "warehouse_scan_not_active")
        self.assertEqual(detail["controller_status"], "success")
        self.assertEqual(detail["message"], "No warehouse scan running.")
        self.assertEqual(detail["snapshot"], controller.snapshot_payload)
        self.assertEqual(controller.stop_calls, 1)

    def test_stop_rejects_idle_and_terminal_scans(self):
        for status in ("idle", "success", "partial", "failed", "stopped"):
            with self.subTest(status=status):
                controller = _FakeController(
                    snapshot=_snapshot(status, f"Warehouse scan {status}.")
                )
                with self._patched_app(controller=controller):
                    with self.assertRaises(HTTPException) as cm:
                        web_app.api_warehouse_stop()

                self.assertEqual(cm.exception.status_code, 409)
                detail = cm.exception.detail
                self.assertEqual(detail["error"], "warehouse_scan_not_active")
                self.assertEqual(detail["controller_status"], status)
                self.assertEqual(controller.stop_calls, 0)

    def test_items_reads_filtered_catalog_and_closes_store_without_starting_scan(self):
        engine = _FakeEngine(status_payload={"running": False, "device_online": True})
        controller = _FakeController(
            snapshot=_snapshot("idle", "Warehouse scan idle.")
        )
        created_stores: list[_FakeStore] = []
        items = [
            {
                "id": 1,
                "category_code": "items",
                "name_raw": "绮崏",
                "name_normalized": "绮崏",
                "quantity_text": "12",
                "ocr_confidence": 0.99,
                "icon_hash": "abc",
                "icon_path": "artifacts/warehouse/icons/items/abc.bin",
                "card_path": "artifacts/warehouse/cards/items/abc.bin",
                "first_seen_at": "2026-08-09T00:00:00+00:00",
                "last_seen_at": "2026-08-09T00:00:00+00:00",
                "page_index": 0,
                "screen_path": "runs/warehouse/page-0.png",
                "bbox": [1, 2, 3, 4],
                "needs_review": False,
            }
        ]

        def store_factory(path: Path) -> _FakeStore:
            store = _FakeStore(path=path, items=items)
            created_stores.append(store)
            return store

        with self._patched_app(
            engine=engine,
            controller=controller,
            store_cls=store_factory,
        ):
            response = web_app.api_warehouse_items(category="items")

        self.assertEqual(response["category"], "items")
        self.assertEqual(response["items"], items)
        self.assertEqual(len(created_stores), 1)
        self.assertTrue(created_stores[0].opened)
        self.assertTrue(created_stores[0].closed)
        self.assertEqual(created_stores[0].category_code, "items")
        self.assertEqual(controller.start_calls, 0)
        self.assertEqual(engine.start_calls, 0)

    def _patched_app(
        self,
        *,
        engine: _FakeEngine | None = None,
        controller: _FakeController | None = None,
        store_cls=None,
    ):
        return _PatchedAppContext(
            engine=engine or _FakeEngine(status_payload={"running": False, "device_online": True}),
            controller=controller or _FakeController(snapshot=_snapshot("idle", "Warehouse scan idle.")),
            store_cls=store_cls,
        )


class _PatchedAppContext:
    def __init__(self, *, engine: _FakeEngine, controller: _FakeController, store_cls) -> None:
        self._engine = engine
        self._controller = controller
        self._store_cls = store_cls
        self._patches = []

    def __enter__(self):
        self._patches = [
            patch.object(web_app, "engine", self._engine),
            patch.object(web_app, "warehouse_controller", self._controller),
        ]
        if self._store_cls is not None:
            self._patches.append(patch.object(web_app, "WarehouseCatalogStore", self._store_cls))
        for active_patch in self._patches:
            active_patch.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for active_patch in reversed(self._patches):
            active_patch.stop()


class _FakeEngine:
    def __init__(self, *, status_payload: dict[str, object]) -> None:
        self._status_payload = dict(status_payload)
        self.start_calls = 0

    def status(self) -> dict[str, object]:
        return dict(self._status_payload)

    def start(self, *args, **kwargs):
        self.start_calls += 1
        raise AssertionError("Warehouse routes must not call engine.start().")


class _FakeController:
    def __init__(
        self,
        *,
        snapshot: dict[str, object],
        start_message: str = "Warehouse scan started.",
        stop_message: str = "Warehouse scan stop requested.",
        stop_snapshot: dict[str, object] | None = None,
    ) -> None:
        self.snapshot_payload = dict(snapshot)
        self.start_message = start_message
        self.stop_message = stop_message
        self.stop_snapshot = dict(stop_snapshot) if stop_snapshot is not None else None
        self.start_calls = 0
        self.stop_calls = 0
        self._database_path = Path("data/warehouse_catalog/catalog.db")

    @property
    def database_path(self) -> Path:
        return self._database_path

    def start(self) -> str:
        self.start_calls += 1
        self.snapshot_payload["status"] = "running"
        self.snapshot_payload["message"] = "Warehouse scan started."
        return self.start_message

    def stop(self) -> str:
        self.stop_calls += 1
        if self.stop_snapshot is not None:
            self.snapshot_payload = dict(self.stop_snapshot)
            return self.stop_message
        self.snapshot_payload["status"] = "stopping"
        self.snapshot_payload["message"] = "Warehouse scan stop requested."
        return self.stop_message

    def snapshot(self) -> dict[str, object]:
        return dict(self.snapshot_payload)


class _FakeStore:
    def __init__(self, *, path: Path, items: list[dict[str, object]]) -> None:
        self.path = Path(path)
        self.items = list(items)
        self.opened = False
        self.closed = False
        self.category_code: str | None = None

    def open(self) -> None:
        self.opened = True

    def get_items(self, category_code: str | None = None) -> list[dict[str, object]]:
        self.category_code = category_code
        return list(self.items)

    def close(self) -> None:
        self.closed = True


def _snapshot(status: str, message: str) -> dict[str, object]:
    return {
        "status": status,
        "scan_id": None,
        "category": None,
        "page": None,
        "categories_completed": 0,
        "items_found": 0,
        "low_confidence_count": 0,
        "message": message,
    }


if __name__ == "__main__":
    unittest.main()
