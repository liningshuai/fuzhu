# -*- coding: utf-8 -*-
"""SQLite 仓储：角色、任务配置/状态、设备、Job、事件。

进程内唯一数据源；不再使用内存 store。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from api.db import close_thread_connection, connect, init_schema
from common.models import (
    DeviceTarget,
    ExecRoute,
    Job,
    JobEvent,
    JobStatus,
    RoleContext,
    RoleTaskConfig,
    RoleTaskState,
    TaskImpl,
    TaskKey,
    TaskResult,
    TaskStatusCode,
    utc_now,
)
from common.registry_meta import TASK_CATALOG

log = logging.getLogger("fuzhu.api.store")

# 禁止写入日志/接口的秘密字段名
_SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "mock_token",
        "cookie",
        "cookies",
        "authorization",
        "session_key",
        "secret",
        "access_token",
        "refresh_token",
    }
)


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "+00:00"
    return dt.isoformat()


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj if obj is not None else {}, ensure_ascii=False, default=str)


def _json_loads(s: Optional[str]) -> Any:
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


def redact_secrets(data: Any) -> Any:
    """递归去除敏感字段名（token/cookie/password 等），不落库、不进接口。"""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            lk = str(k).lower()
            if lk in _SECRET_KEYS or any(
                s in lk for s in ("token", "cookie", "password", "authorization", "passwd")
            ):
                continue
            out[k] = redact_secrets(v)
        return out
    if isinstance(data, list):
        return [redact_secrets(x) for x in data]
    return data


class SQLiteStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._ready = False

    def initialize(self) -> None:
        with self._lock:
            init_schema()
            self._ready = True

    def ensure_ready(self) -> None:
        if not self._ready:
            self.initialize()

    # ---- devices ----
    def upsert_device(self, device: DeviceTarget) -> DeviceTarget:
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO devices(device_id, adb_serial, name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    adb_serial=excluded.adb_serial,
                    name=excluded.name
                """,
                (
                    device.device_id,
                    device.adb_serial,
                    device.name,
                    _dt_to_str(device.created_at) or _dt_to_str(utc_now()),
                ),
            )
        return device

    def get_device(self, device_id: str) -> Optional[DeviceTarget]:
        self.ensure_ready()
        row = connect().execute(
            "SELECT * FROM devices WHERE device_id=?", (device_id,)
        ).fetchone()
        if not row:
            return None
        return DeviceTarget(
            device_id=row["device_id"],
            adb_serial=row["adb_serial"],
            name=row["name"] or "",
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
        )

    def list_devices(self) -> List[DeviceTarget]:
        self.ensure_ready()
        rows = connect().execute(
            "SELECT * FROM devices ORDER BY created_at"
        ).fetchall()
        return [
            DeviceTarget(
                device_id=r["device_id"],
                adb_serial=r["adb_serial"],
                name=r["name"] or "",
                created_at=_str_to_dt(r["created_at"]) or utc_now(),
            )
            for r in rows
        ]

    # ---- roles ----
    def list_roles(self) -> List[RoleContext]:
        self.ensure_ready()
        rows = connect().execute("SELECT * FROM roles ORDER BY role_id").fetchall()
        return [self._row_to_role(r) for r in rows]

    def get_role(self, role_id: str) -> Optional[RoleContext]:
        self.ensure_ready()
        row = connect().execute(
            "SELECT * FROM roles WHERE role_id=?", (role_id,)
        ).fetchone()
        return self._row_to_role(row) if row else None

    def _row_to_role(self, row) -> RoleContext:
        return RoleContext(
            role_id=row["role_id"],
            role_name=row["role_name"] or "",
            server_id=row["server_id"] or "",
            server_name=row["server_name"] or "",
            device_id=row["device_id"],
            session=_json_loads(row["session_json"]),
            params=_json_loads(row["params_json"]),
        )

    def upsert_role(self, role: RoleContext, *, ensure_task_defaults: bool = True) -> RoleContext:
        self.ensure_ready()
        # 不在 API 层落真实秘密以外的扩展字段；session 原样存但接口脱敏
        session = dict(role.session or {})
        conn = connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO roles(
                    role_id, role_name, server_id, server_name,
                    device_id, session_json, params_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                    role_name=excluded.role_name,
                    server_id=excluded.server_id,
                    server_name=excluded.server_name,
                    device_id=excluded.device_id,
                    session_json=excluded.session_json,
                    params_json=excluded.params_json
                """,
                (
                    role.role_id,
                    role.role_name,
                    role.server_id,
                    role.server_name,
                    role.device_id,
                    _json_dumps(session),
                    _json_dumps(role.params or {}),
                ),
            )
            if ensure_task_defaults:
                for key, meta in TASK_CATALOG.items():
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO role_task_configs(
                            role_id, task_key, enabled, interval_minutes, impl, params_json
                        ) VALUES (?, ?, 0, ?, 'auto', '{}')
                        """,
                        (role.role_id, key.value, meta.default_interval_minutes),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO role_task_states(
                            role_id, task_key, last_message, last_extras_json
                        ) VALUES (?, ?, '', '{}')
                        """,
                        (role.role_id, key.value),
                    )
        return role

    def bind_role_device(self, role_id: str, device_id: Optional[str]) -> RoleContext:
        role = self.get_role(role_id)
        if not role:
            raise KeyError(role_id)
        role.device_id = device_id
        return self.upsert_role(role, ensure_task_defaults=False)

    # ---- task config/state ----
    def list_task_configs(self, role_id: str) -> List[RoleTaskConfig]:
        self.ensure_ready()
        rows = connect().execute(
            "SELECT * FROM role_task_configs WHERE role_id=?", (role_id,)
        ).fetchall()
        return [self._row_to_cfg(r) for r in rows]

    def get_task_config(self, role_id: str, task_key: TaskKey) -> Optional[RoleTaskConfig]:
        self.ensure_ready()
        row = connect().execute(
            "SELECT * FROM role_task_configs WHERE role_id=? AND task_key=?",
            (role_id, task_key.value),
        ).fetchone()
        return self._row_to_cfg(row) if row else None

    def _row_to_cfg(self, row) -> RoleTaskConfig:
        return RoleTaskConfig(
            task_key=TaskKey(row["task_key"]),
            enabled=bool(row["enabled"]),
            interval_minutes=int(row["interval_minutes"] or 0),
            impl=TaskImpl(row["impl"] or "auto"),
            params=_json_loads(row["params_json"]),
        )

    def set_task_enabled(
        self, role_id: str, task_key: TaskKey, enabled: bool
    ) -> RoleTaskConfig:
        return self.patch_task_config(role_id, task_key, enabled=enabled)

    def patch_task_config(
        self, role_id: str, task_key: TaskKey, **kwargs
    ) -> RoleTaskConfig:
        self.ensure_ready()
        cfg = self.get_task_config(role_id, task_key)
        if not cfg:
            meta = TASK_CATALOG.get(task_key)
            cfg = RoleTaskConfig(
                task_key=task_key,
                enabled=False,
                interval_minutes=meta.default_interval_minutes if meta else 60,
                impl=TaskImpl.AUTO,
            )
        data = cfg.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                data[k] = v
        new_cfg = RoleTaskConfig.model_validate(data)
        conn = connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO role_task_configs(
                    role_id, task_key, enabled, interval_minutes, impl, params_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id, task_key) DO UPDATE SET
                    enabled=excluded.enabled,
                    interval_minutes=excluded.interval_minutes,
                    impl=excluded.impl,
                    params_json=excluded.params_json
                """,
                (
                    role_id,
                    new_cfg.task_key.value,
                    1 if new_cfg.enabled else 0,
                    int(new_cfg.interval_minutes),
                    new_cfg.impl.value,
                    _json_dumps(new_cfg.params or {}),
                ),
            )
        return new_cfg

    def get_task_state(self, role_id: str, task_key: TaskKey) -> Optional[RoleTaskState]:
        self.ensure_ready()
        row = connect().execute(
            "SELECT * FROM role_task_states WHERE role_id=? AND task_key=?",
            (role_id, task_key.value),
        ).fetchone()
        return self._row_to_state(row) if row else None

    def list_task_states(self, role_id: str) -> List[RoleTaskState]:
        self.ensure_ready()
        rows = connect().execute(
            "SELECT * FROM role_task_states WHERE role_id=?", (role_id,)
        ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def _row_to_state(self, row) -> RoleTaskState:
        last_status = row["last_status"]
        last_route = row["last_route"]
        last_job_status = row["last_job_status"]
        return RoleTaskState(
            task_key=TaskKey(row["task_key"]),
            last_run_at=_str_to_dt(row["last_run_at"]),
            last_status=TaskStatusCode(last_status) if last_status else None,
            last_message=row["last_message"] or "",
            last_route=ExecRoute(last_route) if last_route else None,
            last_job_id=row["last_job_id"],
            last_job_status=JobStatus(last_job_status) if last_job_status else None,
            last_extras=_json_loads(row["last_extras_json"]),
        )

    def _upsert_task_state(self, role_id: str, state: RoleTaskState) -> None:
        conn = connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO role_task_states(
                    role_id, task_key, last_run_at, last_status, last_message,
                    last_route, last_job_id, last_job_status, last_extras_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(role_id, task_key) DO UPDATE SET
                    last_run_at=excluded.last_run_at,
                    last_status=excluded.last_status,
                    last_message=excluded.last_message,
                    last_route=excluded.last_route,
                    last_job_id=excluded.last_job_id,
                    last_job_status=excluded.last_job_status,
                    last_extras_json=excluded.last_extras_json
                """,
                (
                    role_id,
                    state.task_key.value,
                    _dt_to_str(state.last_run_at),
                    state.last_status.value if state.last_status else None,
                    state.last_message or "",
                    state.last_route.value if state.last_route else None,
                    state.last_job_id,
                    state.last_job_status.value if state.last_job_status else None,
                    _json_dumps(redact_secrets(state.last_extras or {})),
                ),
            )

    # ---- jobs ----
    def create_job(self, job: Job) -> Job:
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, role_id, device_id, task_key, route, status, message,
                    result_code, extras_json, created_at, started_at, finished_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.role_id,
                    job.device_id,
                    job.task_key.value,
                    job.route.value,
                    job.status.value,
                    job.message or "",
                    job.result_code.value if job.result_code else None,
                    _json_dumps(redact_secrets(job.extras or {})),
                    _dt_to_str(job.created_at) or _dt_to_str(utc_now()),
                    _dt_to_str(job.started_at),
                    _dt_to_str(job.finished_at),
                    job.duration_ms,
                ),
            )
        return job

    def update_job(self, job: Job) -> Job:
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute(
                """
                UPDATE jobs SET
                    device_id=?, status=?, message=?, result_code=?, extras_json=?,
                    started_at=?, finished_at=?, duration_ms=?
                WHERE job_id=?
                """,
                (
                    job.device_id,
                    job.status.value,
                    job.message or "",
                    job.result_code.value if job.result_code else None,
                    _json_dumps(redact_secrets(job.extras or {})),
                    _dt_to_str(job.started_at),
                    _dt_to_str(job.finished_at),
                    job.duration_ms,
                    job.job_id,
                ),
            )
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        self.ensure_ready()
        row = connect().execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def _row_to_job(self, row) -> Job:
        return Job(
            job_id=row["job_id"],
            role_id=row["role_id"],
            device_id=row["device_id"],
            task_key=TaskKey(row["task_key"]),
            route=ExecRoute(row["route"]),
            status=JobStatus(row["status"]),
            message=row["message"] or "",
            result_code=TaskStatusCode(row["result_code"]) if row["result_code"] else None,
            extras=_json_loads(row["extras_json"]),
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
            started_at=_str_to_dt(row["started_at"]),
            finished_at=_str_to_dt(row["finished_at"]),
            duration_ms=row["duration_ms"],
        )

    def list_jobs(
        self,
        *,
        role_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> List[Job]:
        self.ensure_ready()
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: List[Any] = []
        if role_id:
            sql += " AND role_id=?"
            params.append(role_id)
        if status:
            sql += " AND status=?"
            params.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = connect().execute(sql, params).fetchall()
        return [self._row_to_job(r) for r in rows]

    def find_active_vision_job(self, device_id: str) -> Optional[Job]:
        """查找该设备上最早的 queued/running vision job（FIFO 参考）。"""
        self.ensure_ready()
        row = connect().execute(
            """
            SELECT * FROM jobs
            WHERE device_id=? AND route='vision'
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC, job_id ASC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def find_running_vision_job(self, device_id: str) -> Optional[Job]:
        self.ensure_ready()
        if not device_id:
            return None
        row = connect().execute(
            """
            SELECT * FROM jobs
            WHERE device_id=? AND route='vision' AND status='running'
            ORDER BY started_at ASC, job_id ASC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def find_active_job_for_task(
        self, role_id: str, task_key: TaskKey
    ) -> Optional[Job]:
        self.ensure_ready()
        row = connect().execute(
            """
            SELECT * FROM jobs
            WHERE role_id=? AND task_key=?
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC, job_id ASC
            LIMIT 1
            """,
            (role_id, task_key.value),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list_device_vision_queue(self, device_id: str) -> List[Job]:
        """设备上所有 active vision Job，FIFO 顺序。"""
        self.ensure_ready()
        rows = connect().execute(
            """
            SELECT * FROM jobs
            WHERE device_id=? AND route='vision'
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC, job_id ASC
            """,
            (device_id,),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def vision_queue_position(self, job_id: str) -> Optional[int]:
        """running → 0；queued → 在等待序列中的 1-based 位置；其它 → None。"""
        job = self.get_job(job_id)
        if not job or job.route != ExecRoute.VISION or not job.device_id:
            if job and job.status == JobStatus.RUNNING:
                return 0
            if job and job.status == JobStatus.QUEUED:
                return None
            return None
        if job.status == JobStatus.RUNNING:
            return 0
        if job.status != JobStatus.QUEUED:
            return None
        queue = self.list_device_vision_queue(job.device_id)
        waiting = [j for j in queue if j.status == JobStatus.QUEUED]
        for i, j in enumerate(waiting, start=1):
            if j.job_id == job_id:
                return i
        return None

    def create_or_reuse_active_job(self, draft: Job) -> tuple:
        """原子：同 role+task 已有 queued/running 则复用，否则插入新 Job。

        返回 (job, created: bool)。绝不复用其它 task_key 的 Job。
        """
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE role_id=? AND task_key=?
                      AND status IN ('queued', 'running')
                    ORDER BY created_at ASC, job_id ASC
                    LIMIT 1
                    """,
                    (draft.role_id, draft.task_key.value),
                ).fetchone()
                if row:
                    conn.execute("COMMIT")
                    return self._row_to_job(row), False

                conn.execute(
                    """
                    INSERT INTO jobs(
                        job_id, role_id, device_id, task_key, route, status, message,
                        result_code, extras_json, created_at, started_at, finished_at, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft.job_id,
                        draft.role_id,
                        draft.device_id,
                        draft.task_key.value,
                        draft.route.value,
                        JobStatus.QUEUED.value,
                        draft.message or "已入队",
                        None,
                        _json_dumps(redact_secrets(draft.extras or {})),
                        _dt_to_str(draft.created_at) or _dt_to_str(utc_now()),
                        None,
                        None,
                        None,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        job = self.get_job(draft.job_id)
        assert job is not None
        return job, True

    def try_claim_job(self, job_id: str) -> Optional[Job]:
        """原子：若 job 为 queued 且（Vision 时设备无 running）则置 running。"""
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (job_id,)
                ).fetchone()
                if not row or row["status"] != JobStatus.QUEUED.value:
                    conn.execute("COMMIT")
                    return None

                if row["route"] == ExecRoute.VISION.value:
                    device_id = row["device_id"]
                    if not device_id:
                        conn.execute("COMMIT")
                        return None
                    busy = conn.execute(
                        """
                        SELECT job_id FROM jobs
                        WHERE device_id=? AND route='vision' AND status='running'
                        LIMIT 1
                        """,
                        (device_id,),
                    ).fetchone()
                    if busy:
                        conn.execute("COMMIT")
                        return None

                now = _dt_to_str(utc_now())
                conn.execute(
                    """
                    UPDATE jobs SET status='running', started_at=?, message='执行中'
                    WHERE job_id=? AND status='queued'
                    """,
                    (now, job_id),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    conn.execute("COMMIT")
                    return None
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_job(job_id)

    def claim_next_vision_job(self, device_id: str) -> Optional[Job]:
        """原子：设备无 running 时领取最早 queued Vision Job → running。"""
        self.ensure_ready()
        if not device_id:
            return None
        conn = connect()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                busy = conn.execute(
                    """
                    SELECT job_id FROM jobs
                    WHERE device_id=? AND route='vision' AND status='running'
                    LIMIT 1
                    """,
                    (device_id,),
                ).fetchone()
                if busy:
                    conn.execute("COMMIT")
                    return None

                row = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE device_id=? AND route='vision' AND status='queued'
                    ORDER BY created_at ASC, job_id ASC
                    LIMIT 1
                    """,
                    (device_id,),
                ).fetchone()
                if not row:
                    conn.execute("COMMIT")
                    return None

                job_id = row["job_id"]
                now = _dt_to_str(utc_now())
                conn.execute(
                    """
                    UPDATE jobs SET status='running', started_at=?, message='执行中'
                    WHERE job_id=? AND status='queued'
                    """,
                    (now, job_id),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    conn.execute("COMMIT")
                    return None
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_job(job_id)

    def requeue_job(self, job_id: str, message: str = "重新排队") -> Optional[Job]:
        """running → queued（仅异常恢复用，不伪造终态）。"""
        self.ensure_ready()
        conn = connect()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    UPDATE jobs SET status='queued', started_at=NULL, message=?
                    WHERE job_id=? AND status='running'
                    """,
                    (message, job_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        job = self.get_job(job_id)
        if job:
            self.add_job_event(job_id, message, level="warn")
        return job

    def count_running_vision(self, device_id: str) -> int:
        self.ensure_ready()
        row = connect().execute(
            """
            SELECT COUNT(*) AS c FROM jobs
            WHERE device_id=? AND route='vision' AND status='running'
            """,
            (device_id,),
        ).fetchone()
        return int(row["c"] if row else 0)

    def add_job_event(
        self,
        job_id: str,
        message: str,
        *,
        level: str = "info",
        screenshot_path: Optional[str] = None,
        ts: Optional[datetime] = None,
    ) -> JobEvent:
        self.ensure_ready()
        event = JobEvent(
            job_id=job_id,
            ts=ts or utc_now(),
            level=level,
            message=message,
            screenshot_path=screenshot_path,
        )
        conn = connect()
        with self._lock:
            cur = conn.execute(
                """
                INSERT INTO job_events(job_id, ts, level, message, screenshot_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.job_id,
                    _dt_to_str(event.ts),
                    event.level,
                    event.message,
                    event.screenshot_path,
                ),
            )
            event.id = int(cur.lastrowid)
        return event

    def list_job_events(self, job_id: str, limit: int = 200) -> List[JobEvent]:
        self.ensure_ready()
        rows = connect().execute(
            """
            SELECT * FROM job_events WHERE job_id=?
            ORDER BY id ASC LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()
        return [
            JobEvent(
                id=r["id"],
                job_id=r["job_id"],
                ts=_str_to_dt(r["ts"]) or utc_now(),
                level=r["level"] or "info",
                message=r["message"] or "",
                screenshot_path=r["screenshot_path"],
            )
            for r in rows
        ]

    def apply_job_to_task_state(self, job: Job) -> None:
        """把 Job 终态/运行态写回最近任务状态。"""
        st = self.get_task_state(job.role_id, job.task_key) or RoleTaskState(
            task_key=job.task_key
        )
        st.last_job_id = job.job_id
        st.last_job_status = job.status
        st.last_message = job.message or ""
        st.last_route = job.route
        if job.status in JobStatus.terminal() or job.status == JobStatus.RUNNING:
            st.last_run_at = job.finished_at or job.started_at or utc_now()
        if job.result_code:
            st.last_status = job.result_code
        elif job.status == JobStatus.SUCCEEDED:
            st.last_status = TaskStatusCode.OK
        elif job.status == JobStatus.BLOCKED:
            st.last_status = TaskStatusCode.BLOCKED
        elif job.status == JobStatus.FAILED:
            st.last_status = TaskStatusCode.TEMP_FAIL
        st.last_extras = redact_secrets(dict(job.extras or {}))
        self._upsert_task_state(job.role_id, st)

    def apply_result(self, role_id: str, result: TaskResult) -> None:
        """兼容旧接口：无 Job 时仅更新 task state + 伪日志。"""
        if not result.task_key:
            return
        st = self.get_task_state(role_id, result.task_key) or RoleTaskState(
            task_key=result.task_key
        )
        st.last_run_at = result.finished_at or utc_now()
        st.last_status = result.code
        st.last_message = result.message
        st.last_route = result.route
        st.last_extras = redact_secrets(dict(result.extras or {}))
        self._upsert_task_state(role_id, st)

    def list_logs(self, role_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        """以 Job 列表作为执行日志（新在前）。"""
        jobs = self.list_jobs(role_id=role_id, limit=limit)
        out = []
        for j in jobs:
            out.append(
                {
                    "ts": _dt_to_str(j.finished_at or j.started_at or j.created_at),
                    "role_id": j.role_id,
                    "task_key": j.task_key.value,
                    "job_id": j.job_id,
                    "ok": j.status == JobStatus.SUCCEEDED,
                    "code": j.result_code.value if j.result_code else j.status.value,
                    "status": j.status.value,
                    "message": j.message,
                    "route": j.route.value,
                    "duration_ms": j.duration_ms,
                    "device_id": j.device_id,
                    "extras": redact_secrets(j.extras or {}),
                }
            )
        return out

    def mark_interrupted_jobs(self) -> int:
        """启动时把残留 queued/running 标为 failed。"""
        self.ensure_ready()
        conn = connect()
        now = _dt_to_str(utc_now())
        with self._lock:
            cur = conn.execute(
                """
                UPDATE jobs SET
                    status='failed',
                    message=CASE
                        WHEN message IS NULL OR message='' THEN '进程重启，任务中断'
                        ELSE message || '（进程重启中断）'
                    END,
                    result_code='TEMP_FAIL',
                    finished_at=?,
                    duration_ms=COALESCE(duration_ms, 0)
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )
            n = cur.rowcount or 0
        if n:
            log.warning("已将 %d 个未完成 Job 标记为 failed（进程重启）", n)
        return n

    def reset_for_tests(self) -> None:
        """测试用：关闭连接并清空 ready 标记。"""
        with self._lock:
            close_thread_connection()
            self._ready = False


# 进程内单例
store = SQLiteStore()
