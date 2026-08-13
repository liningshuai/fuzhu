"""把通用 Pipeline 适配为现有 BaseTask。"""

from __future__ import annotations

from src.config import config
from src.pipeline.loader import PipelineConfigError, load_pipeline
from src.pipeline.result import PipelineStatus
from src.pipeline.runner import PipelineRunner
from src.session.recovery import GameSessionRecoveryError, GameSessionRestarted
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus


class PipelineTask(BaseTask):
    def __init__(self, task_id: str, pipeline_id: str, enabled: bool = False) -> None:
        self.id = task_id
        self.pipeline_id = pipeline_id
        self.name = task_id
        self.description = f"Pipeline: {pipeline_id}"
        super().__init__(enabled=enabled)

    def execute(self, ctx: TaskContext) -> TaskResult:
        path = config.root / "config" / "pipelines" / f"{self.pipeline_id}.yaml"
        try:
            definition = load_pipeline(path)
            result = PipelineRunner(ctx).run(definition)
        except (GameSessionRestarted, GameSessionRecoveryError):
            raise
        except PipelineConfigError as exc:
            return TaskResult(TaskStatus.NOT_READY, str(exc))
        except Exception as exc:  # noqa: BLE001
            return TaskResult(TaskStatus.FAILED, str(exc))

        message = result.message
        if result.trace and result.trace[-1].error:
            message = f"{message}；{result.trace[-1].error}"
        if result.status is PipelineStatus.SUCCESS:
            status = TaskStatus.SUCCESS
        elif result.status is PipelineStatus.NOT_READY:
            status = TaskStatus.NOT_READY
        else:
            status = TaskStatus.FAILED
        return TaskResult(status, message, data={"pipeline": self.pipeline_id})
