import unittest

import numpy as np

from src.session.recovery import (
    GameSessionGuard,
    GameSessionRecoveryError,
    GameSessionRestarted,
)
from src.vision.match import MatchResult


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeDevice:
    def __init__(self, main_screen):
        self.main_screen = main_screen
        self.calls = []

    def stop_game(self):
        self.calls.append("stop_game")

    def start_game(self):
        self.calls.append("start_game")

    def is_online(self):
        self.calls.append("is_online")
        return True

    def is_game_foreground(self):
        self.calls.append("is_game_foreground")
        return True

    def screenshot(self):
        self.calls.append("screenshot")
        return self.main_screen


class FakeMatcher:
    def __init__(self, duplicate=False, main_city=True):
        self.duplicate = duplicate
        self.main_city = main_city
        self.calls = []

    def find(self, screen, name, threshold=None, region=None):
        self.calls.append((name, threshold, region))
        if name in {"duplicate_login_message", "duplicate_login_confirm"}:
            if self.duplicate:
                return MatchResult(name, 540, 1000, 0.95, 100, 40)
            return None
        if name == "nav_fief" and self.main_city:
            return MatchResult(name, 80, 1830, 0.95, 120, 140)
        return None


class GameSessionGuardTests(unittest.TestCase):
    def setUp(self):
        self.popup_screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
        self.main_screen = np.ones((1920, 1080, 3), dtype=np.uint8)
        self.clock = FakeClock()

    def make_guard(self, *, duplicate=True, main_city=True):
        device = FakeDevice(self.main_screen)
        matcher = FakeMatcher(duplicate=duplicate, main_city=main_city)
        guard = GameSessionGuard(
            device,
            matcher,
            sleep_fn=self.clock.sleep,
            monotonic_fn=self.clock.monotonic,
            startup_timeout=1.0,
            # The fake clock advances only through sleep; a zero interval
            # would make the timeout path spin forever in the failure case.
            poll_interval=0.1,
        )
        return guard, device, matcher

    def test_non_duplicate_screen_does_not_restart(self):
        guard, device, _ = self.make_guard(duplicate=False)

        guard.check(self.popup_screen)

        self.assertEqual(device.calls, [])

    def test_duplicate_screen_restarts_and_reports_interruption(self):
        guard, device, matcher = self.make_guard()

        with self.assertRaises(GameSessionRestarted):
            guard.check(self.popup_screen)

        self.assertEqual(device.calls[:2], ["stop_game", "start_game"])
        self.assertIn("is_game_foreground", device.calls)
        self.assertIn("nav_fief", [call[0] for call in matcher.calls])

    def test_third_restart_within_window_is_rejected(self):
        guard, device, _ = self.make_guard()

        with self.assertRaises(GameSessionRestarted):
            guard.check(self.popup_screen)
        with self.assertRaises(GameSessionRestarted):
            guard.check(self.popup_screen)
        with self.assertRaises(GameSessionRecoveryError):
            guard.check(self.popup_screen)

        self.assertEqual(device.calls.count("stop_game"), 2)
        self.assertEqual(device.calls.count("start_game"), 2)

    def test_restart_fails_when_main_city_never_returns(self):
        guard, device, _ = self.make_guard(main_city=False)

        with self.assertRaises(GameSessionRecoveryError):
            guard.check(self.popup_screen)

        self.assertEqual(device.calls[:2], ["stop_game", "start_game"])


if __name__ == "__main__":
    unittest.main()
