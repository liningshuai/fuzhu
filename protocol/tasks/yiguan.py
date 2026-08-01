# -*- coding: utf-8 -*-
"""协议任务：自动驿馆（mock）。"""
from __future__ import annotations

from common.models import ExecRoute, RoleContext, TaskKey, TaskResult, TaskStatusCode
from protocol.client import MockGameClient
from protocol.session import SessionService


class YiguanProtocolTask:
    key = TaskKey.YIGUAN

    def __init__(self, session_svc: SessionService | None = None):
        self._session = session_svc or SessionService()

    def run(self, ctx: RoleContext) -> TaskResult:
        bad = self._session.ensure_alive(ctx)
        if bad:
            bad.task_key = self.key
            bad.route = ExecRoute.PROTOCOL
            return bad

        client = MockGameClient(ctx.role_id, ctx.session)
        try:
            status = client.yiguan_status()
            extras = {"status": status, "mock": True}
            if status.get("claimable"):
                claim = client.yiguan_claim()
                extras["claim"] = claim
                msg = f"mock 驿馆领取完成 level={status.get('level')}"
            else:
                msg = f"mock 驿馆无可领 level={status.get('level')}"
            return TaskResult.success(
                msg,
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
                extras=extras,
            )
        except Exception as e:  # noqa: BLE001
            return TaskResult.fail(
                TaskStatusCode.TEMP_FAIL,
                f"mock 驿馆异常: {e}",
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
            )
