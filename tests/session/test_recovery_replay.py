import unittest
from unittest.mock import patch

import numpy as np

from src.bot.engine import BotEngine
from src.session.recovery import GameSessionGuard
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.vision.match import MatchResult


class ReplayDevice:
    def __init__(self):
        self.started = False
        self.calls = []

    def stop_game(self):
        self.calls.append("stop_game")
        self.started = False

    def start_game(self):
        self.calls.append("start_game")
        self.started = True

    def is_online(self):
        return True

    def is_game_foreground(self):
        return True

    def screenshot(self):
        self.calls.append("screenshot")
        value = 2 if self.started else 1
        return np.full((1920, 1080, 3), value, dtype=np.uint8)


class ReplayMatcher:
    def find(self, screen, name, threshold=None, region=None):
        if name in {"duplicate_login_message", "duplicate_login_confirm"}:
            if int(screen[0, 0, 0]) == 1:
                return MatchResult(name, 540, 1000, 0.99, 40, 20)
            return None
        if name == "nav_fief" and int(screen[0, 0, 0]) == 2:
            return MatchResult(name, 80, 1830, 0.99, 40, 40)
        return None


class ReplayTask(BaseTask):
    id = "replay"
    name = "replay"

    def __init__(self):
        super().__init__(enabled=True)
        self.run_calls = 0
        self.calls = 0

    def run(self, ctx):
        self.run_calls += 1
        return super().run(ctx)

    def execute(self, ctx):
        self.calls += 1
        ctx.screenshot()
        return TaskResult(TaskStatus.SUCCESS, "done")


class RecoveryReplayTests(unittest.TestCase):
    def test_popup_restart_main_city_and_same_task_retry(self):
        device = ReplayDevice()
        matcher = ReplayMatcher()
        guard = GameSessionGuard(
            device,
            matcher,
            startup_timeout=1.0,
            poll_interval=0.0,
        )
        engine = BotEngine()
        engine.device = device
        engine.matcher = matcher
        engine.session_guard = guard
        task = ReplayTask()
        ctx = TaskContext(device=device, matcher=matcher, session_guard=guard)

        with patch.object(engine, "refresh_device"):
            result = engine._run_task_with_recovery("replay", task, ctx)

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(task.run_calls, 2)
        self.assertEqual(task.calls, 1)
        self.assertEqual(device.calls[:2], ["screenshot", "stop_game"])
        self.assertIn("start_game", device.calls)
        self.assertFalse(engine._stop.is_set())


if __name__ == "__main__":
    unittest.main()
