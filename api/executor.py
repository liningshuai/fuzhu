# -*- coding: utf-8 -*-
"""统一 Job 执行：单设备 FIFO 队列 + 状态机 + 后台运行。

规则摘要：
- 同一 device_id 任意时刻最多 1 个 Vision Job 为 running
- 不同 task 各自独立 Job；忙时后来者保持 queued，不复用他 task 的 job_id
- 同 role+task 的重复请求可复用该 task 已有的 queued/running Job
- queued Job 不启动 ADB、不占设备锁；running 结束后原子领取队首
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from api.device_lock import device_locks
from api.store import redact_secrets, store
from common.models import (
    ExecRoute,
    Job,
    JobStatus,
    TaskKey,
    TaskResult,
    TaskStatusCode,
    utc_now,
)
from common.registry_meta import TASK_CATALOG
from vision_worker.router import resolve_route, run_task

log = logging.getLogger("fuzhu.api.executor")

TaskRunner = Callable[..., TaskResult]
_task_runner: Optional[TaskRunner] = None
_dispatch_guard = threading.Lock()


def set_task_runner(runner: Optional[TaskRunner]) -> None:
    global _task_runner
    _task_runner = runner


def get_task_runner() -> TaskRunner:
    return _task_runner or run_task


@dataclass
class SubmitResult:
    job: Job
    created: bool
    reused: bool
    queued: bool
    queue_position: Optional[int] = None
    running_job_id: Optional[str] = None


def _map_result_to_job_status(result: TaskResult) -> JobStatus:
    if result.ok and result.code == TaskStatusCode.OK:
        return JobStatus.SUCCEEDED
    if result.code in (TaskStatusCode.BLOCKED, TaskStatusCode.BUSY):
        return JobStatus.BLOCKED
    if result.code == TaskStatusCode.SKIPPED:
        return JobStatus.SUCCEEDED
    if result.code == TaskStatusCode.UNSUPPORTED:
        return JobStatus.BLOCKED
    if result.code == TaskStatusCode.INVALID_CONFIG:
        return JobStatus.BLOCKED
    return JobStatus.FAILED


def _channel_label(route: ExecRoute) -> str:
    if route == ExecRoute.VISION:
        return "本地识图执行"
    return "协议模拟（mock，不会操作游戏）"


def _enrich_meta(job: Job) -> SubmitResult:
    """根据当前 Job/设备状态填充 queue 元数据。"""
    job = store.get_job(job.job_id) or job
    created = False  # caller overrides
    reused = False
    queued = job.status == JobStatus.QUEUED
    qpos: Optional[int] = None
    running_id: Optional[str] = None

    if job.route == ExecRoute.VISION and job.device_id:
        running = store.find_running_vision_job(job.device_id)
        running_id = running.job_id if running else None
        qpos = store.vision_queue_position(job.job_id)
    elif job.status == JobStatus.RUNNING:
        running_id = job.job_id
        qpos = 0
    elif job.status == JobStatus.QUEUED:
        qpos = None

    return SubmitResult(
        job=job,
        created=created,
        reused=reused,
        queued=queued,
        queue_position=qpos,
        running_job_id=running_id,
    )


def _wait_terminal(job_id: str, timeout: float = 120.0) -> Job:
    deadline = time.time() + timeout
    last = store.get_job(job_id)
    while time.time() < deadline:
        last = store.get_job(job_id)
        if last and last.status in JobStatus.terminal():
            return last
        time.sleep(0.02)
    return last or Job(
        job_id=job_id,
        role_id="",
        task_key=TaskKey.MAIL,
        route=ExecRoute.PROTOCOL,
        status=JobStatus.FAILED,
        message="等待 Job 终态超时",
    )


def _start_worker(job_id: str) -> None:
    t = threading.Thread(
        target=_execute_running_job,
        args=(job_id,),
        name=f"job-{job_id[:8]}",
        daemon=True,
    )
    t.start()


def _try_start_job(job_id: str) -> bool:
    """原子领取：queued → running；成功则启动 worker。"""
    claimed = store.try_claim_job(job_id)
    if not claimed:
        return False
    store.add_job_event(job_id, "领取执行权，进入 running")
    store.apply_job_to_task_state(claimed)
    _start_worker(job_id)
    return True


def _dispatch_device(device_id: Optional[str]) -> None:
    """设备空闲时领取队首 Vision Job。"""
    if not device_id:
        return
    with _dispatch_guard:
        nxt = store.claim_next_vision_job(device_id)
        if not nxt:
            return
        store.add_job_event(nxt.job_id, "FIFO 出队，进入 running")
        store.apply_job_to_task_state(nxt)
        _start_worker(nxt.job_id)


def submit_job(
    role_id: str,
    task_key: TaskKey,
    *,
    force_route: Optional[ExecRoute] = None,
    wait: bool = False,
) -> SubmitResult:
    role = store.get_role(role_id)
    if not role:
        job = Job(
            role_id=role_id,
            task_key=task_key,
            route=force_route or ExecRoute.PROTOCOL,
            status=JobStatus.BLOCKED,
            message=f"角色不存在: {role_id}",
            result_code=TaskStatusCode.INVALID_CONFIG,
            finished_at=utc_now(),
            duration_ms=0,
        )
        store.create_job(job)
        store.add_job_event(job.job_id, job.message, level="error")
        return SubmitResult(
            job=job, created=True, reused=False, queued=False, queue_position=None
        )

    cfg = store.get_task_config(role_id, task_key)
    route = force_route or resolve_route(task_key, cfg)
    device_id = role.device_id if route == ExecRoute.VISION else role.device_id

    if route == ExecRoute.VISION and not role.device_id:
        job = Job(
            role_id=role_id,
            device_id=None,
            task_key=task_key,
            route=route,
            status=JobStatus.BLOCKED,
            message="角色未绑定设备（device_id），无法执行本地识图。请先绑定唯一本机设备。",
            result_code=TaskStatusCode.BLOCKED,
            finished_at=utc_now(),
            duration_ms=0,
            extras={"channel": _channel_label(route)},
        )
        store.create_job(job)
        store.add_job_event(job.job_id, job.message, level="error")
        store.apply_job_to_task_state(job)
        return SubmitResult(
            job=job, created=True, reused=False, queued=False, queue_position=None
        )

    draft = Job(
        role_id=role_id,
        device_id=role.device_id if route == ExecRoute.VISION else role.device_id,
        task_key=task_key,
        route=route,
        status=JobStatus.QUEUED,
        message="已入队",
        extras={
            "channel": _channel_label(route),
            "impl": cfg.impl.value if cfg else "auto",
        },
    )

    # 原子：同 role+task 复用，或创建独立 Job（绝不复用其他 task）
    job, created = store.create_or_reuse_active_job(draft)
    if not created:
        store.add_job_event(
            job.job_id,
            f"重复请求：复用同 task={task_key.value} 的 Job（禁止跨 task 复用）",
            level="warn",
        )
        meta = _enrich_meta(job)
        meta.created = False
        meta.reused = True
        if wait and job.status not in JobStatus.terminal():
            # 若仍 queued，尝试推动调度
            if job.status == JobStatus.QUEUED:
                if job.route == ExecRoute.VISION:
                    _dispatch_device(job.device_id)
                else:
                    _try_start_job(job.job_id)
            job = _wait_terminal(job.job_id)
            meta = _enrich_meta(job)
            meta.created = False
            meta.reused = True
        return meta

    store.add_job_event(
        job.job_id,
        f"Job 创建：task={task_key.value} route={route.value}（独立 Job，FIFO 队列）",
    )
    store.apply_job_to_task_state(job)

    # 尝试启动：Vision 可能因设备忙保持 queued
    if route == ExecRoute.VISION:
        started = _try_start_job(job.job_id)
        if not started:
            running = store.find_running_vision_job(job.device_id or "")
            store.add_job_event(
                job.job_id,
                f"设备忙，保持 queued"
                + (f"（running={running.job_id}）" if running else ""),
                level="info",
            )
            store.apply_job_to_task_state(store.get_job(job.job_id) or job)
    else:
        # protocol mock：不占设备队列，可立即执行
        _try_start_job(job.job_id)

    if wait:
        # 推动一次调度，避免仅入队永远不跑
        if route == ExecRoute.VISION:
            _dispatch_device(job.device_id)
        job = _wait_terminal(job.job_id)
    else:
        job = store.get_job(job.job_id) or job

    meta = _enrich_meta(job)
    meta.created = True
    meta.reused = False
    return meta


def _execute_running_job(job_id: str) -> None:
    """仅执行已处于 running 的 Job（领取动作在 DB 层完成）。"""
    job = store.get_job(job_id)
    if not job:
        return
    if job.status != JobStatus.RUNNING:
        # 可能已被重启标记 failed
        return

    role = store.get_role(job.role_id)
    cfg = store.get_task_config(job.role_id, job.task_key)
    route = job.route
    device_id = job.device_id if route == ExecRoute.VISION else None

    if route == ExecRoute.VISION:
        if not device_id:
            _finalize_blocked(job, "角色未绑定设备（device_id），无法执行本地识图。")
            return
        acquired, owner = device_locks.try_acquire(device_id, job.job_id)
        if not acquired:
            # 进程内锁冲突：重新入队，避免伪造成功/失败吞任务
            log.warning(
                "device lock busy job=%s owner=%s — requeue", job_id, owner
            )
            store.requeue_job(job_id, message="设备进程锁忙，重新排队")
            return

    store.add_job_event(job.job_id, "开始执行（已确认 running，可访问 ADB/mock）")

    try:
        if not role:
            result = TaskResult.fail(
                TaskStatusCode.INVALID_CONFIG,
                f"角色不存在: {job.role_id}",
                task_key=job.task_key,
                route=route,
            )
        else:
            runner = get_task_runner()
            result = runner(
                job.task_key,
                role,
                cfg,
                force_route=route,
            )
            if result.task_key is None:
                result.task_key = job.task_key
            if result.route is None:
                result.route = route
    except Exception as e:  # noqa: BLE001
        log.exception("job %s unexpected error", job_id)
        result = TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            f"执行异常: {e}",
            task_key=job.task_key,
            route=route,
        )
    finally:
        if route == ExecRoute.VISION and device_id:
            device_locks.release(device_id, job.job_id)

    _apply_task_result(job_id, result)

    # 串行队列：结束后领取下一单
    if route == ExecRoute.VISION and device_id:
        _dispatch_device(device_id)


def _finalize_blocked(job: Job, message: str) -> None:
    job.status = JobStatus.BLOCKED
    job.result_code = TaskStatusCode.BLOCKED
    job.message = message
    job.finished_at = utc_now()
    if job.started_at:
        job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
    else:
        job.duration_ms = 0
    store.update_job(job)
    store.add_job_event(job.job_id, message, level="error")
    store.apply_job_to_task_state(job)
    if job.device_id and job.route == ExecRoute.VISION:
        _dispatch_device(job.device_id)


def _apply_task_result(job_id: str, result: TaskResult) -> None:
    job = store.get_job(job_id)
    if not job:
        return
    if job.status in JobStatus.terminal():
        return

    for ev in result.events or []:
        store.add_job_event(job_id, ev, level="info")
    for path in result.screenshot_paths or []:
        store.add_job_event(
            job_id, "截图已保存", level="info", screenshot_path=str(path)
        )

    status = _map_result_to_job_status(result)
    job.status = status
    job.result_code = result.code
    job.message = result.message or ""
    extras = redact_secrets(dict(result.extras or {}))
    extras["channel"] = _channel_label(job.route)
    if result.screenshot_paths:
        extras["screenshot_paths"] = list(result.screenshot_paths)
    job.extras = {**(job.extras or {}), **extras}
    job.finished_at = result.finished_at or utc_now()
    if job.started_at:
        job.duration_ms = int(
            (job.finished_at - job.started_at).total_seconds() * 1000
        )
    elif result.duration_ms is not None:
        job.duration_ms = result.duration_ms
    else:
        job.duration_ms = 0

    store.update_job(job)
    level = "info" if status == JobStatus.SUCCEEDED else "error"
    store.add_job_event(
        job_id,
        f"结束 status={status.value} code={result.code.value}: {job.message}",
        level=level,
    )
    store.apply_job_to_task_state(job)
    log.info(
        "job done id=%s task=%s status=%s",
        job_id,
        job.task_key.value,
        status.value,
    )


def execute_one(
    role_id: str,
    task_key: TaskKey,
    *,
    force_route: Optional[ExecRoute] = None,
    wait: bool = True,
) -> Job:
    return submit_job(
        role_id, task_key, force_route=force_route, wait=wait
    ).job


def execute_enabled(role_id: str, *, wait: bool = False) -> List[SubmitResult]:
    """为每个 enabled 任务各建/复用一个 Job；count == 独立 Job 数。"""
    results: List[SubmitResult] = []
    cfgs = {c.task_key: c for c in store.list_task_configs(role_id)}
    for key in TASK_CATALOG.keys():
        cfg = cfgs.get(key)
        if not cfg or not cfg.enabled:
            continue
        results.append(submit_job(role_id, key, wait=False))
    if not wait:
        return results
    out: List[SubmitResult] = []
    for sr in results:
        j = _wait_terminal(sr.job.job_id)
        meta = _enrich_meta(j)
        meta.created = sr.created
        meta.reused = sr.reused
        out.append(meta)
    return out


def due_enabled_jobs(now_ts: float | None = None) -> List[tuple]:
    import time as _time

    now = now_ts if now_ts is not None else _time.time()
    jobs = []
    for role in store.list_roles():
        for cfg in store.list_task_configs(role.role_id):
            if not cfg.enabled:
                continue
            st = store.get_task_state(role.role_id, cfg.task_key)
            interval = max(0, int(cfg.interval_minutes or 0))
            if interval <= 0:
                continue
            active = store.find_active_job_for_task(role.role_id, cfg.task_key)
            if active:
                continue
            if st and st.last_run_at:
                elapsed = now - st.last_run_at.timestamp()
                if elapsed < interval * 60:
                    continue
            jobs.append((role.role_id, cfg.task_key, cfg))
    return jobs
