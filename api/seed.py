# -*- coding: utf-8 -*-
"""幂等演示数据初始化：不覆盖已有真实数据。"""
from __future__ import annotations

import logging
from typing import Optional

from api.settings import settings
from api.store import SQLiteStore, store as default_store
from common.models import DeviceTarget, RoleContext, TaskImpl, TaskKey
from common.registry_meta import TASK_CATALOG

log = logging.getLogger("fuzhu.api.seed")

DEMO_ROLE_ID = "demo-role-1"
DEMO_DEVICE_ID = "local-ldplayer"


def seed_demo_data(store: Optional[SQLiteStore] = None, *, force: bool = False) -> dict:
    """初始化单设备 + demo 角色。

    - 若设备/角色已存在且 force=False：跳过，不覆盖
    - force=True 仅用于测试，仍不删除历史 Job
    """
    s = store or default_store
    s.initialize()

    created = {"device": False, "role": False, "tasks": False}

    device_id = settings.default_device_id or DEMO_DEVICE_ID
    existing_dev = s.get_device(device_id)
    if not existing_dev:
        s.upsert_device(
            DeviceTarget(
                device_id=device_id,
                adb_serial=settings.default_adb_serial,
                name=settings.default_device_name,
            )
        )
        created["device"] = True
        log.info("seed: 创建默认设备 %s", device_id)
    elif force:
        s.upsert_device(
            DeviceTarget(
                device_id=device_id,
                adb_serial=settings.default_adb_serial,
                name=settings.default_device_name,
            )
        )

    existing_role = s.get_role(DEMO_ROLE_ID)
    if not existing_role:
        s.upsert_role(
            RoleContext(
                role_id=DEMO_ROLE_ID,
                role_name="小笼包",
                server_id="h8_26",
                server_name="h8_26",
                device_id=device_id,
                session={"mock_session": True},
            )
        )
        # 默认任务配置：邮件 vision 开、政务 vision 关、驿馆 auto 关
        for key, meta in TASK_CATALOG.items():
            if key == TaskKey.MAIL:
                enabled, impl = True, TaskImpl.VISION
            elif key == TaskKey.ZHENGWU:
                enabled, impl = False, TaskImpl.VISION
            else:
                enabled, impl = False, TaskImpl.AUTO
            s.patch_task_config(
                DEMO_ROLE_ID,
                key,
                enabled=enabled,
                interval_minutes=meta.default_interval_minutes,
                impl=impl,
            )
        created["role"] = True
        created["tasks"] = True
        log.info("seed: 创建演示角色 %s（已绑定 %s）", DEMO_ROLE_ID, device_id)
    else:
        # 角色已存在：仅补齐缺失的 task 配置行（upsert_role 会 IGNORE）
        s.upsert_role(existing_role, ensure_task_defaults=True)
        log.info("seed: 演示角色已存在，跳过覆盖")

    return {
        "ok": True,
        "created": created,
        "device_id": device_id,
        "role_id": DEMO_ROLE_ID,
        "message": "幂等初始化完成（未覆盖已有数据）"
        if not any(created.values())
        else "已写入缺失的演示数据",
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = seed_demo_data()
    print(result)


if __name__ == "__main__":
    main()
