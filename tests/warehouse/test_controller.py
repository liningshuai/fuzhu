from __future__ import annotations

import threading
import unittest
from pathlib import Path

from src.tasks.base import TaskContext
from src.warehouse.models import WarehouseScanResult


class WarehouseScanControllerTests(unittest.TestCase):
    def test_stop_preserves_terminal_snapshot_before_worker_thread_clears(self):
        from src.warehouse.controller import WarehouseScanController

        class _PublishingPauseController(WarehouseScanController):
            def __init__(self, *args, published_event: threading.Event, release_event: threading.Event, **kwargs):
                super().__init__(*args, **kwargs)
                self._published_event = published_event
                self._release_event = release_event

            def _publish_result(self, result: WarehouseScanResult) -> None:
                super()._publish_result(result)
                self._published_event.set()
                self._release_event.wait(timeout=1)

        scenario = _ControllerScenario(
            progress_updates=[
                {
                    "scan_id": "scan-final-window",
                    "category": "items",
                    "page": 2,
                    "message": "Publishing final result.",
                }
            ],
            result=WarehouseScanResult(
                status="success",
                scan_id="scan-final-window",
                categories_completed=4,
                items_found=11,
                low_confidence_count=0,
                message="Completed successfully.",
            ),
        )
        published = threading.Event()
        release = threading.Event()
        controller = _PublishingPauseController(
            engine=_FakeEngine(),
            config_loader=lambda: {"categories": []},
            scanner_cls=_make_scanner_cls(scenario),
            store_cls=_make_store_cls(scenario),
            ocr_backend_factory=scenario.build_ocr_backend,
            join_timeout=0.01,
            published_event=published,
            release_event=release,
        )

        self.assertEqual(controller.start(), "Warehouse scan started.")
        self.assertTrue(published.wait(timeout=1))

        snapshot_before_stop = controller.snapshot()
        self.assertEqual(snapshot_before_stop["status"], "success")
        self.assertEqual(snapshot_before_stop["message"], "Completed successfully.")

        self.assertEqual(controller.stop(), "Warehouse scan stop requested.")
        snapshot_after_stop = controller.snapshot()
        self.assertEqual(snapshot_after_stop["status"], "success")
        self.assertEqual(snapshot_after_stop["message"], "Completed successfully.")

        release.set()
        self.assertTrue(scenario.finished.wait(timeout=1))

    def test_start_rejects_duplicate_scan_and_uses_one_daemon_worker(self):
        from src.warehouse.controller import WarehouseScanController

        scenario = _ControllerScenario(
            progress_updates=[
                {
                    "scan_id": "scan-dup",
                    "category": "items",
                    "page": 0,
                    "message": "Scanning first page.",
                }
            ],
            result=WarehouseScanResult(
                status="success",
                scan_id="scan-dup",
                categories_completed=5,
                items_found=8,
                low_confidence_count=0,
                message="Completed duplicate-start scenario.",
            ),
            wait_for_release=True,
        )
        engine = _FakeEngine()
        controller = WarehouseScanController(
            engine=engine,
            config_loader=lambda: {"categories": []},
            scanner_cls=_make_scanner_cls(scenario),
            store_cls=_make_store_cls(scenario),
            ocr_backend_factory=scenario.build_ocr_backend,
            join_timeout=0.01,
        )

        self.assertEqual(scenario.ocr_factory_calls, 0)
        self.assertEqual(controller.start(), "Warehouse scan started.")
        self.assertTrue(scenario.started.wait(timeout=1))
        self.assertEqual(controller.start(), "Warehouse scan already running.")
        self.assertEqual(scenario.scanner_init_count, 1)
        self.assertTrue(scenario.worker_thread_daemon)
        self.assertEqual(scenario.ocr_factory_calls, 1)
        self.assertEqual(engine.start_calls, 0)
        self.assertEqual(engine.stop_calls, 0)

        scenario.release.set()
        self.assertTrue(scenario.finished.wait(timeout=1))

    def test_start_rejects_when_bot_engine_is_running(self):
        from src.warehouse.controller import WarehouseScanController

        scenario = _ControllerScenario(
            progress_updates=[],
            result=WarehouseScanResult(
                status="success",
                scan_id="scan-never",
                categories_completed=0,
                items_found=0,
                low_confidence_count=0,
                message="should not run",
            ),
        )
        engine = _FakeEngine(running=True)
        controller = WarehouseScanController(
            engine=engine,
            config_loader=lambda: {"categories": []},
            scanner_cls=_make_scanner_cls(scenario),
            store_cls=_make_store_cls(scenario),
            ocr_backend_factory=scenario.build_ocr_backend,
        )

        self.assertEqual(controller.start(), "Stop the bot engine before scanning the warehouse.")
        self.assertEqual(scenario.scanner_init_count, 0)
        self.assertEqual(scenario.store_init_count, 0)
        self.assertEqual(scenario.ocr_factory_calls, 0)
        self.assertEqual(engine.start_calls, 0)
        self.assertEqual(engine.stop_calls, 0)

    def test_stop_sets_event_and_returns_without_waiting_for_unbounded_cleanup(self):
        from src.warehouse.controller import WarehouseScanController

        scenario = _ControllerScenario(
            progress_updates=[
                {
                    "scan_id": "scan-stop",
                    "category": "items",
                    "page": 1,
                    "message": "Waiting for stop.",
                }
            ],
            result=WarehouseScanResult(
                status="stopped",
                scan_id="scan-stop",
                categories_completed=1,
                items_found=3,
                low_confidence_count=1,
                message="Stopped by request.",
            ),
            wait_for_stop=True,
            wait_for_release_after_stop=True,
        )
        controller = WarehouseScanController(
            engine=_FakeEngine(),
            config_loader=lambda: {"categories": []},
            scanner_cls=_make_scanner_cls(scenario),
            store_cls=_make_store_cls(scenario),
            ocr_backend_factory=scenario.build_ocr_backend,
            join_timeout=0.01,
        )

        self.assertEqual(controller.start(), "Warehouse scan started.")
        self.assertTrue(scenario.started.wait(timeout=1))

        self.assertEqual(controller.stop(), "Warehouse scan stop requested.")
        self.assertTrue(scenario.stop_seen.wait(timeout=1))
        self.assertEqual(controller.snapshot()["status"], "stopping")

        scenario.release.set()
        self.assertTrue(scenario.finished.wait(timeout=1))
        final_snapshot = controller.snapshot()
        self.assertEqual(final_snapshot["status"], "stopped")
        self.assertEqual(final_snapshot["scan_id"], "scan-stop")
        self.assertEqual(final_snapshot["items_found"], 3)
        self.assertEqual(final_snapshot["low_confidence_count"], 1)
        self.assertEqual(final_snapshot["message"], "Stopped by request.")

    def test_snapshot_publishes_progress_final_result_and_project_local_store_path(self):
        from src.warehouse.controller import WarehouseScanController

        scenario = _ControllerScenario(
            progress_updates=[
                {
                    "scan_id": "scan-123",
                    "category": "skill_fragments",
                    "page": 4,
                    "categories_completed": 2,
                    "items_found": 7,
                    "low_confidence_count": 1,
                    "message": "Scanning skill fragments page 4.",
                }
            ],
            result=WarehouseScanResult(
                status="partial",
                scan_id="scan-123",
                categories_completed=3,
                items_found=9,
                low_confidence_count=2,
                message="Lost warehouse title during category 4.",
            ),
        )
        engine = _FakeEngine()
        controller = WarehouseScanController(
            engine=engine,
            config_loader=lambda: {"categories": []},
            scanner_cls=_make_scanner_cls(scenario),
            store_cls=_make_store_cls(scenario),
            ocr_backend_factory=scenario.build_ocr_backend,
        )

        self.assertEqual(controller.start(), "Warehouse scan started.")
        self.assertTrue(scenario.finished.wait(timeout=1))

        snapshot = controller.snapshot()
        expected_db = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "warehouse_catalog"
            / "catalog.db"
        )
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["scan_id"], "scan-123")
        self.assertEqual(snapshot["category"], "skill_fragments")
        self.assertEqual(snapshot["page"], 4)
        self.assertEqual(snapshot["categories_completed"], 3)
        self.assertEqual(snapshot["items_found"], 9)
        self.assertEqual(snapshot["low_confidence_count"], 2)
        self.assertEqual(snapshot["message"], "Lost warehouse title during category 4.")
        self.assertEqual(scenario.store_path, expected_db)
        self.assertTrue(scenario.store_opened)
        self.assertTrue(scenario.store_closed)
        self.assertIsInstance(scenario.scanner_ctx, TaskContext)
        self.assertIs(scenario.scanner_ctx.device, engine.device)
        self.assertIs(scenario.scanner_ctx.matcher, engine.matcher)
        self.assertIs(scenario.scanner_ctx.session_guard, engine.session_guard)
        self.assertEqual(engine.created_contexts, 1)


class _FakeEngine:
    def __init__(self, *, running: bool = False) -> None:
        self._running = running
        self.device = object()
        self.matcher = object()
        self.session_guard = object()
        self.start_calls = 0
        self.stop_calls = 0
        self.created_contexts = 0

    def status(self) -> dict[str, object]:
        return {"running": self._running}

    def _new_task_context(self) -> TaskContext:
        self.created_contexts += 1
        return TaskContext(
            device=self.device,
            matcher=self.matcher,
            session_guard=self.session_guard,
        )

    def start(self, *args, **kwargs):
        self.start_calls += 1
        raise AssertionError("Warehouse controller must not start the bot engine.")

    def stop(self, *args, **kwargs):
        self.stop_calls += 1
        raise AssertionError("Warehouse controller must not stop the bot engine.")


class _ControllerScenario:
    def __init__(
        self,
        *,
        progress_updates: list[dict[str, object]],
        result: WarehouseScanResult,
        wait_for_release: bool = False,
        wait_for_stop: bool = False,
        wait_for_release_after_stop: bool = False,
    ) -> None:
        self.progress_updates = progress_updates
        self.result = result
        self.wait_for_release = wait_for_release
        self.wait_for_stop = wait_for_stop
        self.wait_for_release_after_stop = wait_for_release_after_stop
        self.started = threading.Event()
        self.release = threading.Event()
        self.stop_seen = threading.Event()
        self.finished = threading.Event()
        self.worker_thread_daemon = False
        self.scanner_init_count = 0
        self.store_init_count = 0
        self.store_opened = False
        self.store_closed = False
        self.store_path: Path | None = None
        self.scanner_ctx: TaskContext | None = None
        self.ocr_factory_calls = 0

    def build_ocr_backend(self) -> object:
        self.ocr_factory_calls += 1
        return object()

    def run(
        self,
        *,
        progress_callback,
        stop_event: threading.Event | None,
    ) -> WarehouseScanResult:
        self.started.set()
        self.worker_thread_daemon = threading.current_thread().daemon
        for update in self.progress_updates:
            progress_callback(**update)
        if self.wait_for_release:
            self.release.wait(timeout=1)
        if self.wait_for_stop:
            assert stop_event is not None
            stop_event.wait(timeout=1)
            if stop_event.is_set():
                self.stop_seen.set()
        if self.wait_for_release_after_stop:
            self.release.wait(timeout=1)
        self.finished.set()
        return self.result


def _make_store_cls(scenario: _ControllerScenario):
    class _FakeStore:
        def __init__(self, path: Path) -> None:
            scenario.store_init_count += 1
            scenario.store_path = Path(path)

        def open(self) -> None:
            scenario.store_opened = True

        def close(self) -> None:
            scenario.store_closed = True

    return _FakeStore


def _make_scanner_cls(scenario: _ControllerScenario):
    class _FakeScanner:
        def __init__(
            self,
            ctx,
            store,
            config,
            ocr_backend,
            stop_event=None,
            progress_callback=None,
        ) -> None:
            scenario.scanner_init_count += 1
            scenario.scanner_ctx = ctx
            self.stop_event = stop_event
            self.progress_callback = progress_callback or (lambda **kwargs: None)

        def scan(self) -> WarehouseScanResult:
            return scenario.run(
                progress_callback=self.progress_callback,
                stop_event=self.stop_event,
            )

    return _FakeScanner


if __name__ == "__main__":
    unittest.main()
