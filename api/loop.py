# -*- coding: utf-8 -*-
"""进程内调度循环：读取开关，按 interval 触发执行（含识图）。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from api.executor import due_enabled_jobs, submit_job  # submit 入队，同设备 FIFO

log = logging.getLogger("fuzhu.api.loop")

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop_body(poll_seconds: float = 15.0) -> None:
    log.info("调度循环启动 poll=%ss", poll_seconds)
    while not _stop.is_set():
        try:
            jobs = due_enabled_jobs()
            for role_id, task_key, cfg in jobs:
                log.info(
                    "调度触发 role=%s task=%s interval=%s",
                    role_id,
                    task_key.value,
                    cfg.interval_minutes,
                )
                try:
                    # 后台执行；设备忙时 submit 会复用已有 Job
                    submit_job(role_id, task_key, wait=False)
                except Exception:  # noqa: BLE001
                    log.exception("调度执行失败 role=%s task=%s", role_id, task_key)
        except Exception:  # noqa: BLE001
            log.exception("调度循环异常")
        _stop.wait(poll_seconds)
    log.info("调度循环已停止")


def start_scheduler(poll_seconds: float = 15.0) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop_body,
        kwargs={"poll_seconds": poll_seconds},
        name="fuzhu-scheduler",
        daemon=True,
    )
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
