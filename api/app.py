# -*- coding: utf-8 -*-
"""FastAPI 应用：Job 状态机 + SQLite + 单设备互斥 + 静态 WebUI。"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.device_lock import device_locks
from api.executor import execute_enabled, submit_job
from api.loop import start_scheduler, stop_scheduler
from api.seed import seed_demo_data
from api.settings import load_settings, settings as app_settings
from api.store import redact_secrets, store
from common.models import (
    ExecRoute,
    JobStatus,
    RoleContext,
    RoleTaskConfig,
    TaskImpl,
    TaskKey,
)
from common.registry_meta import list_task_meta
from vision_worker.router import channel_display, resolve_route

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fuzhu.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 重新加载设置（测试可能改过 env/文件）
    global app_settings
    try:
        app_settings = load_settings()
    except Exception as e:  # noqa: BLE001
        log.error("配置加载失败: %s", e)
        raise

    from api.db import configure_db

    configure_db(app_settings.db_path)
    store.reset_for_tests()
    store.initialize()
    store.mark_interrupted_jobs()
    device_locks.clear()
    seed_demo_data(store)
    if app_settings.enable_scheduler:
        start_scheduler(poll_seconds=15.0)
    log.info(
        "API ready host=%s port=%s db=%s allow_lan=%s",
        app_settings.host,
        app_settings.port,
        app_settings.db_path,
        app_settings.allow_lan,
    )
    yield
    stop_scheduler()


app = FastAPI(
    title="fuzhu API",
    description="Phase1：单设备 Web 控制 MVP（vision 真机 + protocol mock）",
    version="0.4.1",
    lifespan=lifespan,
)


# ---------- auth（仅 allow_lan 时要求管理口令；唯一来源 X-Admin-Token 请求头） ----------
def _check_admin(x_admin_token: Optional[str]) -> None:
    """仅校验 HTTP 头 X-Admin-Token。禁止 query/body/cookie 传口令。"""
    if not app_settings.allow_lan:
        return
    expected = (app_settings.admin_token or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="服务器未配置 admin_token")
    provided = (x_admin_token or "").strip()
    # 恒定时间比较；失败响应不回显用户提供的口令
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="需要有效的管理口令（X-Admin-Token）")


@app.middleware("http")
async def admin_token_middleware(request: Request, call_next):
    path = request.url.path
    # allow_lan 时：除 /api/health 外的 /api/* 均需 X-Admin-Token
    if app_settings.allow_lan and path.startswith("/api/") and path != "/api/health":
        try:
            _check_admin(request.headers.get("X-Admin-Token"))
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    return await call_next(request)


# ---------- schemas ----------
class TaskToggleBody(BaseModel):
    enabled: bool


class TaskPatchBody(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(default=None, ge=0, le=24 * 60)
    impl: Optional[TaskImpl] = None


class RoleCreateBody(BaseModel):
    role_id: str
    role_name: str = ""
    server_id: str = ""
    server_name: str = ""
    device_id: Optional[str] = None
    # mock 会话占位：禁止 token/cookie/password 字段名
    mock_session: bool = True


class RoleBindDeviceBody(BaseModel):
    device_id: Optional[str] = None


class RunBody(BaseModel):
    """force_route: protocol | vision；wait: 是否同步等待结束。"""

    force_route: Optional[str] = None
    wait: bool = False


class TaskPanelItem(BaseModel):
    key: str
    name: str
    description: str
    category: str
    enabled: bool
    interval_minutes: int
    impl: str
    resolved_route: str
    channel_label: str
    protocol_ready: bool
    vision_ready: bool
    last_status: Optional[str] = None
    last_message: str = ""
    last_run_at: Optional[str] = None
    last_route: Optional[str] = None
    last_job_id: Optional[str] = None
    last_job_status: Optional[str] = None
    running: bool = False
    queued: bool = False
    active_job_id: Optional[str] = None
    queue_position: Optional[int] = None
    device_running_job_id: Optional[str] = None


# ---------- helpers ----------
def _parse_task_key(key: str) -> TaskKey:
    try:
        return TaskKey(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"未知 task_key: {key}") from e


def _parse_route(value: Optional[str]) -> Optional[ExecRoute]:
    if not value:
        return None
    try:
        return ExecRoute(value)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="force_route 只能是 protocol 或 vision"
        ) from e


def _role_or_404(role_id: str) -> RoleContext:
    role = store.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


def _job_event_dict(event) -> Dict[str, Any]:
    """JobEvent 对外序列化：仅 id/job_id/ts/level/message；message 经安全过滤。"""
    from api.store import safe_event_message

    ts = event.ts.isoformat() if getattr(event, "ts", None) else None
    return {
        "id": event.id,
        "job_id": event.job_id,
        "ts": ts,
        "level": event.level if event.level in ("info", "warn", "error") else "info",
        "message": safe_event_message(event.message),
    }


def _job_dict(job) -> Dict[str, Any]:
    """对外 Job 视图：含诊断字段；不返回 extras（防历史 extras_json 脏值）。"""
    from api.store import safe_public_message, store as _store

    duration = job.duration_ms
    if duration is None and job.started_at and job.finished_at:
        try:
            duration = int((job.finished_at - job.started_at).total_seconds() * 1000)
        except Exception:  # noqa: BLE001
            duration = None

    qpos = None
    if job.route == ExecRoute.VISION:
        qpos = _store.vision_queue_position(job.job_id)
    # running：固定 0；protocol：null
    if job.route == ExecRoute.VISION and job.status == JobStatus.RUNNING:
        qpos = 0

    # channel_label 仅来自 job.route，绝不读 extras_json
    channel_label = (
        "本地识图执行"
        if job.route == ExecRoute.VISION
        else "协议模拟（mock，不会操作游戏）"
    )

    um = safe_public_message(job.user_message or job.message or "")
    return {
        "job_id": job.job_id,
        "role_id": job.role_id,
        "device_id": job.device_id,
        "task_key": job.task_key.value,
        "route": job.route.value,
        "status": job.status.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": duration,
        "failure_code": job.failure_code.value if job.failure_code else None,
        "user_message": um,
        "retryable": job.retryable,
        "queue_position": qpos,
        "result_code": job.result_code.value if job.result_code else None,
        "message": um,
        "channel_label": channel_label,
        "is_terminal": job.status in JobStatus.terminal(),
        # 故意省略 extras：历史库 extras_json 可能含任意敏感值
    }


# ---------- API ----------
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "fuzhu-api",
        "mode": "vision+protocol",
        "phase": 1,
        "scheduler": True,
        "bind": f"{app_settings.host}:{app_settings.port}",
        "allow_lan": app_settings.allow_lan,
        "single_device": True,
        "protocol_is_mock": True,
    }


@app.get("/api/meta")
def meta() -> Dict[str, Any]:
    from common.models import FailureCode

    return {
        "channels": {
            "vision": "本地识图执行",
            "protocol": "协议模拟（mock，不会操作游戏）",
            "unavailable": "不可用",
        },
        "job_statuses": [s.value for s in JobStatus],
        "failure_codes": [c.value for c in FailureCode],
        "queue_position_rules": {
            "vision_running": 0,
            "vision_queued": "1-based FIFO among queued on same device",
            "non_vision": None,
        },
        "phase": 1,
        "limits": {
            "devices": 1,
            "vision_concurrency_per_device": 1,
            "remote_control": False,
            "real_protocol": False,
        },
    }


@app.get("/api/devices")
def list_devices() -> List[Dict[str, Any]]:
    return [d.model_dump(mode="json") for d in store.list_devices()]


@app.get("/api/tasks/catalog")
def task_catalog() -> List[Dict[str, Any]]:
    return [m.model_dump(mode="json") for m in list_task_meta()]


@app.get("/api/roles")
def list_roles() -> List[Dict[str, Any]]:
    out = []
    for r in store.list_roles():
        d = r.model_dump(mode="json")
        d["session"] = redact_secrets(d.get("session") or {})
        out.append(d)
    return out


@app.post("/api/roles")
def create_role(body: RoleCreateBody) -> Dict[str, Any]:
    device_id = body.device_id
    if device_id and not store.get_device(device_id):
        raise HTTPException(status_code=400, detail=f"设备不存在: {device_id}")
    role = RoleContext(
        role_id=body.role_id,
        role_name=body.role_name or body.role_id,
        server_id=body.server_id,
        server_name=body.server_name or body.server_id,
        device_id=device_id,
        session={"mock_session": bool(body.mock_session)},
    )
    store.upsert_role(role)
    return {"ok": True, "role_id": role.role_id, "device_id": role.device_id}


@app.patch("/api/roles/{role_id}/device")
def bind_device(role_id: str, body: RoleBindDeviceBody) -> Dict[str, Any]:
    _role_or_404(role_id)
    if body.device_id and not store.get_device(body.device_id):
        raise HTTPException(status_code=400, detail=f"设备不存在: {body.device_id}")
    role = store.bind_role_device(role_id, body.device_id)
    return {"ok": True, "role_id": role.role_id, "device_id": role.device_id}


@app.get("/api/roles/{role_id}/tasks")
def role_tasks(role_id: str) -> List[TaskPanelItem]:
    role = _role_or_404(role_id)
    cfgs = {c.task_key: c for c in store.list_task_configs(role_id)}
    states = {s.task_key: s for s in store.list_task_states(role_id)}
    device_running = None
    if role.device_id:
        device_running = store.find_running_vision_job(role.device_id)
    items: List[TaskPanelItem] = []
    for meta in list_task_meta():
        cfg = cfgs.get(meta.key) or RoleTaskConfig(task_key=meta.key)
        st = states.get(meta.key)
        route = resolve_route(meta.key, cfg)
        label = channel_display(
            route,
            vision_ready=meta.vision_ready,
            protocol_ready=meta.protocol_ready,
        )
        active = store.find_active_job_for_task(role_id, meta.key)
        is_running = bool(active and active.status == JobStatus.RUNNING)
        is_queued = bool(active and active.status == JobStatus.QUEUED)
        qpos = store.vision_queue_position(active.job_id) if active else None
        items.append(
            TaskPanelItem(
                key=meta.key.value,
                name=meta.name,
                description=meta.description,
                category=meta.category,
                enabled=cfg.enabled,
                interval_minutes=cfg.interval_minutes,
                impl=cfg.impl.value,
                resolved_route=route.value,
                channel_label=label,
                protocol_ready=meta.protocol_ready,
                vision_ready=meta.vision_ready,
                last_status=st.last_status.value if st and st.last_status else None,
                last_message=st.last_message if st else "",
                last_run_at=st.last_run_at.isoformat() if st and st.last_run_at else None,
                last_route=st.last_route.value if st and st.last_route else None,
                last_job_id=st.last_job_id if st else None,
                last_job_status=st.last_job_status.value if st and st.last_job_status else None,
                running=is_running,
                queued=is_queued,
                active_job_id=active.job_id if active else None,
                queue_position=qpos,
                device_running_job_id=device_running.job_id if device_running else None,
            )
        )
    return items


@app.post("/api/roles/{role_id}/tasks/{task_key}/toggle")
def toggle_task(role_id: str, task_key: str, body: TaskToggleBody) -> Dict[str, Any]:
    _role_or_404(role_id)
    key = _parse_task_key(task_key)
    cfg = store.set_task_enabled(role_id, key, body.enabled)
    return {"ok": True, "task_key": key.value, "enabled": cfg.enabled}


@app.patch("/api/roles/{role_id}/tasks/{task_key}")
def patch_task(role_id: str, task_key: str, body: TaskPatchBody) -> Dict[str, Any]:
    _role_or_404(role_id)
    key = _parse_task_key(task_key)
    cfg = store.patch_task_config(
        role_id,
        key,
        enabled=body.enabled,
        interval_minutes=body.interval_minutes,
        impl=body.impl,
    )
    route = resolve_route(key, cfg)
    return {
        "ok": True,
        "config": cfg.model_dump(mode="json"),
        "resolved_route": route.value,
        "channel_label": channel_display(
            route,
            vision_ready=True,
            protocol_ready=True,
        ),
    }


def _submit_payload(sr) -> Dict[str, Any]:
    job = sr.job
    return {
        "ok": job.status
        in (
            JobStatus.SUCCEEDED,
            JobStatus.QUEUED,
            JobStatus.RUNNING,
        ),
        "created": bool(sr.created),
        "reused": bool(sr.reused),
        "queued": bool(sr.queued) or job.status == JobStatus.QUEUED,
        "queue_position": sr.queue_position,
        "running_job_id": sr.running_job_id,
        "job": _job_dict(job),
        "result": {
            "ok": job.status == JobStatus.SUCCEEDED,
            "code": job.result_code.value if job.result_code else job.status.value,
            "message": _job_dict(job).get("message") or "",
            "task_key": job.task_key.value,
            "route": job.route.value,
            "job_id": job.job_id,
            "status": job.status.value,
            "duration_ms": job.duration_ms,
            # 不返回 extras（与 job 视图一致）
        },
    }


@app.post("/api/roles/{role_id}/tasks/{task_key}/run")
def run_task_api(
    role_id: str, task_key: str, body: RunBody | None = None
) -> Dict[str, Any]:
    """立即执行：返回独立 Job；同 task 可复用，跨 task 绝不复用。"""
    _role_or_404(role_id)
    key = _parse_task_key(task_key)
    force = _parse_route(body.force_route if body else None)
    wait = bool(body.wait) if body else False
    sr = submit_job(role_id, key, force_route=force, wait=wait)
    return _submit_payload(sr)


@app.post("/api/roles/{role_id}/run-enabled")
def run_enabled_api(role_id: str) -> Dict[str, Any]:
    """跑已启用：每个 enabled task 恰好对应一个独立 Job（FIFO 串行于同设备）。"""
    _role_or_404(role_id)
    results = execute_enabled(role_id, wait=False)
    jobs_out = []
    for sr in results:
        p = _submit_payload(sr)
        jobs_out.append(
            {
                **p["job"],
                "created": p["created"],
                "reused": p["reused"],
                "queued": p["queued"],
                "queue_position": p["queue_position"],
                "running_job_id": p["running_job_id"],
            }
        )
    return {
        "ok": True,
        "count": len(jobs_out),
        "jobs": jobs_out,
    }


@app.get("/api/devices/{device_id}/queue")
def device_queue(device_id: str) -> Dict[str, Any]:
    """单设备 Vision FIFO 队列快照。"""
    if not store.get_device(device_id):
        raise HTTPException(status_code=404, detail="设备不存在")
    q = store.list_device_vision_queue(device_id)
    running = store.find_running_vision_job(device_id)
    return {
        "device_id": device_id,
        "running_job_id": running.job_id if running else None,
        "queue": [
            {
                **_job_dict(j),
                "queue_position": store.vision_queue_position(j.job_id),
            }
            for j in q
        ],
    }


@app.get("/api/jobs")
def list_jobs_api(
    role_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    st = None
    if status:
        try:
            st = JobStatus(status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="无效 status") from e
    return [_job_dict(j) for j in store.list_jobs(role_id=role_id, status=st, limit=limit)]


@app.get("/api/jobs/{job_id}")
def get_job_api(job_id: str) -> Dict[str, Any]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job 不存在")
    events = store.list_job_events(job_id)
    return {
        "job": _job_dict(job),
        "events": [_job_event_dict(e) for e in events],
    }


@app.get("/api/roles/{role_id}/logs")
def role_logs(
    role_id: str, limit: int = Query(default=50, ge=1, le=200)
) -> List[Dict[str, Any]]:
    _role_or_404(role_id)
    return store.list_logs(role_id=role_id, limit=limit)


@app.get("/api/logs")
def all_logs(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    return store.list_logs(limit=limit)


@app.post("/api/dev/seed")
def dev_seed() -> Dict[str, Any]:
    """幂等演示数据初始化（不覆盖已有）。"""
    return seed_demo_data(store)


# ---------- static web ----------
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/")
def index_page():
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="web/index.html missing")
    return FileResponse(index)


def run() -> None:
    import uvicorn

    s = load_settings()
    uvicorn.run("api.app:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    run()
