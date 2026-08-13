"""Bounded warehouse catalog scanner."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.vision.match import TemplateMatcher
from src.warehouse.models import ItemObservation, WarehouseScanResult
from src.warehouse.parser import parse_visible_cards


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class _CollectedPage:
    observations: list[ItemObservation]
    fingerprint: str


@dataclass(frozen=True)
class _CategoryScanOutcome:
    stopped: bool = False


class WarehouseScanner:
    def __init__(
        self,
        ctx,
        store,
        config: dict,
        ocr_backend,
        stop_event=None,
        progress_callback=None,
    ) -> None:
        self.ctx = ctx
        self.store = store
        self.config = config
        self.ocr_backend = ocr_backend
        self.stop_event = stop_event
        self.progress_callback = progress_callback or (lambda **kwargs: None)
        self.categories = list(config.get("categories", []))
        self.navigation = dict(config.get("navigation", {}))
        self.max_swipes = int(config.get("max_swipes_per_category", 30))
        self.no_new_page_limit = int(config.get("no_new_page_limit", 2))
        self.max_return_rounds = min(
            2,
            max(0, int(self.navigation.get("max_return_rounds", 2))),
        )
        artifact_dir = config.get("artifact_dir", "runs/warehouse")
        self.artifact_dir = self._resolve_artifact_dir(artifact_dir)

    def scan(self) -> WarehouseScanResult:
        scan_id = ""
        categories_completed = 0
        try:
            scan_id = self.store.start_scan()
            self._emit_progress(scan_id=scan_id, message="Warehouse scan started.")
            self._open_warehouse()

            for category in self.categories:
                if self._stop_requested():
                    return self._finish_with_status(
                        scan_id,
                        status="stopped",
                        message="Stop requested before next category.",
                    )
                outcome = self._scan_category(scan_id, category)
                if outcome.stopped:
                    return self._finish_with_status(
                        scan_id,
                        status="stopped",
                        message=f"Stop requested while scanning {category['code']}.",
                    )
                self.store.record_category_completion(scan_id, str(category["code"]))
                categories_completed += 1
                self._emit_progress(
                    scan_id=scan_id,
                    category=str(category["code"]),
                    categories_completed=categories_completed,
                    message=f"Completed category {category['code']}.",
                )

            if not self._close_to_main_city():
                return self.store.finish_scan(
                    scan_id,
                    status="partial",
                    message="Scan finished but could not verify return to main city.",
                )
            return self.store.finish_scan(scan_id, status="success")
        except Exception as exc:  # noqa: BLE001
            if scan_id:
                return self._finish_with_status(
                    scan_id,
                    status="failed",
                    message=str(exc),
                )
            raise
        finally:
            self.store.close()

    def _open_warehouse(self) -> None:
        entry_template = self.navigation["warehouse_entry_template"]
        entry_tap = self._point(self.navigation["warehouse_entry_tap"], "warehouse_entry_tap")
        attempts = max(1, int(self.navigation.get("max_open_attempts", 2)))

        if self._is_warehouse_ready():
            return

        for _ in range(attempts):
            screen = self.ctx.screenshot()
            if self._warehouse_ready_matches(screen):
                return
            if not self._tap_if_visible(screen, entry_template, entry_tap):
                raise RuntimeError(
                    f"Warehouse entry template '{entry_template}' was not visible on the current screen."
                )
            if self._wait_for_warehouse_ready():
                return
            if not self._is_visible(self.navigation["main_city_template"]):
                raise RuntimeError("Warehouse page did not become ready after opening.")

        raise RuntimeError("Failed to open warehouse within bounded attempts.")

    def _scan_category(self, scan_id: str, category: dict[str, Any]) -> _CategoryScanOutcome:
        category_code = str(category["code"])
        self._emit_progress(
            scan_id=scan_id,
            category=category_code,
            page=0,
            message=f"Scanning category {category_code}.",
        )
        self._select_category(category)
        seen_fingerprints: set[str] = set()
        repeated_pages = 0
        swipes = 0
        page_index = 0

        while True:
            page = self._collect_page(scan_id, str(category["code"]), page_index)
            if page.fingerprint in seen_fingerprints:
                repeated_pages += 1
            else:
                seen_fingerprints.add(page.fingerprint)
                repeated_pages = 0
                if page.observations:
                    self.store.upsert_page(scan_id, page.observations)

            if repeated_pages >= self.no_new_page_limit:
                return _CategoryScanOutcome(stopped=False)
            if self._stop_requested():
                return _CategoryScanOutcome(stopped=True)
            if swipes >= self.max_swipes:
                return _CategoryScanOutcome(stopped=False)

            self._advance_page()
            swipes += 1
            page_index += 1

    def _select_category(self, category: dict[str, Any]) -> None:
        screen = self.ctx.screenshot()
        template_name = str(category["tab_template"])
        tap_point = self._point(category["tab_tap"], f"{category['code']}.tab_tap")
        if not self._tap_if_visible(screen, template_name, tap_point):
            raise RuntimeError(
                f"Warehouse tab template '{template_name}' was not visible for category '{category['code']}'."
            )
        if not self._wait_for_warehouse_ready():
            raise RuntimeError(f"Warehouse page was not ready after selecting '{category['code']}'.")

    def _collect_page(self, scan_id: str, category_code: str, page_index: int) -> _CollectedPage:
        self._emit_progress(
            scan_id=scan_id,
            category=category_code,
            page=page_index,
            message=f"Scanning {category_code} page {page_index}.",
        )
        screen = self.ctx.screenshot()
        screen_path = self._save_screen(scan_id, category_code, page_index, screen)
        layout = {
            "category_code": category_code,
            "page_index": page_index,
            "screen_path": screen_path,
            "ocr_threshold": self.config.get("ocr_threshold", 0.70),
            "grid": self.config["grid"],
            "rois": self.config["rois"],
        }
        observations = parse_visible_cards(screen, layout, self.ocr_backend)
        fingerprint = self._fingerprint_page(screen, observations)
        return _CollectedPage(observations=observations, fingerprint=fingerprint)

    def _advance_page(self) -> None:
        start = self._point(self.navigation["swipe_start"], "swipe_start")
        end = self._point(self.navigation["swipe_end"], "swipe_end")
        duration = int(self.navigation.get("swipe_duration_ms", 350))
        self.ctx.device.swipe(start[0], start[1], end[0], end[1], duration_ms=duration)

    def _close_to_main_city(self) -> bool:
        main_template = self.navigation["main_city_template"]
        back_template = self.navigation["warehouse_back_template"]
        back_tap = self._point(self.navigation["warehouse_back_tap"], "warehouse_back_tap")

        if self._is_visible(main_template):
            return True
        screen = self.ctx.screenshot()
        if not self._tap_if_visible(screen, back_template, back_tap):
            return False
        return self._is_visible(main_template)

    def _safe_return_to_main_city(self, max_rounds: int) -> bool:
        if max_rounds < 0:
            raise ValueError("max_rounds must be non-negative")
        main_template = self.navigation["main_city_template"]
        back_template = self.navigation["warehouse_back_template"]
        back_tap = self._point(self.navigation["warehouse_back_tap"], "warehouse_back_tap")

        for _ in range(max_rounds):
            if self._is_visible(main_template):
                return True
            screen = self.ctx.screenshot()
            if self._tap_if_visible(screen, back_template, back_tap):
                if self._is_visible(main_template):
                    return True
                continue
            self.ctx.device.back()
            if self._is_visible(main_template):
                return True
        return self._is_visible(main_template)

    def _finish_with_status(
        self,
        scan_id: str,
        *,
        status: str,
        message: str,
    ) -> WarehouseScanResult:
        self._safe_return_to_main_city(max_rounds=self.max_return_rounds)
        return self.store.finish_scan(
            scan_id,
            status=status,
            message=message,
        )

    def _tap_if_visible(
        self,
        screen: np.ndarray,
        template_name: str,
        tap_point: tuple[int, int],
    ) -> bool:
        if not self._has_match(screen, template_name):
            return False
        self.ctx.device.tap(tap_point[0], tap_point[1])
        return True

    def _has_match(self, screen: np.ndarray, template_name: str) -> bool:
        return self.ctx.matcher.find(screen, template_name) is not None

    def _is_visible(self, template_name: str) -> bool:
        return self._has_match(self.ctx.screenshot(), template_name)

    def _is_warehouse_ready(self) -> bool:
        return self._warehouse_ready_matches(self.ctx.screenshot())

    def _warehouse_ready_matches(self, screen: np.ndarray) -> bool:
        ready_template = self._warehouse_ready_template()
        if self._has_match(screen, ready_template):
            return True
        title_template = self.navigation.get("warehouse_title_template")
        return bool(title_template) and str(title_template) != ready_template and self._has_match(
            screen,
            str(title_template),
        )

    def _warehouse_ready_template(self) -> str:
        return str(
            self.navigation.get(
                "warehouse_ready_template",
                self.navigation["warehouse_back_template"],
            )
        )

    def _wait_for_warehouse_ready(self) -> bool:
        timeout = max(
            0.0,
            float(self.navigation.get("warehouse_ready_timeout_seconds", 4.0)),
        )
        poll_interval = max(
            0.0,
            float(self.navigation.get("warehouse_ready_poll_interval_seconds", 0.5)),
        )
        deadline = time.monotonic() + timeout
        while True:
            if self._is_warehouse_ready():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_interval)

    def _stop_requested(self) -> bool:
        return self.stop_event is not None and bool(self.stop_event.is_set())

    def _emit_progress(self, **progress: Any) -> None:
        self.progress_callback(**progress)

    def _save_screen(
        self,
        scan_id: str,
        category_code: str,
        page_index: int,
        screen: np.ndarray,
    ) -> str:
        destination = self.artifact_dir / f"{scan_id}_{category_code}_page_{page_index:02d}.png"
        TemplateMatcher.imwrite(destination, screen)
        return destination.relative_to(PROJECT_ROOT).as_posix()

    def _resolve_artifact_dir(self, artifact_dir: str | Path) -> Path:
        raw = Path(artifact_dir)
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = (PROJECT_ROOT / raw).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError(
                f"artifact_dir must stay inside the project root; got {resolved}"
            ) from exc
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _point(self, value: Any, field_name: str) -> tuple[int, int]:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"{field_name} must be a 2-item coordinate pair")
        return int(value[0]), int(value[1])

    def _fingerprint_page(
        self,
        screen: np.ndarray,
        observations: list[ItemObservation],
    ) -> str:
        normalized = cv2.resize(screen, (135, 240), interpolation=cv2.INTER_AREA)
        screen_hash = hashlib.sha256(normalized.tobytes()).hexdigest()
        item_hashes = "|".join(sorted(observation.icon_hash for observation in observations))
        return hashlib.sha256(f"{screen_hash}|{item_hashes}".encode("utf-8")).hexdigest()
