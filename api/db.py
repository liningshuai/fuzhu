# -*- coding: utf-8 -*-
"""SQLite 连接与 schema。数据库文件位于项目 data/ 目录。"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import local
from typing import Optional

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    adb_serial  TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    role_id     TEXT PRIMARY KEY,
    role_name   TEXT NOT NULL DEFAULT '',
    server_id   TEXT NOT NULL DEFAULT '',
    server_name TEXT NOT NULL DEFAULT '',
    device_id   TEXT REFERENCES devices(device_id),
    session_json TEXT NOT NULL DEFAULT '{}',
    params_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS role_task_configs (
    role_id           TEXT NOT NULL,
    task_key          TEXT NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 0,
    interval_minutes  INTEGER NOT NULL DEFAULT 60,
    impl              TEXT NOT NULL DEFAULT 'auto',
    params_json       TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (role_id, task_key),
    FOREIGN KEY (role_id) REFERENCES roles(role_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS role_task_states (
    role_id          TEXT NOT NULL,
    task_key         TEXT NOT NULL,
    last_run_at      TEXT,
    last_status      TEXT,
    last_message     TEXT NOT NULL DEFAULT '',
    last_route       TEXT,
    last_job_id      TEXT,
    last_job_status  TEXT,
    last_extras_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (role_id, task_key),
    FOREIGN KEY (role_id) REFERENCES roles(role_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    role_id      TEXT NOT NULL,
    device_id    TEXT,
    task_key     TEXT NOT NULL,
    route        TEXT NOT NULL,
    status       TEXT NOT NULL,
    message      TEXT NOT NULL DEFAULT '',
    result_code  TEXT,
    extras_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    duration_ms  INTEGER,
    FOREIGN KEY (role_id) REFERENCES roles(role_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(role_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_device_status ON jobs(device_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL,
    ts               TEXT NOT NULL,
    level            TEXT NOT NULL DEFAULT 'info',
    message          TEXT NOT NULL,
    screenshot_path  TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);
"""

_thread_local = local()
_db_path: Optional[Path] = None


def configure_db(path: str | Path) -> Path:
    """设置数据库路径并确保父目录存在。"""
    global _db_path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _db_path = p
    # 重置连接
    if hasattr(_thread_local, "conn"):
        try:
            _thread_local.conn.close()
        except Exception:  # noqa: BLE001
            pass
        del _thread_local.conn
    return p


def get_db_path() -> Path:
    if _db_path is None:
        from api.settings import settings

        configure_db(settings.db_path)
    assert _db_path is not None
    return _db_path


def connect() -> sqlite3.Connection:
    path = get_db_path()
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit BEGIN
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _thread_local.conn = conn
    return conn


def init_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    c = conn or connect()
    c.executescript(SCHEMA)


def close_thread_connection() -> None:
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        del _thread_local.conn
