import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.config import config
from src.vision.match import MatchResult


class FakeMatcher:
    def __init__(self, *, template_dir=None, matches=None, errors=None):
        self.template_dir = template_dir
        self.matches = matches or {}
        self.errors = errors or {}
        self.calls = []

    def find(self, screen, name, threshold=None, region=None):
        self.calls.append((name, threshold, region))
        error = self.errors.get(name)
        if error is not None:
            raise error
        score = self.matches.get(name)
        if score is None:
            return None
        if threshold is not None and score < threshold:
            return None
        return MatchResult(name, 540, 960, score, 120, 48)


def build_popup_screen():
    screen = np.full((1920, 1080, 3), 32, dtype=np.uint8)
    screen[520:1480, 240:840] = 205
    screen[540:1460, 260:820] = 232
    screen[620:720, 320:760] = 80
    screen[780:820, 320:760] = 88
    screen[930:970, 320:760] = 88
    screen[1080:1120, 320:760] = 88
    return screen


def build_clear_screen():
    return np.full((1920, 1080, 3), 220, dtype=np.uint8)


def build_dim_screen_without_panel_structure():
    return np.full((1920, 1080, 3), 32, dtype=np.uint8)


def build_popup_with_bright_activity_roi_background():
    screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
    screen[400:1650, 20:1060] = 100
    screen[520:1480, 240:840] = 205
    screen[540:1460, 260:820] = 232
    screen[620:720, 320:760] = 80
    screen[780:820, 320:760] = 88
    screen[930:970, 320:760] = 88
    screen[1080:1120, 320:760] = 88
    return screen


def build_command_order_screen(variant="build"):
    """Synthetic 1080x1920 replay of the shared command-order layout.

    The three command types share the same dimmed main-city underlay and
    lower gold banner; their changing title/publisher text is intentionally
    not part of this structural fixture.
    """
    screen = np.full((1920, 1080, 3), 32, dtype=np.uint8)
    screen[400:1650, 20:1060] = 58
    screen[1120:1600, 0:260] = (70, 70, 70)
    # Shared left-side character illustration evidence.  The exact character
    # differs by command type, so the fixture only models bright textured art.
    screen[1160:1510, 70:230] = (95, 155, 190)
    screen[1200:1460, 105:195] = (150, 190, 225)
    colors = {
        "build": ((42, 120, 190), (52, 155, 215)),
        "attack": ((30, 135, 205), (48, 170, 230)),
        "defense": ((48, 110, 175), (68, 145, 205)),
    }
    base, inner = colors[variant]
    screen[1210:1550, 260:1060] = base
    screen[1280:1490, 350:1020] = inner
    screen[1300:1360, 420:980] = (72, 180, 232)
    screen[1420:1480, 420:980] = (40, 105, 170)
    return screen


def build_unknown_gold_overlay_screen():
    screen = np.full((1920, 1080, 3), 32, dtype=np.uint8)
    screen[400:1650, 20:1060] = 58
    screen[1210:1550, 260:1060] = (42, 120, 190)
    screen[1280:1490, 350:1020] = (52, 155, 215)
    return screen


class ActivityPopupDetectorTests(unittest.TestCase):
    def test_live_activity_poster_is_not_blocked_by_weak_legend_confirm_match(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        screenshot_path = config.root / "assets" / "screenshots" / "panel_latest.png"
        data = np.fromfile(str(screenshot_path), dtype=np.uint8)
        screen = cv2.imdecode(data, cv2.IMREAD_COLOR)
        self.assertIsNotNone(screen)

        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )

        match = detector.detect(screen)

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "generic")

    def test_detect_returns_none_for_non_numpy_screen(self):
        from src.session.activity_popup import ActivityPopupDetector

        detector = ActivityPopupDetector(FakeMatcher(template_dir=Path(".")))

        self.assertIsNone(detector.detect("not-an-image"))

    def test_detect_returns_none_when_template_dir_is_missing(self):
        from src.session.activity_popup import ActivityPopupDetector

        detector = ActivityPopupDetector(object())

        self.assertIsNone(detector.detect(build_popup_screen()))

    def test_detect_stops_on_business_blocker_before_activity_templates(self):
        from src.session.activity_popup import ActivityPopupDetector

        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp)
            (template_dir / "startup_activity_flash_sale.png").touch()
            matcher = FakeMatcher(
                template_dir=template_dir,
                matches={
                    "duplicate_login_message": 0.99,
                    "startup_activity_flash_sale": 0.98,
                    "nav_fief": 0.95,
                },
            )

            detector = ActivityPopupDetector(matcher)

            self.assertIsNone(detector.detect(build_popup_screen()))
            self.assertEqual(matcher.calls[0][0], "duplicate_login_message")
            self.assertNotIn(
                "startup_activity_flash_sale",
                [name for name, _, _ in matcher.calls],
            )

    def test_detect_returns_discovered_activity_template_match(self):
        from src.session.activity_popup import ActivityPopupDetector, ActivityPopupMatch

        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp)
            (template_dir / "startup_activity_flash_sale.png").touch()
            matcher = FakeMatcher(
                template_dir=template_dir,
                matches={
                    "nav_fief": 0.93,
                    "startup_activity_flash_sale": 0.91,
                },
            )

            detector = ActivityPopupDetector(matcher)
            match = detector.detect(build_popup_screen())

            self.assertEqual(
                match,
                ActivityPopupMatch(
                    source="template",
                    confidence=0.91,
                    reason="matched startup_activity_flash_sale template",
                ),
            )

    def test_defense_replay_uses_dedicated_template(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "startup_command_order_defense_replay.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)

        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )
        match = detector.detect(screen)

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "command_order_defense_template")

    def test_defense_template_is_blocked_by_business_popup(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=config.root / "assets" / "templates",
            matches={
                "duplicate_login_message": 0.99,
                "startup_command_order_defense": 0.99,
            },
        )

        self.assertIsNone(ActivityPopupDetector(matcher).detect(build_clear_screen()))

    def test_defense_template_ignores_publisher_area_changes(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "startup_command_order_defense_replay.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)
        changed = screen.copy()
        changed[1330:1510, 0:450] = (15, 15, 15)

        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )
        match = detector.detect(changed)

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "command_order_defense_template")

    def test_attack_replay_uses_dedicated_template(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "startup_command_order_attack_replay.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)

        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )
        match = detector.detect(screen)

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "command_order_attack_template")

    def test_attack_template_ignores_publisher_area_changes(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "startup_command_order_attack_replay.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)
        changed = screen.copy()
        changed[1330:1510, 0:450] = (15, 15, 15)

        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )
        match = detector.detect(changed)

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "command_order_attack_template")

    def test_attack_template_is_blocked_by_business_popup(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=config.root / "assets" / "templates",
            matches={
                "duplicate_login_message": 0.99,
                "startup_command_order_attack": 0.99,
            },
        )

        self.assertIsNone(ActivityPopupDetector(matcher).detect(build_clear_screen()))

    def test_bad_activity_template_is_skipped_before_later_valid_template(self):
        from src.session.activity_popup import ActivityPopupDetector, ActivityPopupMatch

        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp)
            (template_dir / "startup_activity_00_bad.png").touch()
            (template_dir / "startup_activity_01_good.png").touch()
            matcher = FakeMatcher(
                template_dir=template_dir,
                matches={
                    "nav_fief": 0.93,
                    "startup_activity_01_good": 0.92,
                },
                errors={
                    "startup_activity_00_bad": FileNotFoundError("bad template"),
                },
            )

            detector = ActivityPopupDetector(matcher)

            self.assertEqual(
                detector.detect(build_popup_screen()),
                ActivityPopupMatch(
                    source="template",
                    confidence=0.92,
                    reason="matched startup_activity_01_good template",
                ),
            )

    def test_detect_returns_generic_match_for_dim_popup_panel(self):
        from src.session.activity_popup import ActivityPopupDetector, ActivityPopupMatch

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.94,
            },
        )

        detector = ActivityPopupDetector(matcher)
        match = detector.detect(build_popup_screen())

        self.assertIsNotNone(match)
        self.assertEqual(match.source, "generic")
        self.assertEqual(match.reason, "main-city-underlay+dim-overlay+central-panel")
        self.assertGreaterEqual(match.confidence, 0.70)

    def test_detects_all_three_command_order_variants(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={"nav_fief": 0.95},
        )
        detector = ActivityPopupDetector(matcher)

        for variant in ("build", "attack", "defense"):
            with self.subTest(variant=variant):
                match = detector.detect(build_command_order_screen(variant))

                self.assertIsNotNone(match)
                self.assertEqual(match.source, "command_order")
                self.assertEqual(
                    match.reason,
                    "main-city-underlay+dim-overlay+command-banner",
                )

    def test_command_order_requires_gold_banner_structure(self):
        from src.session.activity_popup import ActivityPopupDetector

        screen = build_command_order_screen()
        screen[1210:1550, 260:1060] = 58
        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={"nav_fief": 0.95},
        )

        self.assertIsNone(ActivityPopupDetector(matcher).detect(screen))

    def test_command_order_requires_left_character_evidence(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={"nav_fief": 0.95},
        )

        self.assertIsNone(
            ActivityPopupDetector(matcher).detect(
                build_unknown_gold_overlay_screen()
            )
        )

    def test_command_order_is_blocked_by_duplicate_login(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "duplicate_login_message": 0.99,
                "nav_fief": 0.95,
            },
        )

        self.assertIsNone(
                ActivityPopupDetector(matcher).detect(build_command_order_screen())
            )

    def test_command_order_does_not_match_clear_main_city_replay(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "clean_state.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )

        self.assertIsNone(detector.detect(screen))

    def test_command_order_does_not_match_center_highlight_replay(self):
        from src.session.activity_popup import ActivityPopupDetector
        from src.vision.match import TemplateMatcher

        path = config.root / "assets" / "screenshots" / "startup_highlight_replay.png"
        screen = cv2.imdecode(
            np.fromfile(str(path), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        detector = ActivityPopupDetector(
            TemplateMatcher(template_dir=config.root / "assets" / "templates")
        )

        match = detector._detect_command_order(screen)

        self.assertIsNone(match)

    def test_generic_detection_uses_configured_main_city_anchor_threshold(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.89,
            },
        )

        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_popup_screen()))
        self.assertIn(("nav_fief", 0.90, None), matcher.calls)

    def test_detect_returns_none_for_bright_main_city_screen(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.95,
            },
        )

        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_clear_screen()))

    def test_detect_returns_none_when_activity_roi_is_not_dimmed(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.95,
            },
        )
        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_popup_with_bright_activity_roi_background()))

    def test_detect_returns_none_when_central_panel_structure_is_missing(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.95,
            },
        )
        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_dim_screen_without_panel_structure()))

    def test_weak_business_blockers_prevent_generic_activity_detection(self):
        from src.session.activity_popup import ActivityPopupDetector

        for blocker_name, score in (
            ("dialog_confirm_tight", 0.83),
            ("legend_buy_confirm_area", 0.59),
        ):
            with self.subTest(blocker_name=blocker_name):
                matcher = FakeMatcher(
                    template_dir=Path("."),
                    matches={
                        blocker_name: score,
                        "nav_fief": 0.95,
                    },
                )
                detector = ActivityPopupDetector(matcher)

                self.assertIsNone(detector.detect(build_popup_screen()))

    def test_blocker_detection_error_fails_closed_before_generic_activity_detection(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.95,
            },
            errors={
                "duplicate_login_message": FileNotFoundError("missing blocker"),
            },
        )
        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_popup_screen()))

    def test_detect_returns_none_for_nav_fief_or_image_conversion_failures(self):
        from src.session.activity_popup import ActivityPopupDetector

        matcher = FakeMatcher(
            template_dir=Path("."),
            errors={
                "nav_fief": RuntimeError("decode failed"),
            },
        )
        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(build_popup_screen()))

        matcher = FakeMatcher(
            template_dir=Path("."),
            matches={
                "nav_fief": 0.95,
            },
        )
        detector = ActivityPopupDetector(matcher)

        self.assertIsNone(detector.detect(np.zeros((12,), dtype=np.uint8)))


if __name__ == "__main__":
    unittest.main()
