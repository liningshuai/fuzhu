import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.session.activity_popup import ActivityPopupMatch
from src.config import config
from src.session.startup import HIGHLIGHT_CLOSE_POINT, GameStartupFlow
from src.vision.match import MatchResult, TemplateMatcher


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ReplayDevice:
    def __init__(self):
        self.state = "announcement"
        self.calls = []

    def screenshot(self):
        self.calls.append(("screenshot", self.state))
        return self.state

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.state))
        transitions = {
            "announcement": "login",
            "login": "permanent",
            "permanent": "highlight",
            "highlight": "main",
        }
        self.state = transitions.get(self.state, self.state)


class ReplayMatcher:
    MATCHES = {
        "announcement": ("startup_announcement_claim", 540, 1000),
        "login": ("startup_enter_game", 540, 1100),
        "permanent": ("startup_permanent_claim", 540, 1200),
        "highlight": ("startup_highlight_close_hint", 540, 1300),
        "main": ("nav_fief", 80, 1830),
    }

    def find(self, screen, name, threshold=None, region=None):
        expected = self.MATCHES.get(screen)
        if expected is None or expected[0] != name:
            return None
        return MatchResult(name, expected[1], expected[2], 0.99, 100, 40)


class ActivityReplayDevice:
    def __init__(self, states):
        self.states = iter(states)
        self.state = next(self.states)
        self.calls = []

    def screenshot(self):
        self.calls.append(("screenshot", self.state))
        return self.state

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.state))
        try:
            self.state = next(self.states)
        except StopIteration:
            pass


class BusinessPopupMatcher:
    def __init__(self, template_dir):
        self.template_dir = Path(template_dir)
        self.calls = []

    def find(self, screen, name, threshold=None, region=None):
        self.calls.append(name)
        if name == "dialog_confirm":
            return MatchResult(name, 540, 960, 0.99, 120, 48)
        return None


class BusinessPopupDevice:
    def __init__(self):
        self.state = "business_popup"
        self.calls = []
        self.screen = np.zeros((1920, 1080, 3), dtype=np.uint8)

    def screenshot(self):
        self.calls.append(("screenshot", self.state))
        return self.screen

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.state))


class ImageReplayDevice:
    def __init__(self, screens):
        self.screens = list(screens)
        self.index = 0
        self.calls = []

    def screenshot(self):
        self.calls.append(("screenshot", self.index))
        return self.screens[min(self.index, len(self.screens) - 1)]

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.index))
        self.index = min(self.index + 1, len(self.screens) - 1)


class FakeActivityDetector:
    def __init__(self):
        self.screens = []

    def detect(self, screen):
        self.screens.append(screen)
        if screen.startswith("activity_"):
            return ActivityPopupMatch(screen, 0.91, "fake replay match")
        return None


class StartupReplayTests(unittest.TestCase):
    def test_default_activity_detector_dismisses_attack_command_replay(self):
        def read_image(name):
            path = config.root / "assets" / "screenshots" / name
            image = cv2.imdecode(
                np.fromfile(str(path), dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            self.assertIsNotNone(image)
            return image

        device = ImageReplayDevice(
            [
                read_image("startup_command_order_attack_replay.png"),
                read_image("clean_state.png"),
            ]
        )
        clock = FakeClock()
        flow = GameStartupFlow(
            device,
            TemplateMatcher(template_dir=config.root / "assets" / "templates"),
            timeout_seconds=2.0,
            poll_interval=0.1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        flow.wait_until_main_city()

        self.assertEqual(
            [call[:3] for call in device.calls if call[0] == "tap"],
            [("tap", *HIGHLIGHT_CLOSE_POINT)],
        )
        self.assertEqual(
            [call[0] for call in device.calls if call[0] == "screenshot"],
            ["screenshot", "screenshot"],
        )

    def test_full_startup_sequence_reaches_main_city_without_blind_taps(self):
        device = ReplayDevice()
        clock = FakeClock()
        flow = GameStartupFlow(
            device,
            ReplayMatcher(),
            timeout_seconds=2.0,
            poll_interval=0.1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        flow.wait_until_main_city()

        self.assertEqual(device.state, "main")
        self.assertEqual(
            [
                (call[0], call[1], call[2])
                for call in device.calls
                if call[0] == "tap"
            ],
            [
                ("tap", 540, 1000),
                ("tap", 540, 1100),
                ("tap", 540, 1200),
                ("tap", *HIGHLIGHT_CLOSE_POINT),
            ],
        )
        self.assertEqual(
            [call[1] for call in device.calls if call[0] == "screenshot"],
            ["announcement", "login", "permanent", "highlight", "main"],
        )

    def test_activity_popups_are_dismissed_one_per_fresh_screenshot(self):
        device = ActivityReplayDevice(["activity_1", "activity_2", "main"])
        detector = FakeActivityDetector()
        clock = FakeClock()
        flow = GameStartupFlow(
            device,
            ReplayMatcher(),
            activity_detector=detector,
            timeout_seconds=2.0,
            poll_interval=0.1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        flow.wait_until_main_city()

        self.assertEqual(
            [
                (call[0], call[1], call[2])
                for call in device.calls
                if call[0] == "tap"
            ],
            [
                ("tap", *HIGHLIGHT_CLOSE_POINT),
                ("tap", *HIGHLIGHT_CLOSE_POINT),
            ],
        )
        self.assertEqual(
            [call[1] for call in device.calls if call[0] == "screenshot"],
            ["activity_1", "activity_2", "main"],
        )
        self.assertEqual(detector.screens, ["activity_1", "activity_2", "main"])

    def test_activity_dismissal_limit_raises_after_two_taps(self):
        from src.session.startup import GameStartupTimeout

        device = ActivityReplayDevice(["activity_1", "activity_2", "activity_3"])
        detector = FakeActivityDetector()
        clock = FakeClock()
        flow = GameStartupFlow(
            device,
            ReplayMatcher(),
            activity_detector=detector,
            max_activity_dismissals=2,
            timeout_seconds=2.0,
            poll_interval=0.1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        with self.assertRaises(GameStartupTimeout) as ctx:
            flow.wait_until_main_city()

        message = str(ctx.exception)
        self.assertIn("2", message)
        self.assertIn("activity_3", message)
        self.assertIn("fake replay match", message)
        self.assertEqual(
            [call[:3] for call in device.calls if call[0] == "tap"],
            [
                ("tap", *HIGHLIGHT_CLOSE_POINT),
                ("tap", *HIGHLIGHT_CLOSE_POINT),
            ],
        )
        self.assertEqual(
            [call[1] for call in device.calls if call[0] == "screenshot"],
            ["activity_1", "activity_2", "activity_3"],
        )

    def test_default_activity_detector_ignores_business_popup_without_blank_tap(self):
        from src.session.startup import GameStartupTimeout

        device = BusinessPopupDevice()
        clock = FakeClock()

        with tempfile.TemporaryDirectory() as template_dir:
            matcher = BusinessPopupMatcher(template_dir)
            flow = GameStartupFlow(
                device,
                matcher,
                timeout_seconds=0.2,
                poll_interval=0.1,
                sleep_fn=clock.sleep,
                monotonic_fn=clock.monotonic,
            )

            with self.assertRaises(GameStartupTimeout):
                flow.wait_until_main_city()

        taps = [call for call in device.calls if call[0] == "tap"]
        self.assertEqual(taps, [])
        self.assertNotIn(("tap", *HIGHLIGHT_CLOSE_POINT), taps)
        self.assertIn("dialog_confirm", matcher.calls)


if __name__ == "__main__":
    unittest.main()
