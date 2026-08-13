from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


BLOCKER_TEMPLATES = (
    ("duplicate_login_message", 0.78, None),
    ("duplicate_login_confirm", 0.78, None),
    ("guoguan_buy_title", 0.70, None),
    ("guoguan_buy_confirm", 0.72, None),
    ("legend_buy_title", 0.82, (300, 730, 500, 200)),
    # This crop contains mostly a generic button edge and matches unrelated
    # darkened activity posters.  The larger confirm-area crop below is the
    # reliable purchase-dialog signal.
    ("legend_buy_confirm_area", 0.58, (580, 1050, 430, 420)),
    ("dialog_nation_title", 0.78, None),
    ("dialog_confirm_tight", 0.82, (250, 1050, 650, 450)),
    ("dialog_confirm", 0.80, (250, 1050, 650, 450)),
    ("startup_announcement_claim", 0.90, None),
    ("startup_enter_game", 0.90, None),
    ("startup_permanent_claim", 0.90, None),
)

# The command-order overlay is drawn across the lower part of the city rather
# than as a centered dialog.  Keep this signature deliberately structural so
# 建设令 / 进攻令 / 防守令 share one safe path without OCR or publisher text.
COMMAND_ORDER_REGION = (0, 1050, 1080, 550)
COMMAND_ORDER_HUE_RANGE = (5, 35)
COMMAND_ORDER_SATURATION_MIN = 70
COMMAND_ORDER_VALUE_MIN = 80
COMMAND_ORDER_GOLD_FRACTION_MIN = 0.08
COMMAND_ORDER_BANNER_AREA_MIN = 0.08
COMMAND_ORDER_BANNER_WIDTH_MIN = 0.45
COMMAND_ORDER_BANNER_HEIGHT_MIN = 0.20
COMMAND_ORDER_DIM_MEAN_MAX = 82.0
COMMAND_ORDER_DARK_FRACTION_MIN = 0.70
COMMAND_ORDER_BANNER_TOP_MIN = 0.20
COMMAND_ORDER_CHARACTER_REGION = (0, 1050, 250, 550)
COMMAND_ORDER_CHARACTER_BRIGHT_MIN = 0.10
COMMAND_ORDER_CHARACTER_STD_MIN = 20.0
DEFENSE_COMMAND_TEMPLATE = "startup_command_order_defense"
DEFENSE_COMMAND_TEMPLATE_REGION = (450, 1280, 450, 300)
DEFENSE_COMMAND_TEMPLATE_THRESHOLD = 0.88
ATTACK_COMMAND_TEMPLATE = "startup_command_order_attack"
ATTACK_COMMAND_TEMPLATE_REGION = (450, 1280, 450, 300)
ATTACK_COMMAND_TEMPLATE_THRESHOLD = 0.88


@dataclass(frozen=True)
class ActivityPopupMatch:
    source: str
    confidence: float
    reason: str


class ActivityPopupDetector:
    def __init__(
        self,
        matcher: Any,
        panel_region: tuple[int, int, int, int] = (20, 400, 1040, 1250),
        main_city_threshold: float = 0.90,
        dim_mean_max: float = 92.0,
        dark_fraction_min: float = 0.35,
        panel_score_min: float = 0.55,
        confidence_min: float = 0.70,
    ) -> None:
        self.matcher = matcher
        self.panel_region = panel_region
        self.main_city_threshold = float(main_city_threshold)
        self.dim_mean_max = float(dim_mean_max)
        self.dark_fraction_min = float(dark_fraction_min)
        self.panel_score_min = float(panel_score_min)
        self.confidence_min = float(confidence_min)

    def detect(self, screen: Any) -> ActivityPopupMatch | None:
        if not isinstance(screen, np.ndarray):
            return None

        if self.business_blocker_status(screen) is not False:
            return None

        template_dir = getattr(self.matcher, "template_dir", None)
        if template_dir is None:
            return None

        try:
            template_root = Path(template_dir)
            if not template_root.exists():
                return None
        except Exception:  # noqa: BLE001
            return None

        defense_match = self._detect_defense_template(screen)
        if defense_match is not None:
            return defense_match

        attack_match = self._detect_attack_template(screen)
        if attack_match is not None:
            return attack_match

        try:
            activity_paths = sorted(template_root.glob("startup_activity_*.png"))
        except Exception:  # noqa: BLE001
            activity_paths = ()
        for path in activity_paths:
            name = path.stem
            try:
                hit = self._find(screen, name, threshold=0.70)
            except Exception:  # noqa: BLE001
                continue
            if hit is None:
                continue
            return ActivityPopupMatch(
                source="template",
                confidence=round(float(hit.score), 2),
                reason=f"matched {name} template",
            )

        try:
            command_match = self._detect_command_order(screen)
        except Exception:  # noqa: BLE001
            command_match = None
        if command_match is not None:
            return command_match

        try:
            return self._detect_generic(screen)
        except Exception:  # noqa: BLE001
            return None

    def detect_command_order(self, screen: Any) -> ActivityPopupMatch | None:
        """Detect only 建设令/进攻令/防守令 overlays.

        This narrow entry point is used during task execution so a task's own
        purchase or reward dialog is not mistaken for a command-order popup.
        """
        if not isinstance(screen, np.ndarray):
            return None

        if self.business_blocker_status(screen) is not False:
            return None

        defense_match = self._detect_defense_template(screen)
        if defense_match is not None:
            return defense_match

        attack_match = self._detect_attack_template(screen)
        if attack_match is not None:
            return attack_match

        try:
            return self._detect_command_order(screen)
        except Exception:  # noqa: BLE001
            return None

    def _detect_defense_template(self, screen: np.ndarray) -> ActivityPopupMatch | None:
        template_dir = getattr(self.matcher, "template_dir", None)
        if template_dir is None:
            return None
        try:
            if not Path(template_dir).exists():
                return None
            hit = self._find(
                screen,
                DEFENSE_COMMAND_TEMPLATE,
                threshold=DEFENSE_COMMAND_TEMPLATE_THRESHOLD,
                region=DEFENSE_COMMAND_TEMPLATE_REGION,
            )
        except Exception:  # noqa: BLE001
            return None
        if hit is None:
            return None
        return ActivityPopupMatch(
            source="command_order_defense_template",
            confidence=round(float(hit.score), 2),
            reason="matched startup_command_order_defense template",
        )

    def _detect_attack_template(self, screen: np.ndarray) -> ActivityPopupMatch | None:
        template_dir = getattr(self.matcher, "template_dir", None)
        if template_dir is None:
            return None
        try:
            if not Path(template_dir).exists():
                return None
            hit = self._find(
                screen,
                ATTACK_COMMAND_TEMPLATE,
                threshold=ATTACK_COMMAND_TEMPLATE_THRESHOLD,
                region=ATTACK_COMMAND_TEMPLATE_REGION,
            )
        except Exception:  # noqa: BLE001
            return None
        if hit is None:
            return None
        return ActivityPopupMatch(
            source="command_order_attack_template",
            confidence=round(float(hit.score), 2),
            reason="matched startup_command_order_attack template",
        )

    def business_blocker_status(self, screen: Any) -> bool | None:
        """Return True for a business popup, False when checked cleanly.

        None means the blocker set cannot be checked safely. Callers that may
        perform a blank tap must treat that state as blocked.
        """
        if not isinstance(screen, np.ndarray):
            return None

        template_dir = getattr(self.matcher, "template_dir", None)
        if template_dir is None:
            return None
        try:
            if not Path(template_dir).exists():
                return None
        except Exception:  # noqa: BLE001
            return None

        for name, threshold, region in BLOCKER_TEMPLATES:
            try:
                if self._find(screen, name, threshold=threshold, region=region) is not None:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False

    def _find(self, screen: np.ndarray, name: str, threshold: float, region=None):
        return self.matcher.find(screen, name, threshold=threshold, region=region)

    def _detect_generic(self, screen: np.ndarray) -> ActivityPopupMatch | None:
        try:
            nav_hit = self._find(screen, "nav_fief", threshold=self.main_city_threshold)
        except Exception:  # noqa: BLE001
            return None
        if nav_hit is None:
            return None

        gray = self._to_gray(screen)
        if gray is None:
            return None

        dim_mean, dark_fraction = self._measure_dimming(gray)
        if dim_mean > self.dim_mean_max:
            return None

        if dark_fraction < self.dark_fraction_min:
            return None

        panel_score = self._panel_score(gray)
        if panel_score < self.panel_score_min:
            return None

        nav_score = self._normalize(float(nav_hit.score), self.main_city_threshold, 1.0)
        dim_score = self._normalize(255.0 - dim_mean, 0.0, 255.0)
        dark_score = self._normalize(dark_fraction, self.dark_fraction_min, 1.0)
        confidence = round(
            (panel_score * 0.25)
            + (nav_score * 0.25)
            + (dim_score * 0.20)
            + (dark_score * 0.30),
            2,
        )
        if confidence < self.confidence_min:
            return None

        return ActivityPopupMatch(
            source="generic",
            confidence=confidence,
            reason="main-city-underlay+dim-overlay+central-panel",
        )

    def _detect_command_order(self, screen: np.ndarray) -> ActivityPopupMatch | None:
        """Recognize the shared lower command-order banner structure.

        The three command types use different words and may use different
        publishers, so this method intentionally ignores text.  It requires
        the main-city anchor, dimmed underlay, and a broad connected gold/orange
        banner in the expected lower-screen region before returning a positive
        match.
        """
        try:
            nav_hit = self._find(
                screen,
                "nav_fief",
                threshold=self.main_city_threshold,
            )
        except Exception:  # noqa: BLE001
            return None
        if nav_hit is None:
            return None

        gray = self._to_gray(screen)
        if gray is None:
            return None
        dim_mean, dark_fraction = self._measure_dimming(gray)
        if (
            dim_mean > COMMAND_ORDER_DIM_MEAN_MAX
            or dark_fraction < COMMAND_ORDER_DARK_FRACTION_MIN
        ):
            return None

        cx, cy, cw, ch = COMMAND_ORDER_CHARACTER_REGION
        character = gray[cy : cy + ch, cx : cx + cw]
        if character.size == 0:
            return None
        character_bright_fraction = float((character >= 130).mean())
        character_std = float(character.std())
        if (
            character_bright_fraction < COMMAND_ORDER_CHARACTER_BRIGHT_MIN
            or character_std < COMMAND_ORDER_CHARACTER_STD_MIN
        ):
            return None

        x, y, w, h = COMMAND_ORDER_REGION
        height, width = screen.shape[:2]
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + w)
        bottom = min(height, y + h)
        if left >= right or top >= bottom:
            return None
        region = screen[top:bottom, left:right]
        if region.ndim != 3 or region.shape[2] < 3 or region.size == 0:
            return None

        hsv = cv2.cvtColor(region[:, :, :3], cv2.COLOR_BGR2HSV)
        hue_min, hue_max = COMMAND_ORDER_HUE_RANGE
        gold_mask = cv2.inRange(
            hsv,
            np.array((hue_min, COMMAND_ORDER_SATURATION_MIN, COMMAND_ORDER_VALUE_MIN)),
            np.array((hue_max, 255, 255)),
        )
        gold_fraction = float((gold_mask > 0).mean())
        if gold_fraction < COMMAND_ORDER_GOLD_FRACTION_MIN:
            return None

        kernel = np.ones((9, 9), dtype=np.uint8)
        gold_mask = cv2.morphologyEx(gold_mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            gold_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        area_ratio = float(cv2.contourArea(contour)) / float(region.shape[0] * region.shape[1])
        bx, by, bw, bh = cv2.boundingRect(contour)
        width_ratio = float(bw) / float(region.shape[1])
        height_ratio = float(bh) / float(region.shape[0])
        if (
            area_ratio < COMMAND_ORDER_BANNER_AREA_MIN
            or width_ratio < COMMAND_ORDER_BANNER_WIDTH_MIN
            or height_ratio < COMMAND_ORDER_BANNER_HEIGHT_MIN
            or (float(by) / float(region.shape[0])) < COMMAND_ORDER_BANNER_TOP_MIN
        ):
            return None

        nav_score = self._normalize(float(nav_hit.score), self.main_city_threshold, 1.0)
        dim_score = self._normalize(255.0 - dim_mean, 0.0, 255.0)
        gold_score = self._normalize(gold_fraction, COMMAND_ORDER_GOLD_FRACTION_MIN, 0.40)
        area_score = self._normalize(area_ratio, COMMAND_ORDER_BANNER_AREA_MIN, 0.30)
        width_score = self._normalize(width_ratio, COMMAND_ORDER_BANNER_WIDTH_MIN, 0.95)
        character_bright_score = self._normalize(
            character_bright_fraction,
            COMMAND_ORDER_CHARACTER_BRIGHT_MIN,
            0.60,
        )
        character_texture_score = self._normalize(
            character_std,
            COMMAND_ORDER_CHARACTER_STD_MIN,
            70.0,
        )
        # The hard shape checks above are the safety gate.  Keep the reported
        # confidence in the same range as the existing detector while giving
        # the directly observed banner evidence the largest contribution.
        confidence = round(
            0.40
            + (nav_score * 0.20)
            + (dim_score * 0.15)
            + (gold_score * 0.15)
            + (area_score * 0.05)
            + (width_score * 0.05)
            + (character_bright_score * 0.08)
            + (character_texture_score * 0.02),
            2,
        )
        if confidence < self.confidence_min:
            return None

        return ActivityPopupMatch(
            source="command_order",
            confidence=confidence,
            reason="main-city-underlay+dim-overlay+command-banner",
        )

    def _measure_dimming(self, gray: np.ndarray) -> tuple[float, float]:
        x, y, w, h = self.panel_region
        height, width = gray.shape[:2]
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + w)
        bottom = min(height, y + h)
        if left >= right or top >= bottom:
            return 255.0, 0.0

        roi = gray[top:bottom, left:right]
        if roi.size == 0:
            return 255.0, 0.0

        roi_h, roi_w = roi.shape[:2]
        mask = np.zeros((roi_h, roi_w), dtype=bool)
        vertical_band = max(1, int(roi_w * 0.16))
        horizontal_band = max(1, int(roi_h * 0.12))
        mask[:, :vertical_band] = True
        mask[:, roi_w - vertical_band :] = True
        mask[:horizontal_band, :] = True
        mask[roi_h - horizontal_band :, :] = True

        samples = roi[mask]
        if samples.size == 0:
            return 255.0, 0.0
        return float(samples.mean()), float((samples <= 96).mean())

    def _panel_score(self, gray: np.ndarray) -> float:
        x, y, w, h = self.panel_region
        height, width = gray.shape[:2]
        left = max(0, x)
        top = max(0, y)
        right = min(width, x + w)
        bottom = min(height, y + h)
        if left >= right or top >= bottom:
            return 0.0

        panel = gray[top:bottom, left:right]
        if panel.size == 0:
            return 0.0

        blurred = cv2.GaussianBlur(panel, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 160)
        edge_fraction = float((edges > 0).mean())

        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        max_area_ratio = 0.0
        if contours:
            max_area_ratio = max(cv2.contourArea(contour) for contour in contours) / float(
                panel.shape[0] * panel.shape[1]
            )

        center = panel[
            panel.shape[0] // 4 : (panel.shape[0] * 3) // 4,
            panel.shape[1] // 4 : (panel.shape[1] * 3) // 4,
        ]
        contrast = float(center.std()) if center.size else 0.0

        return round(
            (self._normalize(edge_fraction, 0.0015, 0.0040) * 0.30)
            + (self._normalize(max_area_ratio, 0.10, 0.40) * 0.30)
            + (self._normalize(contrast, 10.0, 60.0) * 0.40),
            2,
        )

    @staticmethod
    def _to_gray(screen: np.ndarray) -> np.ndarray | None:
        try:
            if screen.ndim == 2:
                return screen
            if screen.ndim == 3 and screen.shape[2] >= 3:
                return cv2.cvtColor(screen[:, :, :3], cv2.COLOR_BGR2GRAY)
        except Exception:  # noqa: BLE001
            return None
        return None

    @staticmethod
    def _normalize(value: float, minimum: float, maximum: float) -> float:
        if maximum <= minimum:
            return 0.0
        scaled = (value - minimum) / (maximum - minimum)
        return max(0.0, min(1.0, scaled))
