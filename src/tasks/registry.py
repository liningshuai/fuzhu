"""任务注册表。"""

from __future__ import annotations

from datetime import date
from typing import Type

from src.config import config
from src.tasks.base import BaseTask
from src.tasks.placeholder import PlaceholderTask
from src.tasks.auto_mail import AutoMailTask
from src.tasks.daily_wish import DailyWishTask
from src.tasks.guoguan import GuoguanTask
from src.tasks.heroes_arena import HeroesArenaTask
from src.tasks.legend import LegendTask
from src.tasks.mingshi import MingshiTask
from src.tasks.stargaze import StargazeTask
from src.tasks.pipeline_task import PipelineTask
from src.tasks.zizhong_station import ZizhongStationTask


# 已实现的任务
IMPLEMENTED: dict[str, Type[BaseTask]] = {
    "auto_mail": AutoMailTask,
    "daily_wish": DailyWishTask,
    "guoguan": GuoguanTask,
    "heroes_arena": HeroesArenaTask,
    "legend": LegendTask,
    "mingshi": MingshiTask,
    "stargaze": StargazeTask,
    "zizhong_station": ZizhongStationTask,
}

# 配置中所有任务 id（含占位）
def _all_task_ids() -> list[str]:
    tasks = config.get("tasks") or {}
    return list(tasks.keys())


TASK_REGISTRY: dict[str, Type[BaseTask]] = {}


def _build_registry() -> None:
    TASK_REGISTRY.clear()
    for task_id in _all_task_ids():
        if task_id in IMPLEMENTED:
            TASK_REGISTRY[task_id] = IMPLEMENTED[task_id]
        else:
            # 动态生成占位类
            meta = (config.get("tasks") or {}).get(task_id) or {}

            class _P(PlaceholderTask):
                id = task_id
                name = meta.get("name", task_id)
                description = meta.get("description", "功能开发中")

            _P.__name__ = f"Placeholder_{task_id}"
            TASK_REGISTRY[task_id] = _P


def create_task(task_id: str) -> BaseTask:
    _build_registry()
    meta = (config.get("tasks") or {}).get(task_id) or {}
    if str(meta.get("implementation", "python")).lower() == "pipeline":
        return PipelineTask(
            task_id=task_id,
            pipeline_id=str(meta.get("pipeline") or task_id),
            enabled=bool(meta.get("enabled", False)),
        )
    cls = TASK_REGISTRY.get(task_id)
    if cls is None:
        raise KeyError(f"未知任务: {task_id}")
    return cls(enabled=bool(meta.get("enabled", False)))


def list_task_meta() -> list[dict]:
    _build_registry()
    result = []
    for task_id, cls in TASK_REGISTRY.items():
        meta = (config.get("tasks") or {}).get(task_id) or {}
        item = {
            "id": task_id,
            "name": meta.get("name") or cls.name,
            "description": meta.get("description") or cls.description,
            "enabled": bool(meta.get("enabled", False)),
            "implemented": task_id in IMPLEMENTED,
            "options": {},
        }
        # 任务专属可调选项（面板用）
        if task_id == "guoguan":
            item["options"] = {
                "buy_extra": bool(meta.get("buy_extra", False)),
                "max_runs": int(meta.get("max_runs", 2) or 2),
                "battle_timeout": int(meta.get("battle_timeout", 900) or 900),
            }
        if task_id == "daily_wish":
            from src.tasks.daily_wish import (
                DEFAULT_REWARDS,
                REWARD_CATALOG,
                REWARD_LABELS,
                _LEGACY_REWARD_MAP,
                get_selected_rewards,
            )

            # 统一走 get_selected_rewards（含旧 id 迁移）
            try:
                sel = get_selected_rewards()
            except Exception:  # noqa: BLE001
                sel = list(meta.get("selected_rewards") or DEFAULT_REWARDS)[:4]
                sel = [_LEGACY_REWARD_MAP.get(str(x), str(x)) for x in sel]
            item["options"] = {
                "selected_rewards": list(sel)[:4],
                "claim_login_chest": bool(meta.get("claim_login_chest", True)),
                "reward_catalog": [
                    {
                        "id": r["id"],
                        "name": REWARD_LABELS.get(r["id"], r["name"]),
                    }
                    for r in REWARD_CATALOG
                ],
            }
        if task_id == "zizhong_station":
            from src.tasks.zizhong_station import RESOURCE_CATALOG, _task_opt

            resource = str(_task_opt("resource", "food") or "food")
            if resource not in {r["id"] for r in RESOURCE_CATALOG}:
                resource = "food"
            today = date.today().isoformat()
            last_purchase_date = str(_task_opt("last_purchase_date", "") or "")
            try:
                purchased_count = int(_task_opt("purchased_count", 0) or 0)
            except (TypeError, ValueError):
                purchased_count = 0
            if last_purchase_date != today:
                purchased_count = 0
            item["options"] = {
                "resource": resource,
                "purchased_count": max(0, min(3, purchased_count)),
                "max_free_purchases": 3,
                "last_purchase_date": last_purchase_date,
                "resource_catalog": [
                    {"id": r["id"], "name": r["name"]} for r in RESOURCE_CATALOG
                ],
            }
        if task_id == "heroes_arena":
            last_completed_date = str(meta.get("last_completed_date", "") or "")
            item["options"] = {
                "last_completed_date": last_completed_date,
                "completed_today": last_completed_date == date.today().isoformat(),
                "flow": "征战→武馆→比武大会→冠军点赞→报名",
            }
        if task_id == "legend":
            from src.tasks.legend import HEROES, _task_opt

            hero = str(_task_opt("hero", "") or "")
            if hero not in {item["id"] for item in HEROES}:
                hero = ""
            try:
                extra = max(0, min(5, int(_task_opt("extra_purchases", 0) or 0)))
            except (TypeError, ValueError):
                extra = 0
            last_date = str(_task_opt("last_progress_date", "") or "")
            progress_hero = str(_task_opt("progress_hero", "") or "")
            try:
                completed_count = max(0, int(_task_opt("completed_count", 0) or 0))
            except (TypeError, ValueError):
                completed_count = 0
            try:
                purchased_count = max(0, min(5, int(_task_opt("purchased_count", 0) or 0)))
            except (TypeError, ValueError):
                purchased_count = 0
            if last_date != date.today().isoformat() or progress_hero != hero:
                completed_count = 0
                purchased_count = 0
            item["options"] = {
                "hero": hero,
                "extra_purchases": extra,
                "completed_count": completed_count,
                "purchased_count": purchased_count,
                "total_chances": 2 + extra,
                "hero_catalog": [{"id": h["id"], "name": h["name"]} for h in HEROES],
            }
        if task_id == "mingshi":
            last_purchase_date = str(meta.get("last_purchase_date", "") or "")
            item["options"] = {
                "last_purchase_date": last_purchase_date,
                "completed_today": bool(meta.get("completed_today", False))
                and last_purchase_date == date.today().isoformat(),
            }
        if task_id == "stargaze":
            last_completed_date = str(meta.get("last_completed_date", "") or "")
            try:
                max_free_observations = int(
                    meta.get("max_free_observations", 3) or 3
                )
            except (TypeError, ValueError):
                max_free_observations = 3
            item["options"] = {
                "max_free_observations": max(1, min(3, max_free_observations)),
                "last_completed_date": last_completed_date,
                "completed_today": bool(meta.get("completed_today", False))
                and last_completed_date == date.today().isoformat(),
            }
        result.append(item)
    return result
