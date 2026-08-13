import unittest

from src.vision.match import MatchResult


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeDevice:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def screenshot(self):
        self.calls.append(("screenshot", self.state))
        return self.state

    def tap(self, x, y):
        self.calls.append(("tap", x, y, self.state))
        if self.state == "announcement":
            self.state = "login"
        elif self.state == "login":
            self.state = "main"
        elif self.state in {"permanent_reward", "highlight"}:
            self.state = "main"


class FakeMatcher:
    def find(self, screen, name, threshold=None, region=None):
        matches = {
            "announcement": "startup_announcement_claim",
            "login": "startup_enter_game",
            "permanent_reward": "startup_permanent_claim",
            "highlight": "startup_highlight_close_hint",
            "main": "nav_fief",
        }
        if matches.get(screen) != name:
            return None
        return MatchResult(name, 540, 1000, 0.99, 100, 40)


class MissingMainCityMatcher(FakeMatcher):
    def find(self, screen, name, threshold=None, region=None):
        if name == "nav_fief":
            raise FileNotFoundError(name)
        return None


class RecordingActivityDetector:
    def __init__(self, match=None):
        self.match = match
        self.screens = []

    def detect(self, screen):
        self.screens.append(screen)
        return self.match


class StartupFlowTests(unittest.TestCase):
    def make_flow(self, device, *, timeout=1.0, activity_detector=None):
        from src.session.startup import GameStartupFlow

        clock = FakeClock()
        kwargs = {
            "timeout_seconds": timeout,
            "poll_interval": 0.1,
            "sleep_fn": clock.sleep,
            "monotonic_fn": clock.monotonic,
        }
        if activity_detector is not None:
            kwargs["activity_detector"] = activity_detector
        return GameStartupFlow(
            device,
            FakeMatcher(),
            **kwargs,
        )

    def test_main_city_returns_without_clicking(self):
        device = FakeDevice("main")

        self.make_flow(device).wait_until_main_city()

        self.assertEqual([call[0] for call in device.calls], ["screenshot"])

    def test_announcement_then_enter_game_are_processed_in_order(self):
        device = FakeDevice("announcement")

        self.make_flow(device).wait_until_main_city()

        self.assertEqual(
            [(call[0], call[1], call[2]) for call in device.calls if call[0] == "tap"],
            [("tap", 540, 1000), ("tap", 540, 1000)],
        )
        self.assertEqual(device.state, "main")

    def test_permanent_reward_is_claimed_before_main_city(self):
        device = FakeDevice("permanent_reward")

        self.make_flow(device).wait_until_main_city()

        self.assertEqual(device.calls[1][:3], ("tap", 540, 1000))
        self.assertEqual(device.state, "main")

    def test_highlight_popup_uses_safe_blank_point(self):
        device = FakeDevice("highlight")

        self.make_flow(device).wait_until_main_city()

        self.assertIn(("tap", 30, 500, "highlight"), device.calls)
        self.assertEqual(device.state, "main")

    def test_known_highlight_popup_has_priority_over_activity_detector(self):
        device = FakeDevice("highlight")
        detector = RecordingActivityDetector()

        self.make_flow(
            device, activity_detector=detector
        ).wait_until_main_city()

        self.assertEqual(
            [call for call in device.calls if call[0] == "tap"],
            [("tap", 30, 500, "highlight")],
        )
        self.assertEqual(detector.screens, ["main"])

    def test_activity_detector_no_match_does_not_create_blank_tap(self):
        from src.session.startup import GameStartupTimeout

        device = FakeDevice("unknown")
        detector = RecordingActivityDetector()

        with self.assertRaises(GameStartupTimeout):
            self.make_flow(
                device, timeout=0.3, activity_detector=detector
            ).wait_until_main_city()

        self.assertFalse(any(call[0] == "tap" for call in device.calls))

    def test_unknown_screen_does_not_click_and_times_out(self):
        from src.session.startup import GameStartupTimeout

        device = FakeDevice("unknown")

        with self.assertRaises(GameStartupTimeout):
            self.make_flow(device, timeout=0.3).wait_until_main_city()

        self.assertFalse(any(call[0] == "tap" for call in device.calls))

    def test_missing_main_city_template_times_out_instead_of_leaking_file_error(self):
        from src.session.startup import GameStartupTimeout, GameStartupFlow

        device = FakeDevice("unknown")
        clock = FakeClock()
        flow = GameStartupFlow(
            device,
            MissingMainCityMatcher(),
            timeout_seconds=0.3,
            poll_interval=0.1,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
        )

        with self.assertRaises(GameStartupTimeout):
            flow.wait_until_main_city()


if __name__ == "__main__":
    unittest.main()
