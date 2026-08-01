# -*- coding: utf-8 -*-
"""Phase 1.5：Job 诊断字段、失败分类、队列位置、详情鉴权。"""
from __future__ import annotations

import time

from common.models import (
    ExecRoute,
    FailureCode,
    JobStatus,
    TaskKey,
    TaskResult,
    TaskStatusCode,
)
from tests.conftest import wait_job_terminal


def test_diagnostic_fields_success(client):
    role_id = client.get("/api/roles").json()[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    )
    job = r.json()["job"]
    assert job["status"] == "succeeded"
    assert job["created_at"]
    assert job["started_at"]
    assert job["finished_at"]
    assert job["duration_ms"] is not None
    assert job["failure_code"] is None
    assert job.get("user_message")
    assert "tech_summary" not in job
    assert "traceback" not in str(job).lower()


def test_device_not_bound_blocked(client):
    client.post(
        "/api/roles",
        json={"role_id": "diag-nobind", "role_name": "x", "mock_session": True},
    )
    client.patch("/api/roles/diag-nobind/device", json={"device_id": None})
    r = client.post(
        "/api/roles/diag-nobind/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    )
    job = r.json()["job"]
    assert job["status"] == "blocked"
    assert job["failure_code"] == FailureCode.DEVICE_NOT_BOUND.value
    assert job["retryable"] is False
    um = job["user_message"]
    assert "绑定" in um
    low = um.lower()
    for bad in ("password", "token", "cookie", "traceback", "c:\\", "/home/"):
        assert bad not in low


def test_failure_code_mappings_via_runner(client):
    import api.executor as exec_mod

    role_id = client.get("/api/roles").json()[0]["role_id"]
    cases = [
        (
            "pre",
            "超时未等到 mail/title.png",
            TaskStatusCode.TEMP_FAIL,
            FailureCode.PRECONDITION_NOT_MET,
            "failed",
        ),
        (
            "tgt",
            "超时未找到模板 mail/claim_all.png",
            TaskStatusCode.BLOCKED,
            FailureCode.TARGET_NOT_FOUND,
            "blocked",
        ),
        (
            "post",
            "超时后 mail/claim_all.png 仍未消失（后置验证失败）",
            TaskStatusCode.TEMP_FAIL,
            FailureCode.POSTCONDITION_NOT_MET,
            "failed",
        ),
        (
            "exe",
            "执行异常: RuntimeError",
            TaskStatusCode.TEMP_FAIL,
            FailureCode.EXECUTION_ERROR,
            "failed",
        ),
    ]
    for key, msg, code, fc, st in cases:
        def runner(task_key, role, cfg=None, force_route=None, _msg=msg, _code=code):
            return TaskResult.fail(
                _code,
                _msg,
                task_key=task_key,
                route=ExecRoute.VISION,
                events=[_msg],
            )

        exec_mod.set_task_runner(runner)
        # unique task reuse: wait previous finish
        r = client.post(
            f"/api/roles/{role_id}/tasks/mail/run",
            json={"force_route": "vision", "wait": True},
        )
        job = r.json()["job"]
        assert job["status"] == st, (key, job)
        assert job["failure_code"] == fc.value, (key, job)
        assert job["retryable"] is True
        assert job["user_message"]
        assert "Traceback" not in job["user_message"]
    exec_mod.set_task_runner(None)


def test_recovered_after_restart(tmp_db, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_db))
    monkeypatch.setenv("FUZHU_DISABLE_SCHEDULER", "1")
    import api.settings as settings_mod
    import api.db as db_mod
    import api.store as store_mod
    from api.seed import seed_demo_data
    from common.models import Job, ExecRoute, JobStatus, TaskKey, utc_now

    settings_mod.settings = settings_mod.load_settings()
    db_mod.configure_db(str(tmp_db))
    store_mod.store.reset_for_tests()
    store_mod.store.initialize()
    seed_demo_data(store_mod.store)
    role = store_mod.store.list_roles()[0]
    j = Job(
        role_id=role.role_id,
        device_id=role.device_id,
        task_key=TaskKey.MAIL,
        route=ExecRoute.VISION,
        status=JobStatus.RUNNING,
        message="was-running",
        started_at=utc_now(),
    )
    store_mod.store.create_job(j)
    n = store_mod.store.mark_interrupted_jobs()
    assert n >= 1
    got = store_mod.store.get_job(j.job_id)
    assert got.status == JobStatus.FAILED
    assert got.failure_code == FailureCode.RECOVERED_AFTER_RESTART
    assert got.retryable is True
    assert "重启" in (got.user_message or "")


def test_queue_position_fifo(client):
    import api.executor as exec_mod

    gate = {"open": False}
    order = []

    def slow(task_key, role, cfg=None, force_route=None):
        order.append(task_key.value)
        deadline = time.time() + 8
        while not gate["open"] and time.time() < deadline:
            time.sleep(0.02)
        return TaskResult.success(
            "ok",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=["ok"],
        )

    exec_mod.set_task_runner(slow)
    role_id = client.get("/api/roles").json()[0]["role_id"]
    client.patch(
        f"/api/roles/{role_id}/tasks/mail",
        json={"enabled": True, "impl": "vision"},
    )
    client.patch(
        f"/api/roles/{role_id}/tasks/zhengwu",
        json={"enabled": True, "impl": "vision"},
    )
    body = client.post(f"/api/roles/{role_id}/run-enabled").json()
    assert body["count"] == 2
    jobs = body["jobs"]
    time.sleep(0.1)
    # refresh
    details = [client.get(f"/api/jobs/{j['job_id']}").json()["job"] for j in jobs]
    running = [j for j in details if j["status"] == "running"]
    queued = [j for j in details if j["status"] == "queued"]
    assert len(running) == 1
    assert len(queued) == 1
    assert running[0]["queue_position"] == 0
    assert queued[0]["queue_position"] == 1
    assert queued[0].get("failure_code") in (
        None,
        FailureCode.DEVICE_BUSY_OR_QUEUED.value,
    )
    assert queued[0]["status"] != "failed"
    gate["open"] = True
    for j in details:
        wait_job_terminal(client, j["job_id"], timeout=6)
    exec_mod.set_task_runner(None)


def test_job_detail_200_404(client):
    role_id = client.get("/api/roles").json()[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    )
    jid = r.json()["job"]["job_id"]
    d = client.get(f"/api/jobs/{jid}")
    assert d.status_code == 200
    assert d.json()["job"]["job_id"] == jid
    assert "events" in d.json()
    assert client.get("/api/jobs/does-not-exist-job").status_code == 404


def test_job_detail_lan_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "lan_diag.db"))
    monkeypatch.setenv("FUZHU_ALLOW_LAN", "true")
    monkeypatch.setenv("FUZHU_ADMIN_TOKEN", "lan-pass")
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

    with TestClient(app) as client:
        # create a job with header
        roles = client.get("/api/roles", headers={"X-Admin-Token": "lan-pass"}).json()
        rid = roles[0]["role_id"]
        jr = client.post(
            f"/api/roles/{rid}/tasks/mail/run",
            headers={"X-Admin-Token": "lan-pass"},
            json={"force_route": "protocol", "wait": True},
        )
        jid = jr.json()["job"]["job_id"]
        assert client.get(f"/api/jobs/{jid}").status_code == 401
        assert (
            client.get(f"/api/jobs/{jid}?admin_token=lan-pass").status_code == 401
        )
        assert (
            client.get(
                f"/api/jobs/{jid}", headers={"X-Admin-Token": "wrong"}
            ).status_code
            == 401
        )
        ok = client.get(f"/api/jobs/{jid}", headers={"X-Admin-Token": "lan-pass"})
        assert ok.status_code == 200
        blob = str(ok.json()).lower()
        for bad in ("password", "cookie", "traceback", "authorization"):
            assert bad not in blob


def test_api_and_web_static_no_sensitive_leaks(client):
    from pathlib import Path

    role_id = client.get("/api/roles").json()[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    )
    job = r.json()["job"]
    blob = str(job).lower()
    for bad in ("password", "cookie", "traceback", "adb_command"):
        assert bad not in blob
    assert "tech_summary" not in job
    js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "adminToken" in js  # memory only
    assert "localStorage" not in js
    assert "state.adminToken" not in js or "textContent = state.adminToken" not in js
    assert "innerHTML = state.adminToken" not in js


def test_schema_migration_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_path / "mig.db"))
    import api.db as db_mod
    import api.store as store_mod

    db_mod.configure_db(str(tmp_path / "mig.db"))
    store_mod.store.reset_for_tests()
    store_mod.store.initialize()
    # second init / migrate
    db_mod.migrate_jobs_diagnostics()
    db_mod.migrate_jobs_diagnostics()
    conn = db_mod.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for c in ("failure_code", "user_message", "retryable", "tech_summary"):
        assert c in cols


_SENTINELS = (
    "EVENT_SECRET_SENTINEL",
    "EVENT_COOKIE_SENTINEL",
    "EVENT_PASSWORD_SENTINEL",
    "EVENT_AUTH_SENTINEL",
    "EVENT_DEVICE_SENTINEL",
    r"C:\SENTINEL\private.png",
    "private.png",
)


def _assert_no_sentinels(blob: str) -> None:
    low = blob.lower()
    for s in _SENTINELS:
        assert s.lower() not in low, f"leaked {s}"
    for bad in (
        "traceback",
        "token=",
        "cookie=",
        "password=",
        "authorization",
        "adb -s",
        "c:\\sentinel",
        "screenshot_path",
    ):
        assert bad not in low, f"leaked keyword {bad}"


def test_job_detail_events_filter_historical_sensitive(client):
    """历史 JobEvent 即使库内有原文，API 也不得泄露。"""
    from api.store import store
    from api.db import connect
    from common.models import Job, ExecRoute, JobStatus, TaskKey, utc_now

    role_id = client.get("/api/roles").json()[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    )
    jid = r.json()["job"]["job_id"]

    poison = (
        "Traceback (most recent call last):\n"
        "token=EVENT_SECRET_SENTINEL\n"
        "cookie=EVENT_COOKIE_SENTINEL\n"
        "password=EVENT_PASSWORD_SENTINEL\n"
        "Authorization: EVENT_AUTH_SENTINEL\n"
        "C:\\SENTINEL\\private.png\n"
        "adb -s EVENT_DEVICE_SENTINEL shell\n"
    )
    # 绕过 add_job_event 安全写：模拟旧库脏数据
    conn = connect()
    conn.execute(
        """
        INSERT INTO job_events(job_id, ts, level, message, screenshot_path)
        VALUES (?, ?, 'error', ?, ?)
        """,
        (jid, utc_now().isoformat(), poison, r"C:\SENTINEL\private.png"),
    )

    detail = client.get(f"/api/jobs/{jid}").json()
    blob = str(detail)
    _assert_no_sentinels(blob)
    for ev in detail["events"]:
        assert set(ev.keys()) <= {"id", "job_id", "ts", "level", "message"}
        assert "screenshot_path" not in ev
        _assert_no_sentinels(str(ev))


def test_job_logs_run_response_filter_sentinels(client):
    import api.executor as exec_mod

    poison = (
        "Traceback ... token=EVENT_SECRET_SENTINEL cookie=EVENT_COOKIE_SENTINEL "
        "password=EVENT_PASSWORD_SENTINEL Authorization: EVENT_AUTH_SENTINEL "
        "C:\\SENTINEL\\private.png adb -s EVENT_DEVICE_SENTINEL"
    )

    def bad_runner(task_key, role, cfg=None, force_route=None):
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            poison,
            task_key=task_key,
            route=ExecRoute.VISION,
            events=[poison, "token=EVENT_SECRET_SENTINEL"],
            extras={
                "token": "EVENT_SECRET_SENTINEL",
                "cookie": "EVENT_COOKIE_SENTINEL",
                "screenshot_paths": [r"C:\SENTINEL\private.png"],
            },
        )

    exec_mod.set_task_runner(bad_runner)
    role_id = client.get("/api/roles").json()[0]["role_id"]
    run = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    )
    body = run.json()
    _assert_no_sentinels(str(body))
    job = body["job"]
    assert job["status"] in ("failed", "blocked")
    assert "tech_summary" not in job
    jid = job["job_id"]

    for path in (
        f"/api/jobs/{jid}",
        "/api/jobs",
        f"/api/roles/{role_id}/logs",
        "/api/logs",
    ):
        resp = client.get(path)
        assert resp.status_code == 200
        _assert_no_sentinels(str(resp.json()))

    tasks = client.get(f"/api/roles/{role_id}/tasks").json()
    _assert_no_sentinels(str(tasks))
    exec_mod.set_task_runner(None)


def test_sqlite_write_path_no_sentinels(client):
    """含 sentinel 的失败结果不得写入 SQLite 原文。"""
    import api.executor as exec_mod
    from api.db import connect

    poison = (
        "token=EVENT_SECRET_SENTINEL cookie=EVENT_COOKIE_SENTINEL "
        "password=EVENT_PASSWORD_SENTINEL Authorization: EVENT_AUTH_SENTINEL "
        "C:\\SENTINEL\\private.png adb -s EVENT_DEVICE_SENTINEL Traceback"
    )

    def bad_runner(task_key, role, cfg=None, force_route=None):
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            poison,
            task_key=task_key,
            route=ExecRoute.VISION,
            events=[poison],
            screenshot_paths=[r"C:\SENTINEL\private.png"],
            extras={"token": "EVENT_SECRET_SENTINEL"},
        )

    exec_mod.set_task_runner(bad_runner)
    role_id = client.get("/api/roles").json()[0]["role_id"]
    jid = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    ).json()["job"]["job_id"]

    conn = connect()
    row = conn.execute(
        "SELECT message, user_message, tech_summary FROM jobs WHERE job_id=?",
        (jid,),
    ).fetchone()
    for col in (row["message"], row["user_message"], row["tech_summary"] or ""):
        _assert_no_sentinels(col)
        assert "Traceback" not in col
    evs = conn.execute(
        "SELECT message, screenshot_path FROM job_events WHERE job_id=?",
        (jid,),
    ).fetchall()
    assert evs
    for e in evs:
        _assert_no_sentinels(e["message"] or "")
        assert e["screenshot_path"] in (None, "")
    exec_mod.set_task_runner(None)


def test_add_job_event_write_filter_and_api(client):
    """add_job_event 写入即过滤；API 再过滤。"""
    from api.store import store

    role_id = client.get("/api/roles").json()[0]["role_id"]
    jid = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    ).json()["job"]["job_id"]
    store.add_job_event(
        jid,
        "token=EVENT_SECRET_SENTINEL Traceback password=EVENT_PASSWORD_SENTINEL",
        level="error",
        screenshot_path=r"C:\SENTINEL\private.png",
    )
    from api.db import connect

    row = connect().execute(
        "SELECT message, screenshot_path FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 1",
        (jid,),
    ).fetchone()
    _assert_no_sentinels(row["message"])
    assert row["screenshot_path"] in (None, "")
    detail = client.get(f"/api/jobs/{jid}").json()
    _assert_no_sentinels(str(detail))
    for ev in detail["events"]:
        assert "screenshot_path" not in ev


def test_historical_extras_json_not_leaked_via_api(client):
    """历史 extras_json 含普通字段名+敏感值时，API 不得返回。"""
    from api.db import connect

    role_id = client.get("/api/roles").json()[0]["role_id"]
    jid = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    ).json()["job"]["job_id"]

    dirty = (
        '{"detail":"token=EXTRA_SECRET_SENTINEL",'
        '"debug":"Traceback C:\\\\SENTINEL\\\\private.png",'
        '"channel":"cookie=EXTRA_COOKIE_SENTINEL",'
        '"normal":"adb -s EXTRA_DEVICE_SENTINEL"}'
    )
    connect().execute(
        "UPDATE jobs SET extras_json=? WHERE job_id=?",
        (dirty, jid),
    )

    for path in (
        f"/api/jobs/{jid}",
        "/api/jobs",
        "/api/logs",
        f"/api/roles/{role_id}/logs",
    ):
        data = client.get(path).json()
        blob = str(data)
        for s in (
            "EXTRA_SECRET_SENTINEL",
            "EXTRA_COOKIE_SENTINEL",
            "EXTRA_DEVICE_SENTINEL",
            "token=",
            "cookie=",
            "traceback",
            "adb -s",
            "C:\\\\SENTINEL",
            "private.png",
        ):
            assert s.lower() not in blob.lower(), f"{path} leaked {s}"
        # 若结构中出现 job 对象，不得有 extras 键
        if isinstance(data, dict) and "job" in data:
            assert "extras" not in data["job"]
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "job_id" in data[0]:
                assert "extras" not in data[0]


def test_new_write_extras_ignores_taskresult_extras(client):
    """TaskResult.extras 普通键+敏感值不得写入 extras_json 或 API。"""
    import api.executor as exec_mod
    import json
    from api.db import connect

    poison = {
        "detail": "token=EXTRA_SECRET_SENTINEL",
        "debug": "cookie=EXTRA_COOKIE_SENTINEL",
        "note": r"C:\SENTINEL\private.png adb -s EXTRA_DEVICE_SENTINEL",
        "channel": "should-not-use-this-value",
    }

    def bad_runner(task_key, role, cfg=None, force_route=None):
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            "timeout",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=["step"],
            extras=poison,
        )

    exec_mod.set_task_runner(bad_runner)
    role_id = client.get("/api/roles").json()[0]["role_id"]
    body = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    ).json()
    jid = body["job"]["job_id"]
    assert "extras" not in body["job"]
    assert "extras" not in body.get("result", {})
    blob = str(body)
    for s in (
        "EXTRA_SECRET_SENTINEL",
        "EXTRA_COOKIE_SENTINEL",
        "EXTRA_DEVICE_SENTINEL",
        "should-not-use-this-value",
        "token=",
        "cookie=",
        "private.png",
        "adb -s",
    ):
        assert s.lower() not in blob.lower()

    row = connect().execute(
        "SELECT extras_json FROM jobs WHERE job_id=?", (jid,)
    ).fetchone()
    raw = row["extras_json"] or "{}"
    for s in (
        "EXTRA_SECRET_SENTINEL",
        "EXTRA_COOKIE_SENTINEL",
        "EXTRA_DEVICE_SENTINEL",
        "token=",
        "cookie=",
        "private.png",
        "Traceback",
        "adb -s",
        "should-not-use-this-value",
    ):
        assert s not in raw
    parsed = json.loads(raw)
    assert set(parsed.keys()) <= {"channel"}
    if "channel" in parsed:
        assert parsed["channel"] in ("vision", "protocol_mock")

    for path in (
        f"/api/jobs/{jid}",
        "/api/jobs",
        "/api/logs",
        f"/api/roles/{role_id}/logs",
    ):
        resp = client.get(path).json()
        b = str(resp).lower()
        for s in (
            "extra_secret_sentinel",
            "extra_cookie_sentinel",
            "extra_device_sentinel",
            "token=",
            "cookie=",
            "private.png",
            "adb -s",
        ):
            assert s not in b
    # 正常诊断字段仍在
    job = client.get(f"/api/jobs/{jid}").json()["job"]
    assert job["task_key"] == "mail"
    assert job["route"] == "vision"
    assert job["status"] in ("failed", "blocked")
    assert job["channel_label"] == "本地识图执行"
    assert "failure_code" in job
    assert "user_message" in job
    exec_mod.set_task_runner(None)
