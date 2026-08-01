# -*- coding: utf-8 -*-
"""协议任务：自动领邮件（mock）。"""
from __future__ import annotations

from common.models import (
    ExecRoute,
    RoleContext,
    TaskKey,
    TaskResult,
    TaskStatusCode,
)
from protocol.client import MockGameClient
from protocol.session import SessionService


class MailProtocolTask:
    key = TaskKey.MAIL

    def __init__(self, session_svc: SessionService | None = None):
        self._session = session_svc or SessionService()

    def run(self, ctx: RoleContext) -> TaskResult:
        bad = self._session.ensure_alive(ctx)
        if bad:
            bad.task_key = self.key
            bad.route = ExecRoute.PROTOCOL
            return bad

        client = MockGameClient(ctx.role_id, ctx.session)
        events = ["protocol mock：校验会话", "protocol mock：拉取邮件列表"]
        try:
            before = client.mail_list()
            unread = sum(1 for m in before if m.get("unread"))
            events.append(f"protocol mock：未读 {unread}")
            resp = client.mail_claim_all()
            events.append(
                f"protocol mock：领取 claimed={resp.get('claimed')}（非真实游戏）"
            )
            return TaskResult.success(
                f"mock 领取邮件完成：未读 {unread}，claimed={resp.get('claimed')}",
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
                extras={
                    "unread_before": unread,
                    "claimed": resp.get("claimed"),
                    "rewards": resp.get("rewards", []),
                    "mock": True,
                    "channel": "协议模拟（mock，不会操作游戏）",
                },
                events=events,
            )
        except Exception as e:  # noqa: BLE001 — worker 边界捕获
            events.append(f"异常: {e}")
            return TaskResult.fail(
                TaskStatusCode.TEMP_FAIL,
                f"mock 邮件任务异常: {e}",
                task_key=self.key,
                route=ExecRoute.PROTOCOL,
                events=events,
            )
