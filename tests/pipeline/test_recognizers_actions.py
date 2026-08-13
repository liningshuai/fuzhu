import unittest
from types import SimpleNamespace

import numpy as np

from src.pipeline.actions import ActionExecutor
from src.pipeline.models import ActionSpec, RecognizerSpec
from src.pipeline.recognizers import (
    OcrRecognizer,
    OcrText,
    OcrProviderUnavailable,
    RecognitionError,
    TemplateRecognizer,
)
from src.vision.match import MatchResult


class FakeMatcher:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def find(self, screen, name, threshold=None, region=None):
        self.calls.append((screen, name, threshold, region))
        if self.error is not None:
            raise self.error
        return self.result


class FakeDevice:
    def __init__(self):
        self.calls = []

    def tap(self, x, y, jitter=True):
        self.calls.append(("tap", x, y, jitter))

    def back(self):
        self.calls.append(("back",))

    def swipe(self, x1, y1, x2, y2, duration_ms=400):
        self.calls.append(("swipe", x1, y1, x2, y2, duration_ms))


class FakeOcrBackend:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def recognize(self, image, roi):
        self.calls.append((image, roi))
        if self.error is not None:
            raise self.error
        return self.results


class RecognizerAndActionTests(unittest.TestCase):
    def setUp(self):
        self.screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
        self.device = FakeDevice()
        self.ctx = SimpleNamespace(device=self.device)

    def test_template_recognizer_reuses_screen_and_returns_match_point(self):
        matcher = FakeMatcher(
            MatchResult(name="mail", x=200, y=300, score=0.91, w=40, h=20)
        )
        ctx = SimpleNamespace(matcher=matcher)
        spec = RecognizerSpec(
            type="template", template="mail", roi=(10, 20, 400, 500), threshold=0.8
        )

        result = TemplateRecognizer(spec).recognize(ctx, self.screen)

        self.assertIsNotNone(result)
        self.assertEqual(result.point, (200, 300))
        self.assertEqual(result.score, 0.91)
        self.assertIs(matcher.calls[0][0], self.screen)
        self.assertEqual(matcher.calls[0][1:], ("mail", 0.8, (10, 20, 400, 500)))

    def test_template_recognizer_converts_missing_template_to_controlled_error(self):
        matcher = FakeMatcher(error=FileNotFoundError("missing template"))
        ctx = SimpleNamespace(matcher=matcher)
        spec = RecognizerSpec(type="template", template="missing")

        with self.assertRaises(RecognitionError) as raised:
            TemplateRecognizer(spec).recognize(ctx, self.screen)

        self.assertIn("missing template", str(raised.exception))

    def test_ocr_recognizer_matches_normalized_substring_and_uses_best_score(self):
        backend = FakeOcrBackend(
            [
                OcrText("  开始   挑战 ", 0.86, (100, 200, 120, 40)),
                OcrText("开始挑战", 0.94, (300, 400, 120, 40)),
                OcrText("结束", 0.99, (500, 600, 80, 40)),
            ]
        )
        spec = RecognizerSpec(
            type="ocr", text="开始挑战", roi=(0, 0, 1080, 1920), threshold=0.8
        )

        result = OcrRecognizer(spec, backend=backend).recognize(self.ctx, self.screen)

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "开始挑战")
        self.assertEqual(result.point, (360, 420))
        self.assertEqual(result.score, 0.94)
        self.assertEqual(backend.calls[0][1], (0, 0, 1080, 1920))

    def test_ocr_provider_unavailable_is_not_converted_to_a_click(self):
        backend = FakeOcrBackend(error=OcrProviderUnavailable("OCR unavailable"))
        spec = RecognizerSpec(type="ocr", text="开始挑战")

        with self.assertRaises(OcrProviderUnavailable):
            OcrRecognizer(spec, backend=backend).recognize(self.ctx, self.screen)

        self.assertEqual(self.device.calls, [])

    def test_none_action_does_not_send_input(self):
        result = ActionExecutor().execute(self.ctx, ActionSpec(type="none"))

        self.assertTrue(result.ok)
        self.assertIsNone(result.terminal)
        self.assertEqual(self.device.calls, [])

    def test_tap_self_uses_recognition_point_and_keeps_jitter_enabled(self):
        result = ActionExecutor().execute(
            self.ctx,
            ActionSpec(type="tap_self"),
            recognition=SimpleNamespace(point=(200, 300)),
        )

        self.assertTrue(result.ok)
        self.assertEqual(self.device.calls, [("tap", 200, 300, True)])

    def test_tap_rect_uses_rect_center(self):
        result = ActionExecutor().execute(
            self.ctx,
            ActionSpec(type="tap", rect=(100, 200, 40, 20)),
        )

        self.assertTrue(result.ok)
        self.assertEqual(self.device.calls, [("tap", 120, 210, True)])

    def test_device_exception_is_returned_as_action_failure(self):
        class BrokenDevice(FakeDevice):
            def back(self):
                raise RuntimeError("device offline")

        ctx = SimpleNamespace(device=BrokenDevice())
        result = ActionExecutor().execute(ctx, ActionSpec(type="back"))

        self.assertFalse(result.ok)
        self.assertIn("device offline", result.message)


if __name__ == "__main__":
    unittest.main()
