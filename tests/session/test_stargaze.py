import unittest
from datetime import date
import tempfile
from unittest.mock import patch
from pathlib import Path

import numpy as np
import yaml
from fastapi import HTTPException

from src.tasks.base import TaskContext, TaskStatus
from src.tasks.registry import create_task, list_task_meta
from src.tasks.stargaze import (
    ACADEMY_SWIPE,
    StargazeTask,
    _save_completed,
    _observe_once,
    find_and_open_academy,
)
from src.config import config
from src.web.app import TaskOptionBody, _TASK_OPTION_KEYS, api_task_option
from src.vision.match import MatchResult


TODAY = date.today().isoformat()
FREE_POINT = (260, 1535)
GOLD_POINT = (820, 1535)
MARKER_POINT = (428, 689)
SAFE_BLANK = (30, 500)


class ReplayDevice:
    def __init__(self, states):
        self.state = states[0]
        self.remaining = iter(states[1:])
        self.taps = []
        self.swipes = []

    def screenshot(self):
        return self.state

    def tap(self, x, y, jitter=True):
        self.taps.append((int(x), int(y)))
        # The task's fixed points are intentionally translated to semantic
        # actions by this replay device.
        action = None
        if (x, y) == MARKER_POINT:
            action = "stargaze_free_marker"
        elif (x, y) == FREE_POINT:
            action = "stargaze_free_item"
        elif (x, y) == GOLD_POINT:
            action = "stargaze_paid_observe"
        elif (x, y) == SAFE_BLANK:
            action = "safe_blank"
        elif self.state == "main":
            action = "nav_fief"
        elif self.state == "fief" and y >= 1700:
            action = "nav_world"
        elif self.state.startswith("dialog_") and y >= 1700:
            action = "nav_world"
        elif self.state.startswith("dialog_") and x < 180 and y < 600:
            action = "stargaze_close"

        if action is not None:
            self.state = next(self.remaining, self.state)

    def swipe(self, x1, y1, x2, y2, duration_ms=400):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        if self.state == "fief":
            self.state = next(self.remaining, self.state)


class ReplayMatcher:
    def __init__(self):
        self.template_dir = None

    def _load(self, name):
        return np.ones((30, 30, 3), dtype=np.uint8)

    def find(self, screen, name, threshold=None, region=None):
        expected = {
            "main": {"nav_fief"},
            "fief": {"stargaze_academy", "nav_world"},
            "academy": {"stargaze_free_marker", "stargaze_academy"},
            "dialog_free": {"stargaze_title", "stargaze_free_item"},
            "dialog_paid": {"stargaze_title", "stargaze_paid_observe"},
            "dialog_unknown": {"stargaze_title"},
            "reward": {"stargaze_reward_popup"},
            "reward_generic": {"startup_highlight_close_hint_reward"},
        }
        if name not in expected.get(screen, set()):
            return None
        points = {
            "nav_fief": (80, 1820),
            "nav_world": (80, 1820),
            "stargaze_academy": (420, 770),
            "stargaze_free_marker": MARKER_POINT,
            "stargaze_free_item": FREE_POINT,
            "stargaze_paid_observe": GOLD_POINT,
            "stargaze_title": (540, 430),
            "stargaze_reward_popup": (540, 960),
            "startup_highlight_close_hint_reward": (540, 1130),
        }
        x, y = points[name]
        return MatchResult(name, x, y, 0.99, 60, 40)


def make_context(device):
    return TaskContext(device=device, matcher=ReplayMatcher())


def run_task(states, meta=None):
    device = ReplayDevice(states)
    task = StargazeTask(enabled=True)
    with patch("src.tasks.stargaze._task_meta", return_value=meta or {}), patch(
        "src.tasks.stargaze.config.set_task_option"
    ), patch("src.tasks.stargaze.config.save_runtime"):
        result = task.run(make_context(device))
    return result, device


class StargazeTaskTests(unittest.TestCase):
    def test_paid_observe_is_recognized_at_realistic_template_score(self):
        class RealisticPaidMatcher(ReplayMatcher):
            def find(self, screen, name, threshold=None, region=None):
                hit = super().find(screen, name, threshold=threshold, region=region)
                if name != "stargaze_paid_observe" or hit is None:
                    return hit
                hit.score = 0.816
                if threshold is not None and threshold > hit.score:
                    return None
                return hit

        device = ReplayDevice(["dialog_paid"])
        context = TaskContext(device=device, matcher=RealisticPaidMatcher())

        self.assertEqual(_observe_once(context), "paid")
        self.assertEqual(device.taps, [])

    def test_academy_search_swipes_toward_left_side(self):
        class SwipeProbeDevice:
            def __init__(self):
                self.swipes = []

            def screenshot(self):
                return "fief"

            def swipe(self, x1, y1, x2, y2, duration_ms=400):
                self.swipes.append((x1, y1, x2, y2, duration_ms))

        class NoMatchMatcher:
            def find(self, screen, name, threshold=None, region=None):
                return None

        device = SwipeProbeDevice()
        context = TaskContext(device=device, matcher=NoMatchMatcher())

        self.assertFalse(find_and_open_academy(context))
        self.assertEqual(device.swipes[0], ACADEMY_SWIPE)
        self.assertLess(device.swipes[0][0], device.swipes[0][2])

    def test_task_is_registered_as_python_base_task(self):
        task = create_task("stargaze")
        self.assertIsInstance(task, StargazeTask)

    def test_registry_exposes_bounded_observation_option(self):
        item = next(item for item in list_task_meta() if item["id"] == "stargaze")
        self.assertTrue(item["implemented"])
        self.assertEqual(item["options"]["max_free_observations"], 3)

    def test_panel_exposes_only_bounded_free_observation_option(self):
        self.assertEqual(_TASK_OPTION_KEYS["stargaze"], {"max_free_observations"})
        with self.assertRaises(HTTPException):
            api_task_option(
                TaskOptionBody(
                    task_id="stargaze",
                    key="max_free_observations",
                    value=4,
                )
            )

    def test_skips_when_completed_today_without_taps(self):
        result, device = run_task(
            ["main"],
            {"last_completed_date": TODAY, "completed_today": True},
        )

        self.assertEqual(result.status, TaskStatus.SKIPPED)
        self.assertEqual(device.taps, [])

    def test_free_observe_is_allowed_but_gold_is_never_tapped(self):
        result, device = run_task(
            ["main", "fief", "academy", "dialog_free", "reward", "dialog_paid", "fief", "main"]
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertIn(FREE_POINT, device.taps)
        self.assertNotIn(GOLD_POINT, device.taps)
        self.assertIn(SAFE_BLANK, device.taps)

    def test_paid_only_stops_without_gold_tap_and_returns_home(self):
        result, device = run_task(
            ["main", "fief", "academy", "dialog_paid", "fief", "main"]
        )

        self.assertEqual(result.status, TaskStatus.SKIPPED)
        self.assertNotIn(GOLD_POINT, device.taps)
        self.assertEqual(device.state, "main")

    def test_paid_stop_after_free_observation_is_recorded_as_success(self):
        result, device = run_task(
            ["main", "fief", "academy", "dialog_free", "reward", "dialog_paid", "fief", "main"]
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.data["stop_reason"], "paid_observe_detected")
        self.assertIn("元宝", result.message)
        self.assertNotIn(GOLD_POINT, device.taps)

    def test_existing_reward_hint_can_close_observe_reward(self):
        result, device = run_task(
            [
                "main",
                "fief",
                "academy",
                "dialog_free",
                "reward_generic",
                "dialog_paid",
                "fief",
                "main",
            ]
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertIn(SAFE_BLANK, device.taps)

    def test_unrecognized_reward_does_not_repeat_free_click(self):
        result, device = run_task(
            ["main", "fief", "academy", "dialog_free", "dialog_free", "fief", "main"]
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(device.taps.count(FREE_POINT), 1)
        self.assertNotIn(SAFE_BLANK, device.taps)
        self.assertEqual(device.state, "main")

    def test_save_completed_writes_daily_state_to_runtime_payload(self):
        original_data = config.raw
        try:
            with tempfile.TemporaryDirectory() as directory:
                runtime_path = Path(directory) / "runtime.yaml"
                with patch("src.config.RUNTIME_CONFIG_PATH", runtime_path), patch(
                    "src.tasks.stargaze._today", return_value=TODAY
                ):
                    _save_completed()
                    payload = yaml.safe_load(
                        runtime_path.read_text(encoding="utf-8")
                    )
        finally:
            config._data = original_data
        self.assertEqual(
            payload["tasks"]["stargaze"]["last_completed_date"], TODAY
        )
        self.assertTrue(payload["tasks"]["stargaze"]["completed_today"])

    def test_unknown_observe_state_fails_without_unbounded_taps(self):
        result, device = run_task(
            ["main", "fief", "academy", "dialog_unknown", "fief", "main"]
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertNotIn(GOLD_POINT, device.taps)
        self.assertLessEqual(len(device.taps), 8)
        self.assertEqual(device.state, "main")


if __name__ == "__main__":
    unittest.main()
