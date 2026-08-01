# -*- coding: utf-8 -*-
"""本机绑定、allow_lan 口令、session 字段安全。"""
from __future__ import annotations

import json

import pytest


def test_default_host_is_loopback(tmp_path, monkeypatch):
    monkeypatch.delenv("FUZHU_ALLOW_LAN", raising=False)
    monkeypatch.delenv("FUZHU_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "x.db"))
    import api.settings as s

    cfg = s.load_settings()
    assert cfg.host == "127.0.0.1"
    assert cfg.allow_lan is False


def test_allow_lan_requires_admin_token(tmp_path, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("FUZHU_ALLOW_LAN", "true")
    monkeypatch.setenv("FUZHU_ADMIN_TOKEN", "")
    import api.settings as s

    with pytest.raises(RuntimeError, match="admin_token"):
        s.load_settings()


def test_allow_lan_with_token_binds_all(tmp_path, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("FUZHU_ALLOW_LAN", "true")
    monkeypatch.setenv("FUZHU_ADMIN_TOKEN", "secret-admin")
    import api.settings as s

    cfg = s.load_settings()
    assert cfg.allow_lan is True
    assert cfg.host == "0.0.0.0"
    assert cfg.admin_token == "secret-admin"


def _lan_client(tmp_path, monkeypatch, token: str = "lan-pass"):
    """构建 allow_lan=true 的 TestClient（不连 ADB/外网）。"""
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "lan.db"))
    monkeypatch.setenv("FUZHU_ALLOW_LAN", "true")
    monkeypatch.setenv("FUZHU_ADMIN_TOKEN", token)
    monkeypatch.setenv("FUZHU_DISABLE_SCHEDULER", "1")

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

    from fastapi.testclient import TestClient
    from api.app import app

    return TestClient(app)


def test_lan_api_requires_header(tmp_path, monkeypatch):
    """A/D：无头 401；正确 X-Admin-Token 200；health 匿名可访问。"""
    with _lan_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/health").status_code == 200
        # A：未提供 X-Admin-Token
        denied = client.get("/api/roles")
        assert denied.status_code == 401
        detail = denied.json().get("detail", "")
        assert "lan-pass" not in str(detail)
        # D：Header 正确
        ok = client.get("/api/roles", headers={"X-Admin-Token": "lan-pass"})
        assert ok.status_code == 200


def test_lan_query_admin_token_rejected(tmp_path, monkeypatch):
    """B/C/E：query 中的 admin_token 必须被完全忽略，鉴权只看 Header。"""
    with _lan_client(tmp_path, monkeypatch) as client:
        # B：仅 URL 提供正确 token，无 Header → 401
        only_query = client.get("/api/roles?admin_token=lan-pass")
        assert only_query.status_code == 401
        assert "lan-pass" not in str(only_query.json().get("detail", ""))

        # C：Header 错误 + URL 正确 token → 401
        wrong_header = client.get(
            "/api/roles?admin_token=lan-pass",
            headers={"X-Admin-Token": "wrong-pass"},
        )
        assert wrong_header.status_code == 401
        body = str(wrong_header.json().get("detail", ""))
        assert "wrong-pass" not in body
        assert "lan-pass" not in body

        # E：Header 正确 + URL 错误 token → 200（query 忽略）
        ok = client.get(
            "/api/roles?admin_token=wrong-pass",
            headers={"X-Admin-Token": "lan-pass"},
        )
        assert ok.status_code == 200


def test_no_token_cookie_password_in_api(client):
    roles = client.get("/api/roles").json()
    blob = json.dumps(roles, ensure_ascii=False).lower()
    for bad in ("token", "cookie", "password", "authorization", "mock_token"):
        assert bad not in blob
    # mock_session 允许
    assert any(
        (r.get("session") or {}).get("mock_session") is True
        or (r.get("session") or {}) == {}
        for r in roles
    ) or roles


def test_restart_marks_queued_running_failed(tmp_db, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_db))
    monkeypatch.setenv("FUZHU_DISABLE_SCHEDULER", "1")

    import api.settings as settings_mod
    import api.db as db_mod
    import api.store as store_mod
    from api.seed import seed_demo_data
    from common.models import ExecRoute, Job, JobStatus, TaskKey, utc_now

    settings_mod.settings = settings_mod.load_settings()
    db_mod.configure_db(str(tmp_db))
    store_mod.store.reset_for_tests()
    store_mod.store.initialize()
    seed_demo_data(store_mod.store)
    role = store_mod.store.list_roles()[0]

    q = Job(
        role_id=role.role_id,
        device_id=role.device_id,
        task_key=TaskKey.MAIL,
        route=ExecRoute.VISION,
        status=JobStatus.QUEUED,
        message="was-queued",
    )
    r = Job(
        role_id=role.role_id,
        device_id=role.device_id,
        task_key=TaskKey.ZHENGWU,
        route=ExecRoute.VISION,
        status=JobStatus.RUNNING,
        message="was-running",
        started_at=utc_now(),
    )
    store_mod.store.create_job(q)
    store_mod.store.create_job(r)

    n = store_mod.store.mark_interrupted_jobs()
    assert n >= 2
    assert store_mod.store.get_job(q.job_id).status == JobStatus.FAILED
    assert store_mod.store.get_job(r.job_id).status == JobStatus.FAILED
    # 不可伪造成功
    assert store_mod.store.get_job(q.job_id).status != JobStatus.SUCCEEDED
