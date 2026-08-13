"""本地 Web 控制面板。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.bot.engine import engine
from src.config import config
from src.tasks.registry import list_task_meta
from src.warehouse.controller import WarehouseScanController
from src.warehouse.store import WarehouseCatalogStore

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"
WAREHOUSE_ACTIVE_STATUSES = frozenset({"running", "stopping"})

app = FastAPI(title="兵临天下辅助", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
warehouse_controller = WarehouseScanController()


class TaskToggle(BaseModel):
    task_id: str
    enabled: bool


class TaskOptionBody(BaseModel):
    task_id: str
    key: str
    value: Any


class DeviceSerial(BaseModel):
    serial: str = Field(..., min_length=1)


class StartBody(BaseModel):
    ensure_game: bool = True


def _warehouse_catalog_path() -> Path:
    return warehouse_controller.database_path


def _warehouse_conflict(
    *,
    message: str,
    snapshot: dict[str, Any],
    engine_running: bool = False,
) -> HTTPException:
    return HTTPException(
        409,
        {
            "error": "warehouse_scan_conflict",
            "message": message,
            "controller_status": snapshot.get("status"),
            "engine_running": bool(engine_running),
            "scan_id": snapshot.get("scan_id"),
            "snapshot": dict(snapshot),
        },
    )


def _warehouse_not_active(
    *,
    message: str,
    snapshot: dict[str, Any],
) -> HTTPException:
    return HTTPException(
        409,
        {
            "error": "warehouse_scan_not_active",
            "message": message,
            "controller_status": snapshot.get("status"),
            "scan_id": snapshot.get("scan_id"),
            "snapshot": dict(snapshot),
        },
    )


def _warehouse_unavailable(
    *,
    message: str,
    engine_status: dict[str, Any],
) -> HTTPException:
    return HTTPException(
        503,
        {
            "error": "warehouse_scan_unavailable",
            "message": message,
            "device_online": bool(engine_status.get("device_online")),
            "engine_running": bool(engine_status.get("running")),
        },
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = TEMPLATE_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    # 面板轮询也要读取最新 runtime 配置，确保开关和任务元数据与实际执行一致。
    config.reload()
    status = engine.status()
    status["web_title"] = config.get("web", "title")
    status["config"] = {
        "serial": config.get("device", "serial"),
        "adb_path": config.get("device", "adb_path"),
        "package": config.get("game", "package"),
        "loop_interval": config.get("bot", "loop_interval"),
    }
    return status


@app.get("/api/tasks")
def api_tasks() -> list[dict[str, Any]]:
    config.reload()
    return list_task_meta()


@app.post("/api/tasks/toggle")
def api_toggle(body: TaskToggle) -> dict[str, Any]:
    config.reload()
    tasks = config.get("tasks") or {}
    if body.task_id not in tasks:
        raise HTTPException(404, f"未知任务: {body.task_id}")
    config.set_task_enabled(body.task_id, body.enabled)
    config.save_runtime()
    return {"ok": True, "tasks": list_task_meta()}


# 允许面板修改的任务选项白名单
_TASK_OPTION_KEYS: dict[str, set[str]] = {
    "guoguan": {"buy_extra", "max_runs", "battle_timeout"},
    "daily_wish": {"selected_rewards", "claim_login_chest"},
    "zizhong_station": {"resource"},
    "legend": {"hero", "extra_purchases"},
    "stargaze": {"max_free_observations"},
}


@app.post("/api/tasks/option")
def api_task_option(body: TaskOptionBody) -> dict[str, Any]:
    """更新任务选项，例如过关斩将 buy_extra、每日许愿 selected_rewards。"""
    config.reload()
    tasks = config.get("tasks") or {}
    if body.task_id not in tasks:
        raise HTTPException(404, f"未知任务: {body.task_id}")
    allowed = _TASK_OPTION_KEYS.get(body.task_id)
    if not allowed or body.key not in allowed:
        raise HTTPException(400, f"任务 {body.task_id} 不支持选项: {body.key}")

    value = body.value
    if body.key == "buy_extra":
        value = bool(value)
    elif body.key == "claim_login_chest":
        value = bool(value)
    elif body.key == "selected_rewards":
        if not isinstance(value, list):
            raise HTTPException(400, "selected_rewards 必须是数组")
        from src.tasks.daily_wish import REWARD_BY_ID

        cleaned: list[str] = []
        for item in value:
            rid = str(item).strip()
            if rid in REWARD_BY_ID and rid not in cleaned:
                cleaned.append(rid)
            if len(cleaned) >= 4:
                break
        if len(cleaned) != 4:
            raise HTTPException(400, "请恰好选择 4 个许愿奖励")
        value = cleaned
    elif body.key == "resource":
        from src.tasks.zizhong_station import RESOURCE_BY_ID

        value = str(value).strip()
        if value not in RESOURCE_BY_ID:
            raise HTTPException(400, "resource 必须是 coin、food、wood 或 iron")
    elif body.key == "hero":
        from src.tasks.legend import HERO_BY_ID

        value = str(value).strip()
        if value and value not in HERO_BY_ID:
            raise HTTPException(400, "hero 不是支持的见证传奇英雄")
    elif body.key == "extra_purchases":
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "extra_purchases 必须是整数") from exc
        if value < 0 or value > 5:
            raise HTTPException(400, "extra_purchases 必须在 0 到 5 之间")
    elif body.key == "max_free_observations":
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "max_free_observations 必须是整数") from exc
        if value < 1 or value > 3:
            raise HTTPException(400, "max_free_observations 必须在 1 到 3 之间")
    elif body.key in ("max_runs", "battle_timeout"):
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{body.key} 必须是整数") from exc
        if value < 0:
            raise HTTPException(400, f"{body.key} 不能为负")

    config.set_task_option(body.task_id, body.key, value)
    config.save_runtime()
    return {"ok": True, "tasks": list_task_meta()}


@app.post("/api/device/serial")
def api_set_serial(body: DeviceSerial) -> dict[str, Any]:
    config.set_device_serial(body.serial.strip())
    config.save_runtime()
    engine.refresh_device()
    return {"ok": True, "serial": body.serial.strip()}


@app.get("/api/devices")
def api_devices() -> dict[str, Any]:
    engine.refresh_device()
    try:
        devices = engine.device.list_devices()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc
    return {"devices": devices, "current": config.get("device", "serial")}


@app.post("/api/bot/start")
def api_start(body: Optional[StartBody] = None) -> dict[str, str]:
    body = body or StartBody()
    msg = engine.start(ensure_game=body.ensure_game)
    return {"message": msg}


@app.post("/api/bot/stop")
def api_stop() -> dict[str, str]:
    return {"message": engine.stop()}


@app.post("/api/game/start")
def api_game_start() -> dict[str, str]:
    engine.refresh_device()
    try:
        engine.device.start_game()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc
    return {"message": "已请求启动游戏"}


@app.post("/api/game/stop")
def api_game_stop() -> dict[str, str]:
    engine.refresh_device()
    try:
        engine.device.stop_game()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc
    return {"message": "已停止游戏"}


@app.post("/api/screenshot")
def api_screenshot() -> dict[str, str]:
    engine.refresh_device()
    try:
        path = engine.device.save_screenshot("panel_latest.png")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc
    return {"message": "截图成功", "path": str(path), "url": "/api/screenshot/file"}


@app.get("/api/screenshot/file")
def api_screenshot_file() -> FileResponse:
    path = config.root / "assets" / "screenshots" / "panel_latest.png"
    if not path.exists():
        raise HTTPException(404, "还没有截图，请先点击截图")
    return FileResponse(path, media_type="image/png")


@app.post("/api/config/reload")
def api_reload() -> dict[str, str]:
    config.reload()
    engine.refresh_device()
    return {"message": "配置已重新加载"}


@app.get("/api/warehouse/status")
def api_warehouse_status() -> dict[str, Any]:
    return warehouse_controller.snapshot()


@app.post("/api/warehouse/scan")
def api_warehouse_scan() -> dict[str, Any]:
    snapshot = warehouse_controller.snapshot()
    if snapshot.get("status") in WAREHOUSE_ACTIVE_STATUSES:
        raise _warehouse_conflict(
            message="Warehouse scan already running.",
            snapshot=snapshot,
        )

    engine_status = engine.status() or {}
    if not bool(engine_status.get("device_online")):
        raise _warehouse_unavailable(
            message="Device is offline.",
            engine_status=engine_status,
        )
    if bool(engine_status.get("running")):
        raise _warehouse_conflict(
            message="Stop the bot engine before scanning the warehouse.",
            snapshot=snapshot,
            engine_running=True,
        )

    message = warehouse_controller.start()
    snapshot = warehouse_controller.snapshot()
    if message != "Warehouse scan started.":
        latest_engine_status = engine.status() or {}
        raise _warehouse_conflict(
            message=message,
            snapshot=snapshot,
            engine_running=bool(latest_engine_status.get("running")),
        )
    return snapshot


@app.post("/api/warehouse/stop")
def api_warehouse_stop() -> dict[str, Any]:
    snapshot = warehouse_controller.snapshot()
    if snapshot.get("status") not in WAREHOUSE_ACTIVE_STATUSES:
        raise _warehouse_not_active(
            message="No warehouse scan running.",
            snapshot=snapshot,
        )

    message = warehouse_controller.stop()
    snapshot = warehouse_controller.snapshot()
    if message == "No warehouse scan running.":
        raise _warehouse_not_active(
            message=message,
            snapshot=snapshot,
        )
    return snapshot


@app.get("/api/warehouse/items")
def api_warehouse_items(category: str | None = None) -> dict[str, Any]:
    store = WarehouseCatalogStore(path=_warehouse_catalog_path())
    try:
        store.open()
        items = store.get_items(category_code=category)
    finally:
        store.close()
    return {"category": category, "items": items}
