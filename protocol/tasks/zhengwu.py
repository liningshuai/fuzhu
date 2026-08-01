# -*- coding: utf-8 -*-
"""协议任务：自动政务（mock）。"""
from __future__ import annotations

from common.models import ExecRoute, RoleContext, TaskKey, TaskResult, TaskStatusCode
from protocol.client import MockGameClient
from protocol.session import SessionService


class ZhengwuProtocolTask:
    key = TaskKey.ZHENGWU

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
            items = client.zhengwu_list()
            handled = []
            for it in items:
                client.zhengwu_handle(it["id"])
                handled.append(it["id"])
            return TaskResult.success(
                f"mock 政务处理完成：{len(handled)} 项",
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
                extras={"handled": handled, "mock": True},
            )
        except Exception as e:  # noqa: BLE001
            return TaskResult.fail(
                TaskStatusCode.TEMP_FAIL,
                f"mock 政务异常: {e}",
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
            )
