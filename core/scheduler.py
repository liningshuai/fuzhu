# -*- coding: utf-8 -*-
"""任务调度：按顺序执行启用的任务，支持循环模式。"""
import logging
import time
from datetime import datetime
from pathlib import Path

from core.task import Task

log = logging.getLogger("fuzhu.scheduler")


class Scheduler:
    def __init__(self, config: dict, adb, base_dir: str):
        self.config = config
        self.adb = adb
        self.base_dir = Path(base_dir)
        self.template_dir = str(self.base_dir / "templates")
        self.tasks_dir = self.base_dir / "tasks"
        # 记录每个任务下次可运行的时间戳
        self._next_run = {}

    # ------------------------------------------------------------------ #
    def _enabled_tasks(self) -> list:
        """返回 config 中启用的任务配置列表，保持定义顺序。"""
        result = []
        for item in self.config.get("tasks", []):
            if item.get("enabled", False):
                result.append(item)
        return result

    def load_task(self, task_file: str) -> Task:
        path = self.tasks_dir / task_file
        return Task(
            str(path), self.adb, self.template_dir,
            package=self.config.get("game", {}).get("package", ""),
        )

    # ------------------------------------------------------------------ #
    def run_once(self) -> None:
        """把启用的任务按顺序各跑一遍。"""
        tasks = self._enabled_tasks()
        if not tasks:
            log.warning("config.yaml 中没有启用任何任务")
            return
        ok, fail = 0, 0
        for item in tasks:
            task = self.load_task(item["file"])
            if task.run():
                ok += 1
            else:
                fail += 1
            time.sleep(2)
        log.info("本轮结束：成功 %d，失败 %d", ok, fail)

    def run_single(self, task_file: str) -> bool:
        return self.load_task(task_file).run()

    def run_loop(self) -> None:
        """循环模式：按每个任务的 interval_minutes 周期性执行。

        interval_minutes 缺省为 0，表示只在启动时跑一次。
        """
        tasks = self._enabled_tasks()
        if not tasks:
            log.warning("config.yaml 中没有启用任何任务")
            return
        log.info("进入循环模式，Ctrl+C 退出。共 %d 个任务", len(tasks))
        now = time.time()
        for item in tasks:
            self._next_run[item["file"]] = now  # 启动先全部跑一遍

        try:
            while True:
                ran_any = False
                for item in tasks:
                    interval = float(item.get("interval_minutes", 0))
                    key = item["file"]
                    nxt = self._next_run.get(key)
                    if nxt is None or time.time() < nxt:
                        continue
                    task = self.load_task(key)
                    task.run()
                    ran_any = True
                    if interval > 0:
                        self._next_run[key] = time.time() + interval * 60
                        log.info(
                            "任务 %s 下次运行: %s", task.name,
                            datetime.fromtimestamp(
                                self._next_run[key]).strftime("%H:%M:%S"),
                        )
                    else:
                        self._next_run[key] = None  # 只跑一次
                    time.sleep(2)
                if not ran_any:
                    time.sleep(10)
        except KeyboardInterrupt:
            log.info("收到 Ctrl+C，退出循环模式")
