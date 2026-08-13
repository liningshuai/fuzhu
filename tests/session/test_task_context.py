import unittest
from unittest.mock import patch

import numpy as np

from src.session.recovery import GameSessionRecoveryError, GameSessionRestarted
from src.tasks.base import BaseTask, TaskContext, TaskStatus
from src.tasks.pipeline_task import PipelineTask


class FakeDevice:
    def __init__(self):
        self.calls = []

    def screenshot(self):
        self.calls.append("screenshot")
        return np.zeros((1920, 1080, 3), dtype=np.uint8)

    def tap(self, x, y):
        self.calls.append(("tap", x, y))


class FakeMatcher:
    def find(self, screen, name, threshold=None, region=None):
        return None


class GuardThatRaises:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def check(self, screen):
        self.calls += 1
        raise self.error


class RaisingTask(BaseTask):
    id = "raising"
    name = "raising"

    def execute(self, ctx):
        ctx.screenshot()
        return None


class TaskContextRecoveryTests(unittest.TestCase):
    def make_context(self, guard):
        return TaskContext(
            device=FakeDevice(),
            matcher=FakeMatcher(),
            session_guard=guard,
        )

    def test_screenshot_checks_guard_before_returning_screen(self):
        guard = GuardThatRaises(GameSessionRestarted("recovered"))
        ctx = self.make_context(guard)

        with self.assertRaises(GameSessionRestarted):
            ctx.screenshot()

        self.assertEqual(guard.calls, 1)

    def test_base_task_marks_successful_session_recovery_for_retry(self):
        task = RaisingTask(enabled=True)
        ctx = self.make_context(GuardThatRaises(GameSessionRestarted("recovered")))

        result = task.run(ctx)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertTrue(result.data["session_recovered"])

    def test_base_task_marks_exhausted_session_recovery_for_shutdown(self):
        task = RaisingTask(enabled=True)
        ctx = self.make_context(GuardThatRaises(GameSessionRecoveryError("limit")))

        result = task.run(ctx)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertTrue(result.data["session_recovery_exhausted"])

    def test_pipeline_task_does_not_swallow_session_recovery(self):
        task = PipelineTask("demo", "demo", enabled=True)

        with patch("src.tasks.pipeline_task.load_pipeline"), patch(
            "src.tasks.pipeline_task.PipelineRunner"
        ) as runner_cls:
            runner_cls.return_value.run.side_effect = GameSessionRestarted("recovered")

            with self.assertRaises(GameSessionRestarted):
                task.execute(self.make_context(None))


if __name__ == "__main__":
    unittest.main()
