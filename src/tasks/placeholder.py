"""尚未实现的功能占位任务。"""

from __future__ import annotations

from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus


class PlaceholderTask(BaseTask):
    id = "placeholder"
    name = "占位任务"
    description = "功能开发中"
    required_templates: list[str] = []

    def execute(self, ctx: TaskContext) -> TaskResult:
        return TaskResult(
            TaskStatus.SKIPPED,
            f"「{self.name}」尚未实现，请先采集模板并编写逻辑",
        )
