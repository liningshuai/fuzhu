# -*- coding: utf-8 -*-
"""Phase 1.1：单设备 FIFO 队列与并发正确性（fake vision，无 ADB）。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4

from common.models import ExecRoute, Job, JobStatus, TaskKey, TaskResult, utc_now
from tests.conftest import wait_job_terminal


def _slow_vision_runner(gate, order, delay=0.05):
    def runner(task_key, role, cfg=None, force_route=None):
        order.append(("start", task_key.value))
        deadline = time.time() + 8
        while not gate.get("open") and time.time() < deadline:
            time.sleep(0.01)
        time.sleep(delay)
        order.append(("end", task_key.value))
        return TaskResult.success(
            f"fake {task_key.value}",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=[f"fake:{task_key.value}"],
            extras={"fake": True, "verified": True},
        )

    return runner


def test_run_enabled_mail_zhengwu_independent_fifo(client):
    """mail+zhengwu enabled → 两个独立 job_id；先 running 后 queued；串行终态。"""
    import api.executor as exec_mod

    role_id = client.get("/api/roles").json()[0]["role_id"]
    client.patch(
        f"/api/roles/{role_id}/tasks/mail",
        json={"enabled": True, "impl": "vision"},
    )
    client.patch(
        f"/api/roles/{role_id}/tasks/zhengwu",
        json={"enabled": True, "impl": "vision"},
    )
    client.patch(
        f"/api/roles/{role_id}/tasks/yiguan",
        json={"enabled": False},
    )

    gate = {"open": False}
    order = []
    exec_mod.set_task_runner(_slow_vision_runner(gate, order))

    r = client.post(f"/api/roles/{role_id}/run-enabled")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    jobs = body["jobs"]
    assert len(jobs) == 2

    keys = {j["task_key"] for j in jobs}
    assert keys == {"mail", "zhengwu"}
    ids = {j["job_id"] for j in jobs}
    assert len(ids) == 2, "must be two distinct job_ids"

    # 刷新状态
    time.sleep(0.08)
    states = {}
    for j in jobs:
        detail = client.get(f"/api/jobs/{j['job_id']}").json()["job"]
        states[detail["task_key"]] = detail

    statuses = {s["status"] for s in states.values()}
    assert "running" in statuses
    assert "queued" in statuses
    running = [s for s in states.values() if s["status"] == "running"]
    queued = [s for s in states.values() if s["status"] == "queued"]
    assert len(running) == 1
    assert len(queued) == 1
    assert running[0]["job_id"] != queued[0]["job_id"]
    assert running[0]["task_key"] != queued[0]["task_key"]

    first_id = running[0]["job_id"]
    second_id = queued[0]["job_id"]

    gate["open"] = True
    wait_job_terminal(client, first_id, timeout=6)
    # 第二个应随后 running→终态
    wait_job_terminal(client, second_id, timeout=6)

    j1 = client.get(f"/api/jobs/{first_id}").json()["job"]
    j2 = client.get(f"/api/jobs/{second_id}").json()["job"]
    assert j1["status"] == "succeeded"
    assert j2["status"] == "succeeded"
    assert j1["task_key"] in ("mail", "zhengwu")
    assert j2["task_key"] in ("mail", "zhengwu")
    assert j1["task_key"] != j2["task_key"]

    # 串行：第一个 end 不晚于第二个 start（记录顺序）
    starts = [x for x in order if x[0] == "start"]
    ends = [x for x in order if x[0] == "end"]
    assert len(starts) == 2 and len(ends) == 2
    # 第一个任务完整结束后才开始第二个
    first_task = starts[0][1]
    assert ends[0][1] == first_task
    assert starts[1][1] != first_task

    exec_mod.set_task_runner(None)


def test_same_task_reuse_not_cross_task(client):
    import api.executor as exec_mod

    gate = {"open": False}
    order = []
    exec_mod.set_task_runner(_slow_vision_runner(gate, order, delay=0.02))

    role_id = client.get("/api/roles").json()[0]["role_id"]
    r1 = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": False},
    )
    jid_mail = r1.json()["job"]["job_id"]
    assert r1.json()["created"] is True

    # 同 task 复用
    r2 = client.post(
        f"/api/roles/{role_id}/tasks/mail/run",
        json={"force_route": "vision", "wait": False},
    )
    assert r2.json()["reused"] is True
    assert r2.json()["job"]["job_id"] == jid_mail
    assert r2.json()["job"]["task_key"] == "mail"

    # 不同 task 必须新 Job，绝不能返回 mail 的 id
    r3 = client.post(
        f"/api/roles/{role_id}/tasks/zhengwu/run",
        json={"force_route": "vision", "wait": False},
    )
    body3 = r3.json()
    assert body3["job"]["task_key"] == "zhengwu"
    assert body3["job"]["job_id"] != jid_mail
    assert body3["created"] is True
    assert body3["reused"] is False
    # 应排队
    time.sleep(0.05)
    st = client.get(f"/api/jobs/{body3['job']['job_id']}").json()["job"]["status"]
    assert st in ("queued", "running")

    gate["open"] = True
    wait_job_terminal(client, jid_mail, timeout=6)
    wait_job_terminal(client, body3["job"]["job_id"], timeout=6)
    exec_mod.set_task_runner(None)


def test_20_concurrent_requests_at_most_one_running(client):
    import api.executor as exec_mod
    from api.store import store

    role_id = client.get("/api/roles").json()[0]["role_id"]
    device_id = client.get("/api/roles").json()[0]["device_id"]

    gate = {"open": False}
    order = []
    max_running = {"n": 0}
    lock = threading.Lock()

    def runner(task_key, role, cfg=None, force_route=None):
        with lock:
            c = store.count_running_vision(device_id)
            if c > max_running["n"]:
                max_running["n"] = c
        order.append(task_key.value)
        deadline = time.time() + 10
        while not gate["open"] and time.time() < deadline:
            time.sleep(0.01)
            with lock:
                c = store.count_running_vision(device_id)
                if c > max_running["n"]:
                    max_running["n"] = c
        return TaskResult.success(
            "ok",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=["ok"],
            extras={"fake": True},
        )

    exec_mod.set_task_runner(runner)

    def post(task):
        return client.post(
            f"/api/roles/{role_id}/tasks/{task}/run",
            json={"force_route": "vision", "wait": False},
        )

    tasks = (["mail", "zhengwu"] * 10)
    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futs = [pool.submit(post, t) for t in tasks]
        for f in as_completed(futs):
            results.append(f.result().json())

    job_ids = {r["job"]["job_id"] for r in results}
    # 同 task 复用 → 至多 2 个独立 Job
    assert len(job_ids) == 2
    by_task = {}
    for r in results:
        by_task.setdefault(r["job"]["task_key"], set()).add(r["job"]["job_id"])
    assert len(by_task["mail"]) == 1
    assert len(by_task["zhengwu"]) == 1
    assert by_task["mail"] != by_task["zhengwu"]

    # 采样 running 数量
    for _ in range(30):
        with lock:
            c = store.count_running_vision(device_id)
            if c > max_running["n"]:
                max_running["n"] = c
        time.sleep(0.02)

    assert max_running["n"] <= 1

    gate["open"] = True
    for jid in job_ids:
        wait_job_terminal(client, jid, timeout=8)

    # 不重复领取：每个 job 终态一次
    for jid in job_ids:
        j = client.get(f"/api/jobs/{jid}").json()["job"]
        assert j["status"] == "succeeded"

    exec_mod.set_task_runner(None)


def test_concurrent_claim_never_double_running(client):
    """直接插入多条 queued，多线程 claim_next 任意时刻 running≤1。"""
    from api.store import store

    role = client.get("/api/roles").json()[0]
    device_id = role["device_id"]
    role_id = role["role_id"]

    # 清掉可能的 active（测试隔离库通常干净）
    inserted = []
    for i in range(12):
        # 绕过同 task 复用限制：直接 create_job（不同 job，同 task 仅用于 claim 压力）
        # 使用 yiguan 与 mail 交替，且强制插入 queued（允许同 task 多 job 仅本测试）
        job = Job(
            job_id=uuid4().hex,
            role_id=role_id,
            device_id=device_id,
            task_key=TaskKey.MAIL if i % 2 == 0 else TaskKey.ZHENGWU,
            route=ExecRoute.VISION,
            status=JobStatus.QUEUED,
            message="stress-queue",
            created_at=utc_now(),
        )
        store.create_job(job)
        inserted.append(job.job_id)

    claimed = []
    lock = threading.Lock()

    def claim_once():
        j = store.claim_next_vision_job(device_id)
        if j:
            with lock:
                claimed.append(j.job_id)
            # 模拟极短执行后完成，腾出 running
            time.sleep(0.01)
            j.status = JobStatus.SUCCEEDED
            j.message = "stress-done"
            j.finished_at = utc_now()
            j.duration_ms = 1
            store.update_job(j)
            # 再尝试领取下一个
            j2 = store.claim_next_vision_job(device_id)
            if j2:
                with lock:
                    claimed.append(j2.job_id)
                j2.status = JobStatus.SUCCEEDED
                j2.finished_at = utc_now()
                j2.duration_ms = 1
                store.update_job(j2)

    threads = [threading.Thread(target=claim_once) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # 无重复领取
    assert len(claimed) == len(set(claimed))
    assert store.count_running_vision(device_id) <= 1
