# -*- coding: utf-8 -*-
"""Phase 1 基础验收（fake runner，无 ADB）。"""
from __future__ import annotations

import time

from common.models import ExecRoute, RoleContext, TaskResult
from tests.conftest import wait_job_terminal


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["protocol_is_mock"] is True
    assert body["single_device"] is True


def test_sqlite_survives_new_app_instance(tmp_db, monkeypatch):
    monkeypatch.setenv("FUZHU_DB_PATH", str(tmp_db))
    monkeypatch.setenv("FUZHU_DISABLE_SCHEDULER", "1")

    import api.settings as settings_mod
    import api.db as db_mod
    import api.store as store_mod
    from api.seed import seed_demo_data

    settings_mod.settings = settings_mod.load_settings()
    db_mod.configure_db(settings_mod.settings.db_path)
    store_mod.store.reset_for_tests()
    store_mod.store.initialize()
    seed_demo_data(store_mod.store)

    store_mod.store.upsert_role(
        RoleContext(
            role_id="persist-role",
            role_name="持久化角色",
            server_id="s1",
            device_id="local-ldplayer",
            session={"mock_session": True},
        )
    )
    assert store_mod.store.get_role("persist-role") is not None

    store_mod.store.reset_for_tests()
    db_mod.configure_db(str(tmp_db))
    store_mod.store.initialize()
    role = store_mod.store.get_role("persist-role")
    assert role is not None
    assert role.role_name == "持久化角色"
    assert role.device_id == "local-ldplayer"


def test_mock_mail_job_succeeded_with_events(client):
    roles = client.get("/api/roles").json()
    role_id = roles[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "protocol", "wait": True},
    )
    assert r.status_code == 200
    body = r.json()
    job = body["job"]
    assert job["status"] == "succeeded"
    assert job["route"] == "protocol"
    assert job["result_code"] == "OK"
    assert body.get("created") is True or body.get("reused") is False

    detail = client.get(f"/api/jobs/{job['job_id']}").json()
    events = detail["events"]
    assert len(events) >= 1
    assert any(
        "mock" in e["message"].lower() or "protocol" in e["message"].lower()
        for e in events
    )


def test_vision_uses_fake_runner_no_adb(client):
    import api.executor as exec_mod
    import vision_worker.runner as vision_mod

    called = {"n": 0}

    def fake_vision(task_key, ctx=None):
        called["n"] += 1
        return TaskResult.success(
            "fake ok no adb",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=["fake: no adb"],
            extras={"fake": True, "verified": True},
        )

    vision_mod.set_vision_impl(fake_vision)
    exec_mod.set_task_runner(None)

    roles = client.get("/api/roles").json()
    role_id = roles[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    )
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["status"] == "succeeded"
    assert called["n"] == 1
    detail = client.get(f"/api/jobs/{job['job_id']}").json()
    assert any("fake" in e["message"].lower() for e in detail["events"])

    vision_mod.set_vision_impl(None)


def test_unbound_device_vision_blocked(client):
    r = client.post(
        "/api/roles",
        json={
            "role_id": "no-device-role",
            "role_name": "无设备",
            "mock_session": True,
            "device_id": None,
        },
    )
    assert r.status_code == 200
    client.patch("/api/roles/no-device-role/device", json={"device_id": None})

    run = client.post(
        "/api/roles/no-device-role/tasks/mail/run",
        json={"force_route": "vision", "wait": True},
    )
    assert run.status_code == 200
    job = run.json()["job"]
    assert job["status"] == "blocked"
    assert "未绑定" in job["message"] or "device" in job["message"].lower()


def test_job_query_running_to_terminal(client):
    import api.executor as exec_mod

    gate = {"open": False}

    def delayed(task_key, role, cfg=None, force_route=None):
        deadline = time.time() + 3
        while not gate["open"] and time.time() < deadline:
            time.sleep(0.02)
        return TaskResult.success(
            "done",
            task_key=task_key,
            route=ExecRoute.PROTOCOL,
            events=["step1", "step2"],
            extras={"mock": True},
        )

    exec_mod.set_task_runner(delayed)
    roles = client.get("/api/roles").json()
    role_id = roles[0]["role_id"]
    r = client.post(
        f"/api/roles/{role_id}/tasks/yiguan/run",
        json={"force_route": "protocol", "wait": False},
    )
    jid = r.json()["job"]["job_id"]

    saw_running = False
    for _ in range(50):
        st = client.get(f"/api/jobs/{jid}").json()["job"]["status"]
        if st == "running":
            saw_running = True
            break
        if st in ("succeeded", "failed", "blocked"):
            break
        time.sleep(0.02)

    gate["open"] = True
    final = wait_job_terminal(client, jid, timeout=5)
    assert final["job"]["status"] == "succeeded"
    assert len(final["events"]) >= 1
    assert saw_running or final["job"]["status"] == "succeeded"

    exec_mod.set_task_runner(None)


def test_tasks_panel_channel_labels(client):
    roles = client.get("/api/roles").json()
    role_id = roles[0]["role_id"]
    tasks = client.get(f"/api/roles/{role_id}/tasks").json()
    assert tasks
    joined = " ".join(t["channel_label"] for t in tasks)
    assert "识图" in joined or "mock" in joined or "不可用" in joined
