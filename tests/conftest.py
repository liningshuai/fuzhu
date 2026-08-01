# -*- coding: utf-8 -*-
"""pytest fixtures：隔离 SQLite，禁用调度，注入 fake vision。"""
from __future__ import annotations

import os
import time
import warnings
from pathlib import Path

import pytest

# 压制 Starlette TestClient + httpx 的兼容提示（业务无关；不引入未知 httpx2）
warnings.filterwarnings(
    "ignore",
    message=r".*httpx.*starlette\.testclient.*",
)
warnings.filterwarnings(
    "ignore",
    message=r".*Using `httpx` with `starlette\.testclient`.*",
)

# 必须在 import app 之前设置环境
@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test_fuzhu.db"
    monkeypatch.setenv("FUZHU_DB_PATH", str(db))
    monkeypatch.setenv("FUZHU_DISABLE_SCHEDULER", "1")
    monkeypatch.setenv("FUZHU_ALLOW_LAN", "false")
    # 重置 settings 与 store 模块状态
    import api.settings as settings_mod
    import api.db as db_mod
    import api.store as store_mod
    import api.device_lock as lock_mod
    import api.executor as exec_mod
    import vision_worker.runner as vision_mod

    settings_mod.settings = settings_mod.load_settings()
    db_mod.configure_db(settings_mod.settings.db_path)
    store_mod.store.reset_for_tests()
    lock_mod.device_locks.clear()
    exec_mod.set_task_runner(None)
    vision_mod.set_vision_impl(None)

    yield db

    exec_mod.set_task_runner(None)
    vision_mod.set_vision_impl(None)
    lock_mod.device_locks.clear()
    store_mod.store.reset_for_tests()


@pytest.fixture()
def client(tmp_db):
    from fastapi.testclient import TestClient
    from api.app import app

    with TestClient(app) as c:
        yield c


def wait_job_terminal(client, job_id: str, timeout: float = 5.0):
    """轮询直到 Job 终态。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        last = r.json()
        st = last["job"]["status"]
        if st in ("succeeded", "failed", "cancelled", "blocked"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} not terminal: {last}")
