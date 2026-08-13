import unittest

import numpy as np

from src.pipeline.loader import load_pipeline
from src.pipeline.result import PipelineStatus
from src.pipeline.runner import PipelineRunner
from src.vision.match import MatchResult


class ReplayDevice:
    def __init__(self):
        self.calls = []

    def tap(self, x, y, jitter=True):
        self.calls.append(("tap", x, y, jitter))


class ReplayMatcher:
    def __init__(self, available):
        self.available = set(available)

    def find(self, screen, name, threshold=None, region=None):
        if name not in self.available:
            return None
        return MatchResult(name=name, x=200, y=300, score=0.95, w=40, h=20)


class ReplayContext:
    def __init__(self, available):
        self.device = ReplayDevice()
        self.matcher = ReplayMatcher(available)
        self.screenshot_count = 0
        self.image = np.zeros((1920, 1080, 3), dtype=np.uint8)

    def screenshot(self):
        self.screenshot_count += 1
        return self.image


class PipelineReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition = load_pipeline("config/pipelines/auto_mail.yaml")

    def test_auto_mail_replay_uses_template_click_sequence(self):
        ctx = ReplayContext(
            {
                "nav_fief",
                "btn_more",
                "more_title",
                "btn_mail_icon",
                "mail_title",
                "mail_read_all_tight",
                "mail_close",
            }
        )

        result = PipelineRunner(ctx).run(self.definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual(
            [call[0] for call in ctx.device.calls],
            ["tap", "tap", "tap", "tap"],
        )
        self.assertEqual(ctx.screenshot_count, 8)

    def test_auto_mail_replay_uses_explicit_blank_close_fallback(self):
        ctx = ReplayContext(
            {
                "nav_fief",
                "btn_more",
                "more_title",
                "btn_mail_icon",
                "mail_title",
                "mail_read_all_tight",
            }
        )

        result = PipelineRunner(ctx).run(self.definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertEqual(ctx.device.calls[-1][1:3], (30, 500))

    def test_auto_mail_replay_uses_fixed_more_fallback_when_template_is_weak(self):
        ctx = ReplayContext(
            {
                "nav_fief",
                "more_title",
                "btn_mail_icon",
                "mail_title",
                "mail_read_all_tight",
                "mail_close",
            }
        )

        result = PipelineRunner(ctx).run(self.definition)

        self.assertIs(result.status, PipelineStatus.SUCCESS)
        self.assertIn(("tap", 985, 1625, True), ctx.device.calls)


if __name__ == "__main__":
    unittest.main()
