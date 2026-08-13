import unittest

from src.config import config
from src.session.recovery import GameSessionGuard
from src.vision.match import TemplateMatcher


class DuplicateLoginTemplateAssetTests(unittest.TestCase):
    def setUp(self):
        self.template_dir = config.root / "assets" / "templates"
        self.matcher = TemplateMatcher(template_dir=self.template_dir)
        self.replay_screen_path = (
            config.root / "assets" / "screenshots" / "duplicate_login_replay.png"
        )
        self.current_screen_path = (
            config.root
            / "assets"
            / "screenshots"
            / "duplicate_login_negative.png"
        )

    def test_duplicate_login_templates_are_readable(self):
        for name in ("duplicate_login_message", "duplicate_login_confirm"):
            path = self.template_dir / f"{name}.png"
            self.assertTrue(path.is_file(), path)
            image = self.matcher._load(name)
            self.assertGreater(image.shape[0], 20)
            self.assertGreater(image.shape[1], 20)

    def test_duplicate_login_templates_match_replay_screenshot(self):
        import cv2

        screen = cv2.imdecode(
            __import__("numpy").fromfile(str(self.replay_screen_path), dtype="uint8"),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)
        for name in ("duplicate_login_message", "duplicate_login_confirm"):
            match = self.matcher.find(screen, name, threshold=0.95)
            self.assertIsNotNone(match, name)

    def test_current_announcement_screen_is_not_duplicate_login(self):
        import cv2

        screen = cv2.imdecode(
            __import__("numpy").fromfile(str(self.current_screen_path), dtype="uint8"),
            cv2.IMREAD_COLOR,
        )
        guard = GameSessionGuard(device=object(), matcher=self.matcher)

        self.assertFalse(guard.is_duplicate_login(screen))


class StargazeTemplateAssetTests(unittest.TestCase):
    REPLAYS = {
        "stargaze_main_city_replay.png",
        "stargaze_fief_replay.png",
        "stargaze_academy_replay.png",
        "stargaze_dialog_replay.png",
    }
    TEMPLATE_REPLAYS = {
        "stargaze_academy": "stargaze_academy_replay.png",
        "stargaze_free_marker": "stargaze_academy_replay.png",
        "stargaze_title": "stargaze_dialog_replay.png",
        "stargaze_free_item": "stargaze_dialog_replay.png",
        "stargaze_paid_observe": "stargaze_dialog_replay.png",
        "stargaze_close": "stargaze_dialog_replay.png",
    }

    def setUp(self):
        self.replay_dir = config.root / "assets" / "screenshots"
        self.template_dir = config.root / "assets" / "templates"
        self.matcher = TemplateMatcher(template_dir=self.template_dir)

    def read_screen(self, name):
        import cv2
        import numpy as np

        data = np.fromfile(str(self.replay_dir / name), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)

    def test_stargaze_replays_are_normalized(self):
        for name in self.REPLAYS:
            image = self.read_screen(name)
            self.assertIsNotNone(image, name)
            self.assertEqual(image.shape, (1920, 1080, 3))

    def test_stargaze_templates_are_readable_and_match_replays(self):
        for template_name, replay_name in self.TEMPLATE_REPLAYS.items():
            path = self.template_dir / f"{template_name}.png"
            self.assertTrue(path.is_file(), path)
            image = self.matcher._load(template_name)
            self.assertGreater(image.shape[0], 20)
            self.assertGreater(image.shape[1], 20)
            screen = self.read_screen(replay_name)
            match = self.matcher.find(screen, template_name, threshold=0.90)
            self.assertIsNotNone(match, template_name)

    def test_free_and_paid_templates_are_separate_safety_signals(self):
        screen = self.read_screen("stargaze_dialog_replay.png")
        free = self.matcher.find(screen, "stargaze_free_item", threshold=0.90)
        paid = self.matcher.find(screen, "stargaze_paid_observe", threshold=0.90)
        self.assertIsNotNone(free)
        self.assertIsNotNone(paid)
        self.assertGreater(paid.x, free.x)


if __name__ == "__main__":
    unittest.main()
