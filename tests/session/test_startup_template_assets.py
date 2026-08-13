from pathlib import Path
import unittest

import cv2
import numpy as np

from src.config import config
from src.vision.match import TemplateMatcher


class StartupTemplateAssetTests(unittest.TestCase):
    CASES = {
        "startup_announcement_claim": "startup_announcement_replay.png",
        "startup_enter_game": "startup_enter_game_replay.png",
        "startup_permanent_claim": "startup_permanent_replay.png",
        "startup_highlight_close_hint": "startup_highlight_replay.png",
        "startup_highlight_close_hint_reward": "startup_highlight_reward_replay.png",
    }
    ACTIVITY_TEMPLATE = "startup_activity_current_poster"
    ACTIVITY_REPLAY = "startup_activity_replay.png"
    DEFENSE_TEMPLATE = "startup_command_order_defense"
    DEFENSE_REPLAY = "startup_command_order_defense_replay.png"
    ATTACK_TEMPLATE = "startup_command_order_attack"
    ATTACK_REPLAY = "startup_command_order_attack_replay.png"
    ACTIVITY_PANEL_BOUNDS = {
        "left": 40,
        "top": 700,
        "right": 1040,
        "bottom": 1380,
    }
    ACTIVITY_TEMPLATE_BOUNDS = {
        "left": 49,
        "top": 723,
        "right": 1029,
        "bottom": 1360,
    }
    ACTIVITY_TEMPLATE_SIZE = {
        "width": 980,
        "height": 637,
    }

    def setUp(self):
        self.template_dir = config.root / "assets" / "templates"
        self.replay_dir = config.root / "assets" / "screenshots"
        self.matcher = TemplateMatcher(template_dir=self.template_dir)

    def read_screen(self, name):
        path = self.replay_dir / name
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)

    def assert_activity_template_crop_contract(self, image, match=None, top_left=None):
        self.assertIsNotNone(image)
        height, width = image.shape[:2]
        self.assertEqual(width, self.ACTIVITY_TEMPLATE_SIZE["width"])
        self.assertEqual(height, self.ACTIVITY_TEMPLATE_SIZE["height"])
        self.assertAlmostEqual(
            width / height,
            self.ACTIVITY_TEMPLATE_SIZE["width"]
            / self.ACTIVITY_TEMPLATE_SIZE["height"],
            places=4,
        )

        if match is not None:
            top_left = match.top_left
            self.assertEqual(match.w, width)
            self.assertEqual(match.h, height)

        self.assertIsNotNone(top_left)
        left, top = top_left
        right = left + width
        bottom = top + height

        self.assertEqual(left, self.ACTIVITY_TEMPLATE_BOUNDS["left"])
        self.assertEqual(top, self.ACTIVITY_TEMPLATE_BOUNDS["top"])
        self.assertEqual(right, self.ACTIVITY_TEMPLATE_BOUNDS["right"])
        self.assertEqual(bottom, self.ACTIVITY_TEMPLATE_BOUNDS["bottom"])

        self.assertGreaterEqual(left, self.ACTIVITY_PANEL_BOUNDS["left"])
        self.assertLessEqual(right, self.ACTIVITY_PANEL_BOUNDS["right"])
        self.assertGreaterEqual(top, self.ACTIVITY_PANEL_BOUNDS["top"])
        self.assertLessEqual(bottom, self.ACTIVITY_PANEL_BOUNDS["bottom"])

        self.assertEqual(left, 1080 - right - 2)
        self.assertEqual(1920 - bottom, 560)

    def test_startup_templates_exist_and_are_readable(self):
        for name in self.CASES:
            path = self.template_dir / f"{name}.png"
            self.assertTrue(path.is_file(), path)
            image = self.matcher._load(name)
            self.assertGreater(image.shape[0], 20)
            self.assertGreater(image.shape[1], 20)

    def test_defense_replay_and_template_asset_contract(self):
        screen = self.read_screen(self.DEFENSE_REPLAY)
        self.assertIsNotNone(screen, self.DEFENSE_REPLAY)
        self.assertEqual(screen.shape, (1920, 1080, 3))

        template_path = self.template_dir / f"{self.DEFENSE_TEMPLATE}.png"
        self.assertTrue(template_path.is_file(), template_path)
        image = self.matcher._load(self.DEFENSE_TEMPLATE)
        self.assertGreater(image.shape[0], 20)
        self.assertGreater(image.shape[1], 20)

    def test_attack_replay_and_template_asset_contract(self):
        screen = self.read_screen(self.ATTACK_REPLAY)
        self.assertIsNotNone(screen, self.ATTACK_REPLAY)
        self.assertEqual(screen.shape, (1920, 1080, 3))

        template_path = self.template_dir / f"{self.ATTACK_TEMPLATE}.png"
        self.assertTrue(template_path.is_file(), template_path)
        image = self.matcher._load(self.ATTACK_TEMPLATE)
        self.assertEqual(image.shape, (180, 360, 3))

    def test_each_startup_template_matches_its_replay(self):
        for template_name, replay_name in self.CASES.items():
            screen = self.read_screen(replay_name)
            self.assertIsNotNone(screen, replay_name)
            match = self.matcher.find(screen, template_name, threshold=0.90)
            self.assertIsNotNone(match, template_name)

    def test_enter_game_match_center_is_inside_the_button(self):
        screen = self.read_screen("startup_enter_game_replay.png")
        match = self.matcher.find(screen, "startup_enter_game", threshold=0.90)

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.y, 1334)
        self.assertLessEqual(match.y, 1400)

    def test_activity_replay_is_normalized_and_assets_are_readable(self):
        replay_path = self.replay_dir / self.ACTIVITY_REPLAY
        template_path = self.template_dir / f"{self.ACTIVITY_TEMPLATE}.png"

        self.assertTrue(replay_path.is_file(), replay_path)
        screen = self.read_screen(self.ACTIVITY_REPLAY)
        self.assertIsNotNone(screen, self.ACTIVITY_REPLAY)
        self.assertEqual(screen.shape[:2], (1920, 1080))

        self.assertTrue(template_path.is_file(), template_path)
        image = self.matcher._load(self.ACTIVITY_TEMPLATE)
        self.assertGreater(image.shape[0], 20)
        self.assertGreater(image.shape[1], 20)

    def test_activity_template_matches_replay_inside_activity_panel(self):
        screen = self.read_screen(self.ACTIVITY_REPLAY)
        self.assertIsNotNone(screen, self.ACTIVITY_REPLAY)

        match = self.matcher.find(screen, self.ACTIVITY_TEMPLATE, threshold=0.90)

        self.assertIsNotNone(match, self.ACTIVITY_TEMPLATE)
        self.assertGreaterEqual(match.x, self.ACTIVITY_PANEL_BOUNDS["left"])
        self.assertLessEqual(match.x, self.ACTIVITY_PANEL_BOUNDS["right"])
        self.assertGreaterEqual(match.y, self.ACTIVITY_PANEL_BOUNDS["top"])
        self.assertLessEqual(match.y, self.ACTIVITY_PANEL_BOUNDS["bottom"])

    def test_activity_template_crop_geometry_is_stable(self):
        screen = self.read_screen(self.ACTIVITY_REPLAY)
        image = self.matcher._load(self.ACTIVITY_TEMPLATE)
        match = self.matcher.find(screen, self.ACTIVITY_TEMPLATE, threshold=0.90)

        self.assertIsNotNone(match, self.ACTIVITY_TEMPLATE)
        self.assert_activity_template_crop_contract(image=image, match=match)

    def test_activity_template_policy_rejects_bad_candidate_crops(self):
        screen = self.read_screen(self.ACTIVITY_REPLAY)
        self.assertIsNotNone(screen, self.ACTIVITY_REPLAY)

        bad_candidates = {
            "full_screen": (screen, (0, 0)),
            "outer_chrome_wide_crop": (screen[650:1380, 0:1080], (0, 650)),
            "shifted_left_same_size": (screen[723:1360, 0:980], (0, 723)),
            "shifted_up_same_size": (screen[560:1197, 49:1029], (49, 560)),
        }

        for label, (image, top_left) in bad_candidates.items():
            with self.subTest(label=label):
                with self.assertRaises(AssertionError):
                    self.assert_activity_template_crop_contract(
                        image=image,
                        top_left=top_left,
                    )


if __name__ == "__main__":
    unittest.main()
