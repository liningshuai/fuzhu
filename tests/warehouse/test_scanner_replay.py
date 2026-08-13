from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np

from src.vision.match import MatchResult
from src.warehouse.models import ItemObservation, WarehouseScanResult
from src.warehouse.scanner import WarehouseScanner


class WarehouseScannerReplayTests(unittest.TestCase):
    def test_scan_uses_stable_back_template_when_title_match_is_unreliable(self):
        config = _warehouse_config(no_new_page_limit=1)
        config["categories"] = [config["categories"][0]]
        scenario = _ReplayScenario(
            config=config,
            category_pages={"items": ["items-0", "items-0"]},
            warehouse_title_visible=False,
        )
        store = _FakeStore()
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.categories_completed, 1)
        self.assertEqual(scenario.location, "main_city")

    def test_scan_completes_all_five_categories_and_returns_to_main_city(self):
        config = _warehouse_config(no_new_page_limit=1)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-1", "items-1"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
        )
        store = _FakeStore()
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "success")
        self.assertEqual(result.categories_completed, 5)
        self.assertEqual(
            store.completed_categories,
            [
                "items",
                "skill_fragments",
                "arms_fragments",
                "treasure_fragments",
                "specialties",
            ],
        )
        self.assertEqual(scenario.location, "main_city")
        self.assertEqual(
            {tap for tap in scenario.device_taps},
            {
                tuple(config["navigation"]["warehouse_entry_tap"]),
                tuple(config["navigation"]["warehouse_back_tap"]),
                tuple(config["categories"][0]["tab_tap"]),
                tuple(config["categories"][1]["tab_tap"]),
                tuple(config["categories"][2]["tab_tap"]),
                tuple(config["categories"][3]["tab_tap"]),
                tuple(config["categories"][4]["tab_tap"]),
            },
        )
        self.assertNotIn((120, 520), scenario.device_taps)
        self.assertNotIn((930, 1780), scenario.device_taps)

    def test_scan_stops_on_repeated_page_without_persisting_duplicate_page(self):
        config = _warehouse_config(no_new_page_limit=1)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-1", "items-1"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
        )
        store = _FakeStore()
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "success")
        item_pages = [
            observations[0].page_index
            for scan_id, observations in store.upserted_pages
            if observations and observations[0].category_code == "items"
        ]
        self.assertEqual(item_pages, [0, 1])

    def test_scan_respects_max_swipe_bound(self):
        config = _warehouse_config(max_swipes_per_category=1, no_new_page_limit=4)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-1", "items-2"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
        )
        store = _FakeStore()
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "success")
        self.assertEqual(len(scenario.device_swipes), 5)
        item_pages = [
            observations[0].page_index
            for scan_id, observations in store.upserted_pages
            if observations and observations[0].category_code == "items"
        ]
        self.assertEqual(item_pages, [0, 1])

    def test_scan_preserves_low_confidence_card_evidence(self):
        config = _warehouse_config(no_new_page_limit=1)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["needs-review-0", "needs-review-0"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
            page_payloads={
                "needs-review-0": [
                    _ObservationSpec(
                        icon_hash="needs-review",
                        name_raw="",
                        name_normalized="",
                        quantity_text="99",
                        needs_review=True,
                        ocr_confidence=0.0,
                    )
                ]
            },
        )
        store = _FakeStore()
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "success")
        first_page = store.upserted_pages[0][1]
        self.assertEqual(len(first_page), 1)
        observation = first_page[0]
        self.assertEqual(observation.name_raw, "")
        self.assertEqual(observation.name_normalized, "")
        self.assertEqual(observation.quantity_text, "99")
        self.assertTrue(observation.needs_review)
        self.assertGreater(len(observation.icon_bytes), 0)
        self.assertGreater(len(observation.card_bytes), 0)

    def test_scan_honours_stop_event_before_next_category(self):
        stop_event = threading.Event()
        config = _warehouse_config(no_new_page_limit=1)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-0"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
        )
        store = _FakeStore(stop_after_category="items", stop_event=stop_event)
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
            stop_event=stop_event,
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.categories_completed, 1)
        self.assertEqual(store.completed_categories, ["items"])
        self.assertEqual(store.finish_calls[-1]["status"], "stopped")
        self.assertNotIn(tuple(config["categories"][1]["tab_tap"]), scenario.device_taps)

    def test_scan_clamps_configured_cleanup_rounds_before_finishing(self):
        stop_event = threading.Event()
        config = _warehouse_config(no_new_page_limit=1, max_return_rounds=99)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-0"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
            back_template_visible=False,
            back_tap_returns_main_city=False,
            device_back_returns_main_city=False,
        )
        store = _FakeStore(stop_after_category="items", stop_event=stop_event)
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
            stop_event=stop_event,
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "stopped")
        self.assertEqual(store.finish_calls[-1]["status"], "stopped")
        self.assertEqual(scenario.device_backs, 2)
        self.assertNotIn(tuple(config["navigation"]["warehouse_back_tap"]), scenario.device_taps)

    def test_scan_clamps_negative_cleanup_rounds_to_zero(self):
        stop_event = threading.Event()
        config = _warehouse_config(no_new_page_limit=1, max_return_rounds=-3)
        scenario = _ReplayScenario(
            config=config,
            category_pages={
                "items": ["items-0", "items-0"],
                "skill_fragments": ["skill-0", "skill-0"],
                "arms_fragments": ["arms-0", "arms-0"],
                "treasure_fragments": ["treasure-0", "treasure-0"],
                "specialties": ["specialties-0", "specialties-0"],
            },
        )
        store = _FakeStore(stop_after_category="items", stop_event=stop_event)
        scanner = WarehouseScanner(
            ctx=scenario.context,
            store=store,
            config=config,
            ocr_backend=object(),
            stop_event=stop_event,
        )

        with mock.patch(
            "src.warehouse.scanner.parse_visible_cards",
            side_effect=scenario.parse_visible_cards,
        ):
            result = scanner.scan()

        self.assertEqual(result.status, "stopped")
        self.assertEqual(store.finish_calls[-1]["status"], "stopped")
        self.assertEqual(scenario.device_backs, 0)
        self.assertNotIn(tuple(config["navigation"]["warehouse_back_tap"]), scenario.device_taps)


class _FakeStore:
    def __init__(
        self,
        *,
        stop_after_category: str | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.scan_id = "scan-001"
        self.upserted_pages: list[tuple[str, list[ItemObservation]]] = []
        self.completed_categories: list[str] = []
        self.finish_calls: list[dict[str, str | None]] = []
        self.closed = False
        self.stop_after_category = stop_after_category
        self.stop_event = stop_event

    def start_scan(self) -> str:
        return self.scan_id

    def upsert_page(self, scan_id: str, observations: list[ItemObservation]) -> None:
        self.upserted_pages.append((scan_id, list(observations)))

    def record_category_completion(self, scan_id: str, category_code: str) -> None:
        self.completed_categories.append(category_code)
        if self.stop_after_category == category_code and self.stop_event is not None:
            self.stop_event.set()

    def finish_scan(
        self,
        scan_id: str,
        status: str = "success",
        message: str | None = None,
    ) -> WarehouseScanResult:
        self.finish_calls.append(
            {
                "scan_id": scan_id,
                "status": status,
                "message": message,
            }
        )
        distinct_items = {
            (observation.category_code, observation.icon_hash)
            for _, observations in self.upserted_pages
            for observation in observations
        }
        low_confidence = {
            (observation.category_code, observation.icon_hash)
            for _, observations in self.upserted_pages
            for observation in observations
            if observation.needs_review
        }
        final_message = "fake finish" if message is None else message
        return WarehouseScanResult(
            status=status,
            scan_id=scan_id,
            categories_completed=len(self.completed_categories),
            items_found=len(distinct_items),
            low_confidence_count=len(low_confidence),
            message=final_message,
        )

    def close(self) -> None:
        self.closed = True


class _FakeTaskContext:
    def __init__(self, scenario: "_ReplayScenario") -> None:
        self._scenario = scenario
        self.device = _FakeDevice(scenario)
        self.matcher = _FakeMatcher(scenario)

    def screenshot(self) -> np.ndarray:
        return self._scenario.current_screen()


class _FakeDevice:
    def __init__(self, scenario: "_ReplayScenario") -> None:
        self._scenario = scenario

    def tap(self, x: int, y: int) -> None:
        point = (int(x), int(y))
        self._scenario.device_taps.append(point)
        self._scenario.handle_tap(point)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 400,
    ) -> None:
        self._scenario.device_swipes.append((x1, y1, x2, y2, duration_ms))
        self._scenario.handle_swipe()

    def back(self) -> None:
        self._scenario.device_backs += 1
        self._scenario.handle_back()


class _FakeMatcher:
    def __init__(self, scenario: "_ReplayScenario") -> None:
        self._scenario = scenario

    def find(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: float | None = None,
        region=None,
    ) -> MatchResult | None:
        if self._scenario.template_visible(template_name):
            return MatchResult(
                name=template_name,
                x=777,
                y=333,
                score=0.99,
                w=80,
                h=40,
            )
        return None


@dataclass(frozen=True)
class _ObservationSpec:
    icon_hash: str
    name_raw: str = "Name"
    name_normalized: str = "name"
    quantity_text: str = "1"
    needs_review: bool = False
    ocr_confidence: float = 0.95


class _ReplayScenario:
    def __init__(
        self,
        *,
        config: dict,
        category_pages: dict[str, list[str]],
        page_payloads: dict[str, list[_ObservationSpec]] | None = None,
        back_template_visible: bool = True,
        warehouse_title_visible: bool = True,
        back_tap_returns_main_city: bool = True,
        device_back_returns_main_city: bool = True,
    ) -> None:
        self.config = config
        self.category_pages = category_pages
        self.page_payloads = page_payloads or {}
        self.back_template_visible = back_template_visible
        self.warehouse_title_visible = warehouse_title_visible
        self.back_tap_returns_main_city = back_tap_returns_main_city
        self.device_back_returns_main_city = device_back_returns_main_city
        self.location = "main_city"
        self.current_category: str | None = None
        self.current_page_index = 0
        self.context = _FakeTaskContext(self)
        self.device_taps: list[tuple[int, int]] = []
        self.device_swipes: list[tuple[int, int, int, int, int]] = []
        self.device_backs = 0
        self._screen_codes = {
            "main_city": 10,
            **{
                page_name: index + 20
                for index, page_name in enumerate(
                    page_name
                    for pages in category_pages.values()
                    for page_name in pages
                )
            },
        }

    def current_screen(self) -> np.ndarray:
        tag = self.current_page_tag()
        image = np.zeros((1920, 1080, 3), dtype=np.uint8)
        image[:, :] = (self._screen_codes[tag], 0, 0)
        return image

    def current_page_tag(self) -> str:
        if self.location == "main_city":
            return "main_city"
        assert self.current_category is not None
        pages = self.category_pages[self.current_category]
        return pages[self.current_page_index]

    def parse_visible_cards(
        self,
        screen: np.ndarray,
        layout: dict,
        ocr_backend,
    ) -> list[ItemObservation]:
        page_tag = self.current_page_tag()
        category_code = layout["category_code"]
        specs = self.page_payloads.get(page_tag)
        if specs is None:
            specs = [self._default_spec(page_tag)]
        if page_tag.endswith("-0") and category_code in {"arms_fragments", "specialties"}:
            specs = []
        observations: list[ItemObservation] = []
        for spec in specs:
            observations.append(
                ItemObservation(
                    category_code=category_code,
                    name_raw=spec.name_raw,
                    name_normalized=spec.name_normalized,
                    quantity_text=spec.quantity_text,
                    ocr_confidence=spec.ocr_confidence,
                    icon_bytes=b"icon-" + spec.icon_hash.encode("utf-8"),
                    card_bytes=b"card-" + spec.icon_hash.encode("utf-8"),
                    icon_hash=spec.icon_hash,
                    page_index=int(layout["page_index"]),
                    screen_path=str(layout["screen_path"]),
                    bbox=(52, 404, 232, 262),
                    needs_review=spec.needs_review,
                )
            )
        return observations

    def handle_tap(self, point: tuple[int, int]) -> None:
        navigation = self.config["navigation"]
        if point == tuple(navigation["warehouse_entry_tap"]):
            self.location = "warehouse"
            self.current_category = self.config["categories"][0]["code"]
            self.current_page_index = 0
            return
        if point == tuple(navigation["warehouse_back_tap"]):
            if self.back_tap_returns_main_city:
                self.location = "main_city"
                self.current_category = None
                self.current_page_index = 0
            return
        for category in self.config["categories"]:
            if point == tuple(category["tab_tap"]):
                self.location = "warehouse"
                self.current_category = category["code"]
                self.current_page_index = 0
                return
        raise AssertionError(f"unexpected tap: {point}")

    def handle_swipe(self) -> None:
        assert self.current_category is not None
        pages = self.category_pages[self.current_category]
        if self.current_page_index + 1 < len(pages):
            self.current_page_index += 1

    def handle_back(self) -> None:
        if self.device_back_returns_main_city:
            self.location = "main_city"
            self.current_category = None
            self.current_page_index = 0

    def template_visible(self, template_name: str) -> bool:
        navigation = self.config["navigation"]
        if template_name == navigation["main_city_template"]:
            return self.location == "main_city"
        if template_name == navigation["warehouse_entry_template"]:
            return self.location == "main_city"
        if template_name == navigation["warehouse_title_template"]:
            return self.location == "warehouse" and self.warehouse_title_visible
        if template_name == navigation["warehouse_back_template"]:
            return self.location == "warehouse" and self.back_template_visible
        if template_name.startswith("warehouse_tab_"):
            return self.location == "warehouse"
        return False

    def _default_spec(self, page_tag: str) -> _ObservationSpec:
        return _ObservationSpec(
            icon_hash=page_tag,
            name_raw=page_tag.upper(),
            name_normalized=page_tag.replace("-", "_"),
            quantity_text="1",
            needs_review=False,
            ocr_confidence=0.95,
        )


def _warehouse_config(
    *,
    max_swipes_per_category: int = 3,
    no_new_page_limit: int = 2,
    max_return_rounds: int = 2,
) -> dict:
    return {
        "categories": [
            {"code": "items", "label": "道具", "tab_template": "warehouse_tab_items", "tab_tap": [112, 338]},
            {
                "code": "skill_fragments",
                "label": "技能碎片",
                "tab_template": "warehouse_tab_skill_fragments",
                "tab_tap": [330, 338],
            },
            {
                "code": "arms_fragments",
                "label": "军械碎片",
                "tab_template": "warehouse_tab_arms_fragments",
                "tab_tap": [548, 338],
            },
            {
                "code": "treasure_fragments",
                "label": "宝物碎片",
                "tab_template": "warehouse_tab_treasure_fragments",
                "tab_tap": [766, 338],
            },
            {
                "code": "specialties",
                "label": "特产",
                "tab_template": "warehouse_tab_specialties",
                "tab_tap": [968, 338],
            },
        ],
        "grid": {
            "columns": 4,
            "rows": 4,
            "origin": [52, 404],
            "card_size": [232, 262],
            "column_gap": 18,
            "row_gap": 22,
        },
        "rois": {
            "icon": [16, 18, 76, 76],
            "text": [96, 20, 120, 208],
            "name": [102, 24, 108, 54],
            "quantity": [102, 188, 108, 34],
        },
        "ocr_threshold": 0.70,
        "max_swipes_per_category": max_swipes_per_category,
        "no_new_page_limit": no_new_page_limit,
        "navigation": {
            "warehouse_entry_template": "warehouse_entry",
            "warehouse_entry_tap": [660, 1812],
            "warehouse_title_template": "warehouse_title",
            "warehouse_ready_template": "warehouse_back",
            "warehouse_back_template": "warehouse_back",
            "warehouse_back_tap": [64, 214],
            "main_city_template": "nav_fief",
            "swipe_start": [540, 1560],
            "swipe_end": [540, 760],
            "swipe_duration_ms": 350,
            "max_open_attempts": 2,
            "max_return_rounds": max_return_rounds,
        },
        "artifact_dir": "runs/warehouse",
    }


if __name__ == "__main__":
    unittest.main()
