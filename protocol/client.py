# -*- coding: utf-8 -*-
"""游戏 API 客户端占位。

真实环境：在此封装 HTTP/WS、公共头、签名。
当前：MockGameClient，用内存假数据模拟响应。
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List


class MockGameClient:
    """不访问外网的假客户端。"""

    def __init__(self, role_id: str, session: Dict[str, Any]):
        self.role_id = role_id
        self.session = session

    def mail_list(self) -> List[Dict[str, Any]]:
        time.sleep(0.05)  # 模拟网络
        return [
            {"id": "m1", "title": "掠夺城池", "unread": True},
            {"id": "m2", "title": "勋贵奖励", "unread": True},
            {"id": "m3", "title": "系统通知", "unread": False},
        ]

    def mail_claim_all(self) -> Dict[str, Any]:
        time.sleep(0.08)
        unread = sum(1 for m in self.mail_list() if m.get("unread"))
        return {"claimed": unread, "rewards": ["铜钱x1000", "粮草x500"] if unread else []}

    def zhengwu_list(self) -> List[Dict[str, Any]]:
        time.sleep(0.05)
        n = random.randint(0, 3)
        return [{"id": f"z{i}", "title": f"政务事项{i}"} for i in range(n)]

    def zhengwu_handle(self, item_id: str) -> Dict[str, Any]:
        time.sleep(0.04)
        return {"id": item_id, "ok": True}

    def yiguan_status(self) -> Dict[str, Any]:
        time.sleep(0.05)
        return {"level": 11, "claimable": random.choice([True, False]), "progress": "0/1"}

    def yiguan_claim(self) -> Dict[str, Any]:
        time.sleep(0.06)
        return {"ok": True, "gained": ["加速x1"]}
