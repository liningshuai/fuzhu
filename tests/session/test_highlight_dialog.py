import unittest
from pathlib import Path

import cv2
import numpy as np

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    HIGHLIGHT_CLOSE_POINT,
    dismiss_confirm_dialogs,
    dismiss_activity_popups,
)
from src.session.activity_popup import ActivityPopupMatch
from src.vision.match import MatchResult


class FakeDevice:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.state))
        if self.state == "highlight":
            self.state = "confirm"
        elif self.state == "reward":
            self.state = "main"
        elif self.state == "confirm":
            self.state = "main"


class FakeMatcher:
    def find(self, screen, name, threshold=None, region=None):
        if screen == "highlight" and name == "startup_highlight_close_hint":
            return MatchResult(name, 540, 1000, 0.99, 100, 40)
        if screen == "reward" and name == "startup_highlight_close_hint_reward":
            return MatchResult(name, 540, 1100, 0.99, 100, 40)
        if screen == "confirm" and name == "dialog_confirm":
            return MatchResult(name, 540, 1305, 0.99, 120, 40)
        if screen == "buy" and name == "guoguan_buy_title":
            return MatchResult(name, 540, 800, 0.99, 120, 40)
        return None


class FakeContext:
    def __init__(self, state, matcher=None):
        self.device = FakeDevice(state)
        self.matcher = matcher or FakeMatcher()

    def screenshot(self):
        return self.device.state


class ReplayDevice:
    def __init__(self, states):
        self.states = iter(states)
        self.state = next(self.states)
        self.screenshots = []
        self.blank_taps = []

    def screenshot(self):
        self.screenshots.append(self.state)
        return self.state

    def tap(self, x, y):
        self.blank_taps.append((x, y))
        try:
            self.state = next(self.states)
        except StopIteration:
            pass


class ReplayContext:
    def __init__(self, states):
        self.device = ReplayDevice(states)
        self.matcher = object()

    def screenshot(self):
        return self.device.screenshot()


class ReplayActivityDetector:
    def __init__(self, activity_states):
        self.activity_states = set(activity_states)

    def detect(self, screen):
        if screen in self.activity_states:
            return ActivityPopupMatch(screen, 0.91, "replay safe popup")
        return None


class BusinessHighlightMatcher(FakeMatcher):
    template_dir = Path(".")

    def find(self, screen, name, threshold=None, region=None):
        if name == "duplicate_login_message":
            return MatchResult(name, 540, 987, 0.99, 100, 40)
        if name == "startup_highlight_close_hint":
            return MatchResult(name, 540, 1000, 0.99, 100, 40)
        return super().find(screen, name, threshold=threshold, region=region)


class ImageReplayDevice:
    def __init__(self, screens):
        self.screens = iter(screens)
        self.screen = next(self.screens)
        self.blank_taps = []
        self.screenshot_count = 0

    def screenshot(self):
        self.screenshot_count += 1
        return self.screen

    def tap(self, x, y):
        self.blank_taps.append((x, y))
        try:
            self.screen = next(self.screens)
        except StopIteration:
            pass


class TriggeredImageReplayDevice:
    def __init__(self, main, popup):
        self.main = main
        self.screen = main
        self.popup = popup
        self.blank_taps = []

    def screenshot(self):
        return self.screen

    def tap(self, x, y):
        if (x, y) == (1, 1):
            self.screen = self.popup
        else:
            self.blank_taps.append((x, y))
            self.screen = self.main


class MidTaskCommandPopupTask(BaseTask):
    id = "mid_task_command_popup"
    name = "mid-task command popup"

    def execute(self, ctx):
        ctx.device.tap(1, 1)
        ctx.screenshot()
        return TaskResult(TaskStatus.SUCCESS, "task continued")


class HighlightDialogTests(unittest.TestCase):
    def test_command_order_popup_is_dismissed_during_task_screenshot(self):
        from src.vision.match import TemplateMatcher

        matcher = TemplateMatcher(template_dir=config.root / "assets" / "templates")
        defense_path = (
            config.root
            / "assets"
            / "screenshots"
            / "startup_command_order_defense_replay.png"
        )
        defense = cv2.imdecode(
            np.fromfile(str(defense_path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        main = np.full((1920, 1080, 3), 220, dtype=np.uint8)
        nav = matcher._load("nav_fief")
        nav_h, nav_w = nav.shape[:2]
        main[1760 : 1760 + nav_h, 0:nav_w] = nav

        device = TriggeredImageReplayDevice(main, defense)
        ctx = TaskContext(device=device, matcher=matcher)
        result = MidTaskCommandPopupTask(enabled=True).run(ctx)

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(device.blank_taps, [HIGHLIGHT_CLOSE_POINT])

    def test_attack_command_popup_is_dismissed_during_task_screenshot(self):
        from src.vision.match import TemplateMatcher

        matcher = TemplateMatcher(template_dir=config.root / "assets" / "templates")
        attack_path = (
            config.root
            / "assets"
            / "screenshots"
            / "startup_command_order_attack_replay.png"
        )
        attack = cv2.imdecode(
            np.fromfile(str(attack_path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(attack)
        main = np.full((1920, 1080, 3), 220, dtype=np.uint8)
        nav = matcher._load("nav_fief")
        nav_h, nav_w = nav.shape[:2]
        main[1760 : 1760 + nav_h, 0:nav_w] = nav

        device = TriggeredImageReplayDevice(main, attack)
        ctx = TaskContext(device=device, matcher=matcher)
        result = MidTaskCommandPopupTask(enabled=True).run(ctx)

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(device.blank_taps, [HIGHLIGHT_CLOSE_POINT])

    def test_safe_activity_popup_uses_blank_point_and_fresh_screenshot(self):
        ctx = ReplayContext(["activity_1", "activity_2", "main"])
        detector = ReplayActivityDetector({"activity_1", "activity_2"})

        closed = dismiss_activity_popups(ctx, max_rounds=3, detector=detector)

        self.assertEqual(closed, 2)
        self.assertEqual(ctx.device.blank_taps, [HIGHLIGHT_CLOSE_POINT, HIGHLIGHT_CLOSE_POINT])
        self.assertEqual(
            ctx.device.screenshots,
            ["activity_1", "activity_2", "main"],
        )

    def test_safe_activity_popup_never_taps_unknown_or_business_screen(self):
        ctx = ReplayContext(["unknown"])
        detector = ReplayActivityDetector(set())

        closed = dismiss_activity_popups(ctx, detector=detector)

        self.assertEqual(closed, 0)
        self.assertEqual(ctx.device.blank_taps, [])

    def test_safe_activity_popup_stops_at_limit(self):
        ctx = ReplayContext(["activity_1", "activity_2", "activity_3"])
        detector = ReplayActivityDetector(
            {"activity_1", "activity_2", "activity_3"}
        )

        closed = dismiss_activity_popups(ctx, max_rounds=2, detector=detector)

        self.assertEqual(closed, 2)
        self.assertEqual(ctx.device.blank_taps, [HIGHLIGHT_CLOSE_POINT, HIGHLIGHT_CLOSE_POINT])

    def test_command_order_pages_are_dismissed_one_per_fresh_screenshot(self):
        ctx = ReplayContext(["command_build", "command_attack", "main"])
        detector = ReplayActivityDetector({"command_build", "command_attack"})

        closed = dismiss_activity_popups(ctx, max_rounds=3, detector=detector)

        self.assertEqual(closed, 2)
        self.assertEqual(
            ctx.device.blank_taps,
            [HIGHLIGHT_CLOSE_POINT, HIGHLIGHT_CLOSE_POINT],
        )
        self.assertEqual(
            ctx.device.screenshots,
            ["command_build", "command_attack", "main"],
        )

    def test_business_blocker_prevents_legacy_highlight_blank_tap(self):
        ctx = FakeContext("highlight", matcher=BusinessHighlightMatcher())

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 0)
        self.assertEqual(ctx.device.calls, [])

    def test_confirm_cleanup_dismisses_real_activity_replay_without_business_click(self):
        from src.vision.match import TemplateMatcher

        matcher = TemplateMatcher(template_dir=config.root / "assets" / "templates")
        panel_path = config.root / "assets" / "screenshots" / "panel_latest.png"
        panel_data = np.fromfile(str(panel_path), dtype=np.uint8)
        panel = cv2.imdecode(panel_data, cv2.IMREAD_COLOR)
        self.assertIsNotNone(panel)

        main = np.full((1920, 1080, 3), 220, dtype=np.uint8)
        nav = matcher._load("nav_fief")
        nav_h, nav_w = nav.shape[:2]
        main[1760 : 1760 + nav_h, 0:nav_w] = nav
        self.assertIsNotNone(matcher.find(main, "nav_fief", threshold=0.90))

        device = ImageReplayDevice([panel, main])
        ctx = TaskContext(device=device, matcher=matcher)

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 1)
        self.assertEqual(device.blank_taps, [HIGHLIGHT_CLOSE_POINT])
        self.assertGreaterEqual(device.screenshot_count, 2)

    def test_confirm_cleanup_dismisses_defense_command_with_only_safe_blank_tap(self):
        from src.vision.match import TemplateMatcher

        matcher = TemplateMatcher(template_dir=config.root / "assets" / "templates")
        defense_path = (
            config.root
            / "assets"
            / "screenshots"
            / "startup_command_order_defense_replay.png"
        )
        defense = cv2.imdecode(
            np.fromfile(str(defense_path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(defense)

        main = np.full((1920, 1080, 3), 220, dtype=np.uint8)
        nav = matcher._load("nav_fief")
        nav_h, nav_w = nav.shape[:2]
        main[1760 : 1760 + nav_h, 0:nav_w] = nav

        device = ImageReplayDevice([defense, main])
        ctx = TaskContext(device=device, matcher=matcher)

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 1)
        self.assertEqual(device.blank_taps, [HIGHLIGHT_CLOSE_POINT])
        self.assertEqual(
            [call[:3] for call in getattr(device, "calls", [])],
            [],
        )

    def test_confirm_cleanup_dismisses_attack_command_with_only_safe_blank_tap(self):
        from src.vision.match import TemplateMatcher

        matcher = TemplateMatcher(template_dir=config.root / "assets" / "templates")
        attack_path = (
            config.root
            / "assets"
            / "screenshots"
            / "startup_command_order_attack_replay.png"
        )
        attack = cv2.imdecode(
            np.fromfile(str(attack_path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(attack)

        main = np.full((1920, 1080, 3), 220, dtype=np.uint8)
        nav = matcher._load("nav_fief")
        nav_h, nav_w = nav.shape[:2]
        main[1760 : 1760 + nav_h, 0:nav_w] = nav

        device = ImageReplayDevice([attack, main])
        ctx = TaskContext(device=device, matcher=matcher)

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 1)
        self.assertEqual(device.blank_taps, [HIGHLIGHT_CLOSE_POINT])

    def test_highlight_popup_uses_safe_blank_and_then_processes_confirm(self):
        ctx = FakeContext("highlight")

        closed = dismiss_confirm_dialogs(ctx, max_rounds=3)

        self.assertEqual(closed, 2)
        self.assertEqual(
            [(call[0], call[1], call[2]) for call in ctx.device.calls],
            [
                ("tap", *HIGHLIGHT_CLOSE_POINT),
                ("tap", 540, 1305),
            ],
        )

    def test_unknown_screen_does_not_click_blank(self):
        ctx = FakeContext("main")

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 0)
        self.assertEqual(ctx.device.calls, [])

    def test_reward_highlight_template_also_uses_safe_blank(self):
        ctx = FakeContext("reward")

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 1)
        self.assertEqual(
            [(call[0], call[1], call[2]) for call in ctx.device.calls],
            [("tap", *HIGHLIGHT_CLOSE_POINT)],
        )

    def test_buy_times_dialog_remains_owned_by_purchase_flow(self):
        ctx = FakeContext("buy")

        closed = dismiss_confirm_dialogs(ctx, max_rounds=2)

        self.assertEqual(closed, 0)
        self.assertEqual(ctx.device.calls, [])


if __name__ == "__main__":
    unittest.main()
