# -*- coding: utf-8 -*-
"""会话占位：登录 / 刷新 / 校验。

真实协议落地前仅做 mock 校验。
禁止使用 token / cookie / password 字段名；使用 mock_session 布尔占位。
"""
from __future__ import annotations

from typing import Any, Dict

from common.models import RoleContext, TaskResult, TaskStatusCode


class SessionService:
    def ensure_alive(self, ctx: RoleContext) -> TaskResult | None:
        """会话可用返回 None；不可用返回失败 TaskResult。"""
        session = ctx.session or {}
        # 仅认无敏感语义字段；兼容历史 mock_session 字符串真值
        flag = session.get("mock_session")
        if flag is True or flag == 1 or flag == "ok":
            return None
        if flag is False or flag == "expired":
            return TaskResult.fail(
                TaskStatusCode.NEED_RELOGIN,
                "会话已失效（mock_session）",
            )
        return TaskResult.fail(
            TaskStatusCode.NEED_RELOGIN,
            "会话缺失：请设置 session.mock_session=true（mock，非真实登录）",
        )

    def refresh(self, ctx: RoleContext) -> Dict[str, Any]:
        """刷新会话（mock：标记 refreshed，不出现敏感字段名）。"""
        session = dict(ctx.session or {})
        session["mock_session"] = True
        session["refreshed"] = True
        return session
