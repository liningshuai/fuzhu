# -*- coding: utf-8 -*-
"""单设备互斥：同一 device_id 同一时刻最多一个 Vision Job。"""
from __future__ import annotations

from threading import Lock
from typing import Dict, Optional, Tuple


class DeviceLockManager:
    """进程内设备锁。

    返回 (acquired, existing_job_id)：
    - acquired=True：本 job 获得执行权
    - acquired=False：已有 running job，existing_job_id 为占用者
    """

    def __init__(self) -> None:
        self._guard = Lock()
        self._owners: Dict[str, str] = {}  # device_id -> job_id

    def try_acquire(self, device_id: str, job_id: str) -> Tuple[bool, Optional[str]]:
        with self._guard:
            current = self._owners.get(device_id)
            if current and current != job_id:
                return False, current
            self._owners[device_id] = job_id
            return True, None

    def release(self, device_id: str, job_id: str) -> None:
        with self._guard:
            if self._owners.get(device_id) == job_id:
                del self._owners[device_id]

    def owner(self, device_id: str) -> Optional[str]:
        with self._guard:
            return self._owners.get(device_id)

    def clear(self) -> None:
        with self._guard:
            self._owners.clear()


# 进程单例
device_locks = DeviceLockManager()
