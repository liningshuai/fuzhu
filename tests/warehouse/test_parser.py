from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest
from unittest import mock

import cv2
import numpy as np

from src.config import load_warehouse_config
from src.pipeline.recognizers import OcrText
from src.warehouse.parser import (
    normalise_item_name,
    parse_visible_cards,
    sha256_icon,
)


class _FakeOcrBackend:
    def __init__(self, responses: list[OcrText]) -> None:
        self._responses = responses
        self.calls: list[tuple[int, int, int, int] | None] = []

    def recognize(
        self,
        image: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> list[OcrText]:
        self.calls.append(roi)
        return list(self._responses)


class WarehouseParserTests(unittest.TestCase):
    def test_importing_parser_does_not_load_or_instantiate_rapidocr(self):
        original_module = sys.modules.get("src.warehouse.parser")
        rapidocr_factory = mock.Mock(name="RapidOCR")
        module_imports: list[str] = []
        real_import_module = importlib.import_module

        def guarded_import(name: str, package: str | None = None):
            module_imports.append(name)
            if name == "rapidocr_onnxruntime":
                raise AssertionError("parser import should not load RapidOCR")
            return real_import_module(name, package)

        try:
            sys.modules.pop("src.warehouse.parser", None)
            with mock.patch("importlib.import_module", side_effect=guarded_import):
                with mock.patch.dict(
                    sys.modules,
                    {"rapidocr_onnxruntime": mock.Mock(RapidOCR=rapidocr_factory)},
                    clear=False,
                ):
                    parser_module = importlib.import_module("src.warehouse.parser")
                    reloaded_module = importlib.reload(parser_module)
        finally:
            sys.modules.pop("src.warehouse.parser", None)
            if original_module is not None:
                sys.modules["src.warehouse.parser"] = original_module

        self.assertIs(parser_module, reloaded_module)
        self.assertNotIn("rapidocr_onnxruntime", module_imports)
        rapidocr_factory.assert_not_called()

    def test_load_warehouse_config_reads_yaml_without_shared_mutable_state(self):
        loaded = load_warehouse_config()

        self.assertEqual(
            [item["code"] for item in loaded["categories"]],
            [
                "items",
                "skill_fragments",
                "arms_fragments",
                "treasure_fragments",
                "specialties",
            ],
        )
        self.assertEqual(loaded["ocr_threshold"], 0.70)
        self.assertEqual(loaded["grid"]["columns"], 4)
        self.assertEqual(loaded["max_swipes_per_category"], 30)
        self.assertEqual(loaded["no_new_page_limit"], 2)

        loaded["categories"][0]["code"] = "mutated"
        reloaded = load_warehouse_config()
        self.assertEqual(reloaded["categories"][0]["code"], "items")

    def test_load_warehouse_config_does_not_modify_runtime_yaml(self):
        runtime_path = Path(__file__).resolve().parents[2] / "config" / "runtime.yaml"
        before_exists = runtime_path.exists()
        before_bytes = runtime_path.read_bytes() if before_exists else None
        before_mtime_ns = runtime_path.stat().st_mtime_ns if before_exists else None

        loaded = load_warehouse_config()

        after_exists = runtime_path.exists()
        after_bytes = runtime_path.read_bytes() if after_exists else None
        after_mtime_ns = runtime_path.stat().st_mtime_ns if after_exists else None

        self.assertIn("categories", loaded)
        self.assertEqual(after_exists, before_exists)
        self.assertEqual(after_bytes, before_bytes)
        self.assertEqual(after_mtime_ns, before_mtime_ns)

    def test_normalise_item_name_applies_nfkc_casefold_and_punctuation_cleanup(self):
        self.assertEqual(
            normalise_item_name("  ＳＳＲ　碎片  （ 通用 ） ／ Ⅰ "),
            "ssr碎片(通用)/i",
        )

    def test_sha256_icon_is_stable_for_identical_icon_arrays(self):
        icon = np.zeros((20, 20, 3), dtype=np.uint8)
        icon[:, :] = (10, 80, 200)

        self.assertEqual(sha256_icon(icon), sha256_icon(icon.copy()))

    def test_parse_visible_cards_marks_low_confidence_name_for_review(self):
        screen = self._screen_with_one_card()
        layout = self._layout()
        ocr = _FakeOcrBackend(
            [
                OcrText("  ＳＳＲ　碎片 ", 0.69, (52, 70, 120, 26)),
                OcrText("x12", 0.95, (150, 110, 50, 24)),
            ]
        )

        observations = parse_visible_cards(screen, layout, ocr)

        self.assertEqual(ocr.calls, [(40, 60, 180, 90)])
        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.category_code, "items")
        self.assertEqual(observation.name_raw, "  ＳＳＲ　碎片 ")
        self.assertEqual(observation.name_normalized, "ssr碎片")
        self.assertEqual(observation.quantity_text, "x12")
        self.assertEqual(observation.ocr_confidence, 0.69)
        self.assertEqual(observation.bbox, (40, 40, 200, 140))
        self.assertTrue(observation.needs_review)

    def test_parse_visible_cards_keeps_evidence_when_ocr_name_is_empty(self):
        screen = self._screen_with_one_card()
        layout = self._layout()
        ocr = _FakeOcrBackend(
            [
                OcrText("   ", 0.10, (52, 70, 120, 26)),
                OcrText("99", 0.91, (150, 110, 50, 24)),
            ]
        )

        observations = parse_visible_cards(screen, layout, ocr)

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.name_raw, "")
        self.assertEqual(observation.name_normalized, "")
        self.assertEqual(observation.quantity_text, "99")
        self.assertEqual(observation.ocr_confidence, 0.0)
        self.assertTrue(observation.needs_review)
        self.assertGreater(len(observation.icon_bytes), 0)
        self.assertGreater(len(observation.card_bytes), 0)
        self.assertTrue(observation.icon_hash)
        card = cv2.imdecode(
            np.frombuffer(observation.card_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        icon = cv2.imdecode(
            np.frombuffer(observation.icon_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertEqual(tuple(card.shape[:2]), (140, 200))
        self.assertEqual(tuple(icon.shape[:2]), (48, 48))

    def _layout(self) -> dict:
        return {
            "category_code": "items",
            "page_index": 3,
            "screen_path": "runs/warehouse/page-3.png",
            "ocr_threshold": 0.70,
            "grid": {
                "columns": 1,
                "rows": 1,
                "origin": [40, 40],
                "card_size": [200, 140],
                "column_gap": 0,
                "row_gap": 0,
            },
            "rois": {
                "icon": [8, 18, 48, 48],
                "text": [0, 20, 180, 90],
                "name": [52, 20, 120, 30],
                "quantity": [110, 58, 70, 28],
            },
        }

    def _screen_with_one_card(self) -> np.ndarray:
        screen = np.zeros((220, 260, 3), dtype=np.uint8)
        screen[40:180, 40:240] = (25, 35, 55)
        screen[58:106, 48:96] = (0, 180, 90)
        return screen


if __name__ == "__main__":
    unittest.main()
