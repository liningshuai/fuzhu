"""配置加载与热更新。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "default.yaml"
RUNTIME_CONFIG_PATH = ROOT / "config" / "runtime.yaml"
WAREHOUSE_CONFIG_PATH = ROOT / "config" / "warehouse.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """进程内单例配置。"""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if RUNTIME_CONFIG_PATH.exists():
            with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8") as f:
                runtime = yaml.safe_load(f) or {}
            data = _deep_merge(data, runtime)
        self._data = data

    def save_runtime(self) -> None:
        RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 只持久化可热改项，避免整份默认配置被覆盖
        payload = {
            "device": {
                "serial": self._data.get("device", {}).get("serial"),
                "adb_path": self._data.get("device", {}).get("adb_path"),
            },
            "tasks": self._data.get("tasks", {}),
            "bot": {
                "loop_interval": self._data.get("bot", {}).get("loop_interval"),
            },
        }
        with open(RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set_task_enabled(self, task_id: str, enabled: bool) -> None:
        tasks = self._data.setdefault("tasks", {})
        if task_id not in tasks:
            tasks[task_id] = {"enabled": enabled, "name": task_id}
        else:
            tasks[task_id]["enabled"] = enabled

    def set_task_option(self, task_id: str, key: str, value: Any) -> None:
        """更新任务选项（如 guoguan.buy_extra），并写回内存配置。"""
        tasks = self._data.setdefault("tasks", {})
        if task_id not in tasks:
            tasks[task_id] = {"name": task_id}
        tasks[task_id][key] = value

    def set_device_serial(self, serial: str) -> None:
        self._data.setdefault("device", {})["serial"] = serial

    @property
    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    @property
    def root(self) -> Path:
        return ROOT


config = Config()


def load_warehouse_config() -> dict[str, Any]:
    with open(WAREHOUSE_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return copy.deepcopy(data)
