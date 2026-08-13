import unittest
from unittest.mock import patch

from src.config import config
from src.pipeline.result import PipelineResult, PipelineStatus
from src.tasks.auto_mail import AutoMailTask
from src.tasks.base import TaskStatus
from src.tasks.pipeline_task import PipelineTask
from src.tasks.registry import create_task


class PipelineTaskTests(unittest.TestCase):
    def tearDown(self):
        config.set_task_option("auto_mail", "implementation", "python")
        config.set_task_option("auto_mail", "pipeline", "auto_mail")

    def test_python_implementation_still_creates_existing_task(self):
        config.set_task_option("auto_mail", "implementation", "python")

        task = create_task("auto_mail")

        self.assertIsInstance(task, AutoMailTask)

    def test_pipeline_implementation_creates_pipeline_task(self):
        config.set_task_option("auto_mail", "implementation", "pipeline")
        config.set_task_option("auto_mail", "pipeline", "auto_mail")

        task = create_task("auto_mail")

        self.assertIsInstance(task, PipelineTask)
        self.assertEqual(task.pipeline_id, "auto_mail")

    def test_pipeline_status_maps_to_task_status(self):
        fake_result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            message="done",
            trace=(),
        )
        task = PipelineTask("auto_mail", "auto_mail", enabled=True)

        with patch("src.tasks.pipeline_task.load_pipeline"), patch(
            "src.tasks.pipeline_task.PipelineRunner"
        ) as runner_cls:
            runner_cls.return_value.run.return_value = fake_result
            result = task.execute(object())

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertIn("done", result.message)


if __name__ == "__main__":
    unittest.main()
