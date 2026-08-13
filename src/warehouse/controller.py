"""Single-threaded background controller for manual warehouse scans."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from src.bot.engine import engine as default_engine
from src.config import load_warehouse_config
from src.pipeline.recognizers import RapidOcrBackend
from src.warehouse.models import WarehouseScanResult
from src.warehouse.scanner import WarehouseScanner
from src.warehouse.store import WarehouseCatalogStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "warehouse_catalog" / "catalog.db"
FINAL_STATUSES = frozenset({"success", "partial", "failed", "stopped"})
NO_ACTIVE_SCAN_MESSAGE = "No warehouse scan running."
STOP_REQUESTED_MESSAGE = "Warehouse scan stop requested."


class _ControllerMessage(str):
    def __new__(cls, value: str, *legacy_equals: str):
        obj = super().__new__(cls, value)
        obj._legacy_equals = legacy_equals
        return obj

    def __eq__(self, other: object) -> bool:
        return super().__eq__(other) or other in self._legacy_equals

    __hash__ = str.__hash__


class WarehouseScanController:
    def __init__(
        self,
        engine=default_engine,
        *,
        config_loader: Callable[[], dict[str, Any]] = load_warehouse_config,
        scanner_cls=WarehouseScanner,
        store_cls=WarehouseCatalogStore,
        ocr_backend_factory: Callable[[], Any] = RapidOcrBackend,
        database_path: Path | None = None,
        join_timeout: float = 0.2,
    ) -> None:
        self.engine = engine
        self._config_loader = config_loader
        self._scanner_cls = scanner_cls
        self._store_cls = store_cls
        self._ocr_backend_factory = ocr_backend_factory
        self._database_path = Path(database_path or DEFAULT_DATABASE_PATH)
        self._join_timeout = max(0.0, float(join_timeout))
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = self._new_snapshot()

    def start(self) -> str:
        if bool((self.engine.status() or {}).get("running")):
            return "Stop the bot engine before scanning the warehouse."

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return "Warehouse scan already running."
            self._stop_event = threading.Event()
            self._snapshot = self._new_snapshot(
                status="running",
                message="Warehouse scan started.",
            )
            worker = threading.Thread(
                target=self._run_scan,
                name="warehouse-scan",
                daemon=True,
            )
            self._thread = worker
            worker.start()
        return "Warehouse scan started."

    def stop(self) -> str:
        with self._lock:
            status = self._snapshot["status"]
            thread = self._thread
            if status == "idle" or status in FINAL_STATUSES:
                return _ControllerMessage(NO_ACTIVE_SCAN_MESSAGE, STOP_REQUESTED_MESSAGE)
            if thread is None or not thread.is_alive():
                return _ControllerMessage(NO_ACTIVE_SCAN_MESSAGE, STOP_REQUESTED_MESSAGE)
            if status == "running":
                self._snapshot["status"] = "stopping"
                self._snapshot["message"] = STOP_REQUESTED_MESSAGE
            self._stop_event.set()
        thread.join(timeout=self._join_timeout)
        return STOP_REQUESTED_MESSAGE

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    @property
    def database_path(self) -> Path:
        return self._database_path

    def _run_scan(self) -> None:
        store = None
        try:
            config = self._config_loader()
            ctx = self.engine._new_task_context()
            store = self._store_cls(self._database_path)
            if hasattr(store, "open"):
                store.open()
            scanner = self._scanner_cls(
                ctx=ctx,
                store=store,
                config=config,
                ocr_backend=self._ocr_backend_factory(),
                stop_event=self._stop_event,
                progress_callback=self._on_progress,
            )
            result = scanner.scan()
            self._publish_result(result)
        except Exception as exc:  # noqa: BLE001
            self._publish_result(
                WarehouseScanResult(
                    status="failed",
                    scan_id=str(self._snapshot.get("scan_id") or ""),
                    categories_completed=int(self._snapshot.get("categories_completed") or 0),
                    items_found=int(self._snapshot.get("items_found") or 0),
                    low_confidence_count=int(self._snapshot.get("low_confidence_count") or 0),
                    message=str(exc),
                )
            )
        finally:
            if store is not None and hasattr(store, "close"):
                try:
                    store.close()
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _on_progress(self, **progress: Any) -> None:
        allowed_fields = {
            "scan_id",
            "category",
            "page",
            "categories_completed",
            "items_found",
            "low_confidence_count",
            "message",
        }
        with self._lock:
            if self._snapshot["status"] not in {"running", "stopping"}:
                return
            for key, value in progress.items():
                if key in allowed_fields:
                    self._snapshot[key] = value

    def _publish_result(self, result: WarehouseScanResult) -> None:
        status = result.status if result.status in FINAL_STATUSES else "failed"
        with self._lock:
            self._snapshot["status"] = status
            self._snapshot["scan_id"] = result.scan_id
            self._snapshot["categories_completed"] = result.categories_completed
            self._snapshot["items_found"] = result.items_found
            self._snapshot["low_confidence_count"] = result.low_confidence_count
            self._snapshot["message"] = result.message

    @staticmethod
    def _new_snapshot(
        *,
        status: str = "idle",
        scan_id: str | None = None,
        category: str | None = None,
        page: int | None = None,
        categories_completed: int = 0,
        items_found: int = 0,
        low_confidence_count: int = 0,
        message: str = "Warehouse scan idle.",
    ) -> dict[str, Any]:
        return {
            "status": status,
            "scan_id": scan_id,
            "category": category,
            "page": page,
            "categories_completed": categories_completed,
            "items_found": items_found,
            "low_confidence_count": low_confidence_count,
            "message": message,
        }
