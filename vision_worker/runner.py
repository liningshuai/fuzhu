# -*- coding: utf-8 -*-
"""执行识图 yaml，输出统一 TaskResult。

支持注入 fake runner（测试不连 ADB）。
成功语义：Task.run 返回 True 且无 blocked 标记；yaml 内须含前置 wait + 后置验证。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from common.models import (
    ExecRoute,
    RoleContext,
    TaskKey,
    TaskResult,
    TaskStatusCode,
)
from core.adb import ADBClient, ADBError
from core.task import Task, TaskBlockedError, TaskError
from vision_worker.mapping import VISION_YAML

log = logging.getLogger("fuzhu.vision_worker")

ROOT = Path(__file__).resolve().parent.parent

# 测试注入：Callable[[TaskKey, Optional[RoleContext]], TaskResult]
_vision_impl: Optional[Callable[..., TaskResult]] = None


def set_vision_impl(impl: Optional[Callable[..., TaskResult]]) -> None:
    """测试用：替换真实 ADB 识图实现。"""
    global _vision_impl
    _vision_impl = impl


def vision_task_available(task_key: TaskKey) -> bool:
    name = VISION_YAML.get(task_key)
    if not name:
        return False
    return (ROOT / "tasks" / name).is_file()


def _load_config() -> Dict[str, Any]:
    path = ROOT / "config" / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"缺少配置: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _make_adb(config: Dict[str, Any], serial_override: Optional[str] = None) -> ADBClient:
    adb_cfg = config.get("adb", {})
    adb = ADBClient(
        adb_path=adb_cfg.get("adb_path", "adb"),
        serial=serial_override or adb_cfg.get("serial", "127.0.0.1:5555"),
    )
    adb.connect()
    return adb


def run_vision_task(
    task_key: TaskKey,
    ctx: Optional[RoleContext] = None,
) -> TaskResult:
    """在本地模拟器上跑对应 yaml。

    若已 set_vision_impl，则完全走注入实现（不连 ADB）。
    """
    if _vision_impl is not None:
        return _vision_impl(task_key, ctx)

    yaml_name = VISION_YAML.get(task_key)
    if not yaml_name:
        return TaskResult.fail(
            TaskStatusCode.UNSUPPORTED,
            f"识图未映射任务: {task_key.value}",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=[f"无 yaml 映射: {task_key.value}"],
        )

    task_path = ROOT / "tasks" / yaml_name
    if not task_path.is_file():
        return TaskResult.fail(
            TaskStatusCode.UNSUPPORTED,
            f"识图任务文件不存在: {task_path.name}",
            task_key=task_key,
            route=ExecRoute.VISION,
            events=[f"文件不存在: {yaml_name}"],
        )

    role_id = ctx.role_id if ctx else ""
    events = [f"开始识图任务 {yaml_name} role={role_id}"]
    log.info("vision run task=%s role=%s file=%s", task_key.value, role_id, yaml_name)

    try:
        config = _load_config()
        package = (config.get("game") or {}).get("package", "")
        # 优先使用角色绑定设备的 serial（本阶段单设备）
        serial = None
        if ctx and ctx.device_id:
            try:
                from api.store import store

                dev = store.get_device(ctx.device_id)
                if dev:
                    serial = dev.adb_serial
                    events.append(f"使用设备 {dev.device_id} serial={serial}")
            except Exception:  # noqa: BLE001
                pass
        adb = _make_adb(config, serial_override=serial)
        task = Task(
            str(task_path),
            adb,
            str(ROOT / "templates"),
            package=package,
        )
        events.append("前置检查与步骤执行中（需确认界面并完成操作后验证）")
        ok = task.run()
        events.extend(getattr(task, "step_events", []) or [])
        if ok:
            events.append("后置状态验证通过，任务成功")
            return TaskResult.success(
                f"识图任务完成: {task.name}",
                task_key=task_key,
                route=ExecRoute.VISION,
                extras={
                    "yaml": yaml_name,
                    "role_id": role_id,
                    "task_name": task.name,
                    "verified": True,
                },
                events=events,
            )
        err = getattr(task, "last_error", "") or "未知错误"
        # TaskBlockedError 会写入 last_status
        last_status = getattr(task, "last_status", None)
        code = (
            TaskStatusCode.BLOCKED
            if last_status == "blocked" or isinstance(getattr(task, "last_exc", None), TaskBlockedError)
            else TaskStatusCode.TEMP_FAIL
        )
        events.append(f"失败: {err}")
        return TaskResult.fail(
            code,
            f"识图任务{'阻塞' if code == TaskStatusCode.BLOCKED else '失败'}: {err}",
            task_key=task_key,
            route=ExecRoute.VISION,
            extras={"yaml": yaml_name, "role_id": role_id, "verified": False},
            events=events,
        )
    except TaskBlockedError as e:
        events.append(f"blocked: {e}")
        return TaskResult.fail(
            TaskStatusCode.BLOCKED,
            str(e),
            task_key=task_key,
            route=ExecRoute.VISION,
            extras={"role_id": role_id, "verified": False},
            events=events,
        )
    except ADBError as e:
        events.append(f"ADB 错误: {e}")
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            f"ADB 错误: {e}",
            task_key=task_key,
            route=ExecRoute.VISION,
            extras={"role_id": role_id},
            events=events,
        )
    except TaskError as e:
        events.append(f"任务错误: {e}")
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            f"任务错误: {e}",
            task_key=task_key,
            route=ExecRoute.VISION,
            extras={"role_id": role_id},
            events=events,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("vision worker unexpected error")
        events.append(f"异常: {e}")
        return TaskResult.fail(
            TaskStatusCode.TEMP_FAIL,
            f"识图执行异常: {e}",
            task_key=task_key,
            route=ExecRoute.VISION,
            extras={"role_id": role_id},
            events=events,
        )
