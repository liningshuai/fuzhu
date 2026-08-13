import unittest
from unittest.mock import patch

from src.bot.engine import BotEngine
from src.tasks.base import TaskResult, TaskStatus


class FakeTask:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, ctx):
        self.calls.append(ctx)
        return self.results.pop(0)


class FakeContext:
    def __init__(self):
        self.device = object()
        self.matcher = object()
        self.session_guard = object()
        self.state = {}


class BotEngineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = BotEngine()
        self.engine._stop.clear()

    def test_recovery_retries_only_the_same_task(self):
        task = FakeTask(
            [
                TaskResult(
                    TaskStatus.FAILED,
                    "recovered",
                    data={"session_recovered": True},
                ),
                TaskResult(TaskStatus.SUCCESS, "done"),
            ]
        )
        ctx = FakeContext()

        with patch.object(self.engine, "refresh_device") as refresh:
            result = self.engine._run_task_with_recovery("demo", task, ctx)

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(len(task.calls), 2)
        refresh.assert_called_once()
        self.assertFalse(self.engine._stop.is_set())

    def test_exhausted_recovery_stops_engine(self):
        task = FakeTask(
            [
                TaskResult(
                    TaskStatus.FAILED,
                    "recovery limit",
                    data={"session_recovery_exhausted": True},
                )
            ]
        )
        ctx = FakeContext()

        result = self.engine._run_task_with_recovery("demo", task, ctx)

        self.assertTrue(result.data["session_recovery_exhausted"])
        self.assertEqual(len(task.calls), 1)
        self.assertTrue(self.engine._stop.is_set())


if __name__ == "__main__":
    unittest.main()
