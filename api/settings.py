# -*- coding: utf-8 -*-
"""API 进程配置：默认仅本机；局域网需显式开启并设置管理口令。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "fuzhu.db"
CONFIG_PATH = ROOT / "config" / "config.yaml"


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    # 仅当 allow_lan=true 时允许非 loopback 绑定；同时必须配置 admin_token
    allow_lan: bool = False
    admin_token: str = ""
    db_path: str = str(DEFAULT_DB_PATH)
    # 单设备默认绑定（本阶段只支持一台）
    default_device_id: str = "local-ldplayer"
    default_adb_serial: str = "127.0.0.1:5555"
    default_device_name: str = "本地雷电"
    # 测试可关闭调度
    enable_scheduler: bool = True


def _load_yaml() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> ApiSettings:
    raw = _load_yaml()
    api_raw = dict(raw.get("api") or {})
    adb_raw = raw.get("adb") or {}
    if "default_adb_serial" not in api_raw and adb_raw.get("serial"):
        api_raw["default_adb_serial"] = str(adb_raw["serial"])

    # 环境变量覆盖（测试 / 运维）
    if os.environ.get("FUZHU_DB_PATH"):
        api_raw["db_path"] = os.environ["FUZHU_DB_PATH"]
    if os.environ.get("FUZHU_ALLOW_LAN") is not None:
        api_raw["allow_lan"] = os.environ["FUZHU_ALLOW_LAN"].lower() in (
            "1",
            "true",
            "yes",
        )
    if os.environ.get("FUZHU_ADMIN_TOKEN") is not None:
        api_raw["admin_token"] = os.environ["FUZHU_ADMIN_TOKEN"]
    if os.environ.get("FUZHU_DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        api_raw["enable_scheduler"] = False

    settings = ApiSettings.model_validate(api_raw)

    # 相对路径 → 项目根
    dbp = Path(settings.db_path)
    if not dbp.is_absolute():
        settings.db_path = str((ROOT / dbp).resolve())
    else:
        settings.db_path = str(dbp)

    if settings.allow_lan:
        if not (settings.admin_token and settings.admin_token.strip()):
            raise RuntimeError(
                "api.allow_lan=true 时必须设置 api.admin_token（本地管理口令）"
            )
        if settings.host in ("127.0.0.1", "localhost"):
            settings.host = "0.0.0.0"
    else:
        settings.host = "127.0.0.1"

    return settings


# 进程内缓存；测试可重新 load
settings: ApiSettings = load_settings()
