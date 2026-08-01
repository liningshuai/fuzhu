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
from api.store import (
    build_tech_summary,
    safe_job_extras_for_route,
    store,
)
from common.models import (
    ExecRoute,
    FailureCode,
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
    """仅用于中文展示/日志，不写入 extras_json。"""
    if route == ExecRoute.VISION:
        return "本地识图执行"
    return "协议模拟（mock，不会操作游戏）"


# failure_code → 固定中文安全文案（用户可见，禁止拼接原文）
_FIXED_USER_MSG = {
    FailureCode.DEVICE_NOT_BOUND: "当前角色未绑定本机设备，无法执行识图任务。请先绑定设备后再试。",
    FailureCode.DEVICE_BUSY_OR_QUEUED: "设备正忙或任务排队中，请等待当前任务结束后再试。",
    FailureCode.PRECONDITION_NOT_MET: "未满足任务开始条件（界面可能不在预期位置）。请回到主城或对应界面后重试。",
    FailureCode.TARGET_NOT_FOUND: "未找到预期的界面元素或按钮。请确认游戏画面后稍后重试。",
    FailureCode.POSTCONDITION_NOT_MET: "操作后的界面状态未确认成功，请检查游戏界面后稍后重试。",
    FailureCode.EXECUTION_ERROR: "本地执行出错，请稍后重试。",
    FailureCode.RECOVERED_AFTER_RESTART: "服务曾重启，该任务未能完成。可稍后在控制台手动再次执行。",
}


def fixed_user_message(fc: Optional[FailureCode], *, success: bool = False) -> str:
    if success:
        return "任务已成功完成。"
    if fc and fc in _FIXED_USER_MSG:
        return _FIXED_USER_MSG[fc]
    return "任务状态已更新，详情未展示（安全过滤）。"


def classify_from_message(
    message: str,
    *,
    code: Optional[TaskStatusCode] = None,
    status: Optional[JobStatus] = None,
) -> tuple:
    """返回 (FailureCode|None, user_message, retryable|None)。user_message 仅固定文案。"""
    msg = message or ""
    low = msg.lower()

    if "未绑定" in msg or ("device_id" in low and "绑定" in msg):
        fc = FailureCode.DEVICE_NOT_BOUND
        return fc, fixed_user_message(fc), False
    if "进程重启" in msg or "进程重启中断" in msg:
        fc = FailureCode.RECOVERED_AFTER_RESTART
        return fc, fixed_user_message(fc), True
    if "后置" in msg or "仍未消失" in msg or "后置验证" in msg:
        fc = FailureCode.POSTCONDITION_NOT_MET
        return fc, fixed_user_message(fc), True
    if "前置" in msg or "未等到" in msg or "确认出现" in msg or "未进入" in msg:
        fc = FailureCode.PRECONDITION_NOT_MET
        return fc, fixed_user_message(fc), True
    if (
        "未找到" in msg
        or "超时未找到" in msg
        or "找不到" in msg
        or "未检测到" in msg
        or "无可接受" in msg
    ):
        fc = FailureCode.TARGET_NOT_FOUND
        return fc, fixed_user_message(fc), True
    if code in (
        TaskStatusCode.BLOCKED,
        TaskStatusCode.UNSUPPORTED,
        TaskStatusCode.INVALID_CONFIG,
    ):
        if status == JobStatus.BLOCKED or status is None:
            fc = FailureCode.PRECONDITION_NOT_MET
            return fc, fixed_user_message(fc), True
    if code == TaskStatusCode.BUSY:
        fc = FailureCode.DEVICE_BUSY_OR_QUEUED
        return fc, fixed_user_message(fc), True
    fc = FailureCode.EXECUTION_ERROR
    return fc, fixed_user_message(fc), True


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
            failure_code=FailureCode.PRECONDITION_NOT_MET,
            user_message="角色不存在或配置无效，无法执行。",
            retryable=False,
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
            extras=safe_job_extras_for_route(route),
            failure_code=FailureCode.DEVICE_NOT_BOUND,
            user_message="当前角色未绑定本机设备，无法执行识图任务。请先绑定设备后再试。",
            retryable=False,
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
        user_message="任务已入队，等待执行。",
        retryable=True,
        extras=safe_job_extras_for_route(route),
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

    # 尝试启动：Vision 可能因设备忙保持 queued（不得标 failed）
    if route == ExecRoute.VISION:
        started = _try_start_job(job.job_id)
        if not started:
            running = store.find_running_vision_job(job.device_id or "")
            j2 = store.get_job(job.job_id) or job
            j2.message = "设备忙，保持排队"
            j2.user_message = "设备正忙，任务已排队等待前序任务完成。"
            # 排队说明：failure_code 用 DEVICE_BUSY_OR_QUEUED，status 仍为 queued
            j2.failure_code = FailureCode.DEVICE_BUSY_OR_QUEUED
            j2.retryable = True
            store.update_job(j2)
            store.add_job_event(
                job.job_id,
                f"设备忙，保持 queued"
                + (f"（running={running.job_id}）" if running else ""),
                level="info",
            )
            store.apply_job_to_task_state(store.get_job(job.job_id) or j2)
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
            _finalize_blocked(
                job,
                "角色未绑定设备（device_id），无法执行本地识图。",
                failure_code=FailureCode.DEVICE_NOT_BOUND,
                user_message="当前角色未绑定本机设备，无法执行识图任务。请先绑定设备后再试。",
                retryable=False,
            )
            return
        acquired, owner = device_locks.try_acquire(device_id, job.job_id)
        if not acquired:
            # 进程内锁冲突：重新入队（不得 failed）
            log.warning(
                "device lock busy job=%s owner=%s — requeue", job_id, owner
            )
            store.requeue_job(job_id, message="设备进程锁忙，重新排队")
            j2 = store.get_job(job_id)
            if j2:
                j2.failure_code = FailureCode.DEVICE_BUSY_OR_QUEUED
                j2.user_message = "设备正忙，任务已重新排队。"
                j2.retryable = True
                store.update_job(j2)
            return

    store.add_job_event(job.job_id, "开始执行（已确认 running）")
    # running 时清除排队类 failure_code
    job.user_message = "正在执行…"
    job.failure_code = None
    job.retryable = None
    store.update_job(job)

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
            f"执行异常: {type(e).__name__}",
            task_key=job.task_key,
            route=route,
            extras={"error_type": type(e).__name__},
        )
    finally:
        if route == ExecRoute.VISION and device_id:
            device_locks.release(device_id, job.job_id)

    _apply_task_result(job_id, result)

    # 串行队列：结束后领取下一单
    if route == ExecRoute.VISION and device_id:
        _dispatch_device(device_id)


def _finalize_blocked(
    job: Job,
    message: str,
    *,
    failure_code: Optional[FailureCode] = None,
    user_message: str = "",
    retryable: Optional[bool] = True,
) -> None:
    job.status = JobStatus.BLOCKED
    job.result_code = TaskStatusCode.BLOCKED
    job.message = message
    fc, um, rt = classify_from_message(
        message, code=TaskStatusCode.BLOCKED, status=JobStatus.BLOCKED
    )
    job.failure_code = failure_code or fc
    job.user_message = user_message or um
    job.retryable = retryable if retryable is not None else rt
    job.message = job.user_message
    job.tech_summary = build_tech_summary(
        failure_code=job.failure_code.value if job.failure_code else None,
        result_code=TaskStatusCode.BLOCKED.value,
    )
    job.finished_at = utc_now()
    if job.started_at:
        job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
    else:
        job.duration_ms = 0
    store.update_job(job)
    store.add_job_event(
        job.job_id,
        f"任务结束：status={job.status.value}"
        + (
            f" failure_code={job.failure_code.value}"
            if job.failure_code
            else ""
        ),
        level="error",
    )
    store.apply_job_to_task_state(job)
    if job.device_id and job.route == ExecRoute.VISION:
        _dispatch_device(job.device_id)


def _apply_task_result(job_id: str, result: TaskResult) -> None:
    job = store.get_job(job_id)
    if not job:
        return
    if job.status in JobStatus.terminal():
        return

    # 不落库任意 runner 事件原文；仅固定白名单文案
    if result.events:
        step_msg = "任务步骤已记录"
        if (result.extras or {}).get("fake") is True:
            step_msg = "任务步骤已记录（fake runner）"
        elif job.route == ExecRoute.PROTOCOL or result.route == ExecRoute.PROTOCOL:
            step_msg = "任务步骤已记录（protocol mock）"
        elif job.route == ExecRoute.VISION:
            step_msg = "任务步骤已记录（vision）"
        store.add_job_event(job_id, step_msg, level="info")
    if result.screenshot_paths:
        store.add_job_event(job_id, "截图已保存（路径不展示）", level="info")

    status = _map_result_to_job_status(result)
    job.status = status
    job.result_code = result.code
    # 禁止持久化 TaskResult.extras；仅固定 channel 元数据
    job.extras = safe_job_extras_for_route(job.route)
    job.finished_at = result.finished_at or utc_now()
    if job.started_at and job.finished_at:
        try:
            job.duration_ms = int(
                (job.finished_at - job.started_at).total_seconds() * 1000
            )
        except Exception:  # noqa: BLE001
            job.duration_ms = result.duration_ms
    elif result.duration_ms is not None:
        job.duration_ms = result.duration_ms
    else:
        job.duration_ms = None

    err_type = None
    if isinstance(result.extras, dict):
        et = result.extras.get("error_type")
        if isinstance(et, str):
            err_type = et

    if status == JobStatus.SUCCEEDED:
        job.failure_code = None
        job.user_message = fixed_user_message(None, success=True)
        job.message = job.user_message
        job.retryable = None
        job.tech_summary = ""
    else:
        fc, um, rt = classify_from_message(
            result.message or "", code=result.code, status=status
        )
        if fc == FailureCode.TARGET_NOT_FOUND and result.code == TaskStatusCode.BLOCKED:
            job.status = JobStatus.BLOCKED
        job.failure_code = fc
        job.user_message = um
        job.message = um  # 库内 message 也不保留原文
        job.retryable = rt
        job.tech_summary = build_tech_summary(
            failure_code=fc.value if fc else None,
            result_code=result.code.value if result.code else None,
            error_type=err_type,
        )

    store.update_job(job)
    level = "info" if status == JobStatus.SUCCEEDED else "error"
    end_msg = f"任务结束：status={job.status.value}"
    if job.failure_code:
        end_msg += f" failure_code={job.failure_code.value}"
    store.add_job_event(job_id, end_msg, level=level)
    store.apply_job_to_task_state(job)
    log.info(
        "job done id=%s task=%s status=%s failure=%s",
        job_id,
        job.task_key.value,
        job.status.value,
        job.failure_code.value if job.failure_code else "-",
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
