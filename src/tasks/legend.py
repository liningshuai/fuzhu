"""见证传奇。

流程：
  主城 -> 征战 -> 探险 -> 见证传奇
       -> 按配置滚动定位目标英雄 -> 点击挑战
       -> 编队已由游戏自动完成，只点击「开始挑战」
       -> 等待挑战结束 -> 返回见证传奇列表
       -> 免费 2 次用完后，按配置逐次购买 0~5 次并继续挑战
       -> 返回主城
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from typing import Any

import cv2
from loguru import logger

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    UI_BACK_FALLBACK,
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_main_city,
    open_war_list,
    ui_back,
)


EXPLORE_TAB = (750, 345)
LEGEND_ENTRY = (540, 480)
ADD_CHANCE = (700, 1820)
BUY_CONFIRM = (785, 1235)
CHALLENGE = (540, 1665)
# 图2的编队弹窗会覆盖在英雄详情页上方，底层详情页的“挑战”按钮仍然
# 可能露在弹窗下方。只在弹窗底部按钮带内匹配，避免误点到底层按钮。
START_CHALLENGE_REGION = (240, 1480, 650, 170)
BUY_CONFIRM_REGION = (580, 1050, 430, 420)
# 购买弹窗标题实际位于弹窗上半部中央；区域过宽时，列表背景会把
# 「提示」模板误匹配出来，导致弹窗已经关闭却一直被判定为仍存在。
BUY_TITLE_REGION = (300, 730, 500, 200)
BUY_TITLE_THRESHOLD = 0.82
# 战斗页专用返回区域。任务头像在返回箭头右侧，禁止使用通用返回点。
BATTLE_BACK_REGION = (0, 60, 220, 240)
BATTLE_BACK_FALLBACK = (105, 171)
# 见证传奇的次数显示位于列表底部。这里只裁剪“数字/斜杠”区域，避免把
# 动态英雄卡片、红点和底图带入判断。
LEGEND_TIMES_DIGIT_REGION = (500, 1820, 70, 50)
# 开始挑战后，战斗结果/奖励页面通过点击空白处逐层跳过。
RESULT_SKIP_POINTS = ((30, 500), (50, 900), (1030, 900), (540, 1000))
MAX_RESULT_SKIP_TAPS = 24

LEGEND_SCROLL_REGION = (20, 300, 1040, 1450)
HERO_CARD_REGION = (25, 310, 1030, 1450)
MAX_HERO_SWIPES = 8
FREE_CHANCES = 2
MAX_EXTRA_PURCHASES = 5

HEROES: list[dict[str, Any]] = [
    {"id": "zhangjiao", "name": "张角", "template": "legend_hero_zhangjiao"},
    {"id": "wangyue", "name": "王越", "template": "legend_hero_wangyue"},
    {"id": "zixushangren", "name": "紫虚上人", "template": "legend_hero_zixushangren"},
    {"id": "mazhong", "name": "马忠", "template": "legend_hero_mazhong"},
    {"id": "sunjian", "name": "孙坚", "template": "legend_hero_sunjian"},
    {"id": "gongsunpu", "name": "公孙璞", "template": "legend_hero_gongsunpu"},
    {"id": "liru", "name": "李儒", "template": "legend_hero_liru"},
    {"id": "zhoucang", "name": "周仓", "template": "legend_hero_zhoucang"},
]
HERO_BY_ID = {hero["id"]: hero for hero in HEROES}


def _task_meta() -> dict[str, Any]:
    return (config.get("tasks") or {}).get("legend") or {}


def _task_opt(key: str, default: Any) -> Any:
    return _task_meta().get(key, default)


def _find(ctx: TaskContext, screen, name: str, threshold: float = 0.75, region=None):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold, region=region)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, point: tuple[int, int]) -> None:
    ctx.device.tap(int(point[0]), int(point[1]), jitter=False)


def _debug_capture(
    ctx: TaskContext,
    step: str,
    screen,
    *,
    region: tuple[int, int, int, int] | None = None,
    hit=None,
    click_point: tuple[int, int] | None = None,
    note: str = "",
) -> None:
    """保存见证传奇每个关键步骤的原图和识别标注图。"""
    try:
        directory = config.root / "assets" / "screenshots" / "legend_debug"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        base = f"{stamp}_{step}"
        raw_path = directory / f"{base}_raw.png"
        marked_path = directory / f"{base}_marked.png"

        ctx.matcher.imwrite(raw_path, screen)
        marked = screen.copy()
        if region:
            x, y, w, h = region
            cv2.rectangle(marked, (x, y), (x + w, y + h), (0, 0, 255), 4)
            cv2.putText(
                marked,
                f"search=({x},{y},{w},{h})",
                (max(5, x), max(28, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        if hit:
            left = hit.x - hit.w // 2
            top = hit.y - hit.h // 2
            cv2.rectangle(
                marked,
                (left, top),
                (left + hit.w, top + hit.h),
                (0, 255, 0),
                4,
            )
            cv2.drawMarker(
                marked,
                (hit.x, hit.y),
                (255, 0, 0),
                cv2.MARKER_CROSS,
                36,
                4,
            )
            cv2.putText(
                marked,
                f"hit=({hit.x},{hit.y}) score={hit.score:.3f}",
                (max(5, left), min(marked.shape[0] - 12, top + hit.h + 30)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        if click_point:
            cv2.circle(marked, click_point, 18, (255, 0, 255), 4)
            cv2.putText(
                marked,
                f"click=({click_point[0]},{click_point[1]})",
                (max(5, click_point[0] - 100), max(30, click_point[1] - 24)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 0, 255),
                2,
                cv2.LINE_AA,
            )
        if note:
            cv2.putText(
                marked,
                note,
                (12, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
        ctx.matcher.imwrite(marked_path, marked)
        logger.info(
            "见证传奇调试截图 [{}] raw={} marked={}",
            step,
            raw_path,
            marked_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("保存见证传奇调试截图失败 [{}]: {}", step, exc)


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def is_explore_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    # 征战页本身也有「探险」Tab；必须同时看到见证传奇入口卡片。
    return _find(ctx, screen, "legend_entry", 0.60, region=(80, 390, 920, 260)) is not None


def is_legend_list(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    if is_hero_detail(ctx, screen) or is_form_page(ctx, screen):
        return False
    return _find(ctx, screen, "legend_add", 0.60, region=(560, 1650, 300, 260)) is not None


def is_hero_detail(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find(ctx, screen, "legend_challenge", 0.64, region=(250, 1450, 600, 300)) is not None


def is_form_page(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    # 不同客户端版本的编队弹窗标题可能是“英雄历练”或“见证传奇”；
    # 底部唯一的“开始挑战”按钮才是确认编队弹窗的必要条件。
    title_region = (250, 220, 650, 180)
    title = _find(ctx, screen, "legend_form_title", 0.64, region=title_region)
    if title is None:
        title = _find(ctx, screen, "legend_title", 0.64, region=title_region)
    if title is None:
        return False
    return _find(
        ctx,
        screen,
        "legend_start_challenge_area",
        0.62,
        region=START_CHALLENGE_REGION,
    ) is not None


def is_battle_page(ctx: TaskContext, screen=None) -> bool:
    """战斗画面判定：返回箭头存在，且编队/列表标记已经消失。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "legend_battle_back", 0.60, region=BATTLE_BACK_REGION) is None:
        return False
    if _find(ctx, screen, "legend_form_title", 0.60, region=(250, 220, 650, 180)):
        return False
    if _find(ctx, screen, "legend_start_challenge_area", 0.60, region=START_CHALLENGE_REGION):
        return False
    if _find(ctx, screen, "legend_add", 0.60, region=(560, 1650, 300, 260)):
        return False
    return True


def _wait(ctx: TaskContext, predicate, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate(ctx):
            return True
        time.sleep(0.35)
    return predicate(ctx)


def open_explore(ctx: TaskContext) -> bool:
    if is_explore_page(ctx):
        return True
    if not open_war_list(ctx):
        return False
    before = ctx.screenshot()
    explore_region = (550, 230, 400, 230)
    hit = _find(ctx, before, "legend_explore_tab", 0.60, region=explore_region)
    _debug_capture(
        ctx,
        "explore_before",
        before,
        region=explore_region,
        hit=hit,
        click_point=(hit.x, hit.y) if hit else EXPLORE_TAB,
        note="探险入口识别",
    )
    _tap(ctx, (hit.x, hit.y) if hit else EXPLORE_TAB)
    result = _wait(ctx, is_explore_page, 8.0)
    _debug_capture(
        ctx,
        "explore_after",
        ctx.screenshot(),
        note=f"is_explore_page={result}",
    )
    return result


def open_legend_list(ctx: TaskContext) -> bool:
    if is_legend_list(ctx):
        return True
    if not open_explore(ctx):
        return False
    before = ctx.screenshot()
    entry_region = (80, 390, 920, 260)
    hit = _find(ctx, before, "legend_entry", 0.60, region=entry_region)
    _debug_capture(
        ctx,
        "legend_entry_before",
        before,
        region=entry_region,
        hit=hit,
        click_point=(hit.x, hit.y) if hit else LEGEND_ENTRY,
        note="见证传奇入口识别",
    )
    _tap(ctx, (hit.x, hit.y) if hit else LEGEND_ENTRY)
    result = _wait(ctx, is_legend_list, 8.0)
    _debug_capture(
        ctx,
        "legend_entry_after",
        ctx.screenshot(),
        note=f"is_legend_list={result}",
    )
    return result


def _hero_target() -> dict[str, Any] | None:
    hero_id = str(_task_opt("hero", "") or "").strip()
    return HERO_BY_ID.get(hero_id)


def _extra_purchases() -> int:
    try:
        return max(0, min(MAX_EXTRA_PURCHASES, int(_task_opt("extra_purchases", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _progress_today() -> tuple[int, int]:
    hero = _hero_target()
    if hero is None or str(_task_opt("last_progress_date", "") or "") != _today():
        return 0, 0
    if str(_task_opt("progress_hero", "") or "") != hero["id"]:
        return 0, 0
    try:
        completed = max(0, int(_task_opt("completed_count", 0) or 0))
    except (TypeError, ValueError):
        completed = 0
    try:
        purchased = max(0, min(MAX_EXTRA_PURCHASES, int(_task_opt("purchased_count", 0) or 0)))
    except (TypeError, ValueError):
        purchased = 0
    return completed, purchased


def _save_progress(completed: int, purchased: int) -> None:
    hero = _hero_target()
    config.set_task_option("legend", "last_progress_date", _today())
    config.set_task_option("legend", "progress_hero", hero["id"] if hero else "")
    config.set_task_option("legend", "completed_count", completed)
    config.set_task_option("legend", "purchased_count", purchased)
    config.save_runtime()


def _times_digit_crop(screen):
    x, y, width, height = LEGEND_TIMES_DIGIT_REGION
    if y + height > screen.shape[0] or x + width > screen.shape[1]:
        return None
    return screen[y : y + height, x : x + width]


def _times_mask(image):
    """提取次数框中的黄/橙色数字，降低底图亮度变化的影响。"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (8, 60, 100), (45, 255, 255))


def _times_components(mask) -> list[tuple[int, int, int, int, int]]:
    """返回次数框内的主要字符组件，按从左到右排列。"""
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    components = []
    for index in range(1, count):
        x, y, width, height, area = [int(value) for value in stats[index]]
        if width >= 8 and height >= 16 and area >= 20:
            components.append((x, y, width, height, area))
    return sorted(components)


def _classify_times_digit(component: tuple[int, int, int, int, int]) -> int | None:
    """按当前游戏字体的几何特征识别次数框中的单个数字。"""
    _x, _y, width, _height, area = component
    if width <= 12:
        return 1
    if width <= 18:
        if area >= 225:
            return 0
        return 3
    if width >= 20:
        return 4
    if width >= 19:
        return 2
    return None


def _times_state(screen) -> tuple[int, int | None, tuple[tuple[int, int, int], ...]] | None:
    """识别次数框状态。

    返回剩余次数、可选的总次数和一个包含“剩余数字/斜杠/总次数”三部分
    的结构签名。购买校验使用完整三部分签名，因此 ``2/2 -> 2/4``
    这种只改变分母的状态也能被识别为购买成功。
    """
    crop = _times_digit_crop(screen)
    if crop is None:
        return None
    components = _times_components(_times_mask(crop))
    if len(components) < 3:
        return None

    first, slash, last = components[:3]
    if not (first[0] < slash[0] < last[0]):
        return None

    remaining = _classify_times_digit(first)
    if remaining not in (0, 1, 2):
        return None
    total = _classify_times_digit(last)

    signature = tuple(
        (component[2], component[3], int(round(component[4] / 10.0)))
        for component in (first, slash, last)
    )
    return remaining, total, signature


def _times_area_from_screen(screen) -> int | None:
    state = _times_state(screen)
    if state is None:
        return None
    crop = _times_digit_crop(screen)
    if crop is None:
        return None
    components = _times_components(_times_mask(crop))
    return components[0][4] if components else None


def _remaining_chances(ctx: TaskContext, screen=None) -> int | None:
    """识别列表底部次数框的当前值。

    当前素材中稳定可用的是剩余数字 0/1/2。识别不到时返回 None，
    上层会安全失败，而不是在次数不足时误点“挑战”。
    """
    screen = screen if screen is not None else ctx.screenshot()
    state = _times_state(screen)
    if state is None:
        return None
    value, total, signature = state
    logger.debug(
        "见证传奇剩余次数识别为 {}/{}，次数框签名={}",
        value,
        total if total is not None else "?",
        signature,
    )
    return value


def _verify_times_readable(ctx: TaskContext) -> bool:
    screen = ctx.screenshot()
    state = _times_state(screen)
    if state is None:
        logger.warning("购买后无法确认见证传奇次数框，停止进入挑战流程")
        _debug_capture(ctx, "times_unrecognized", screen, note="剩余次数无法确认")
        return False
    remaining, total, _signature = state
    logger.info(
        "购买后见证传奇次数框已确认：{}/{}",
        remaining,
        total if total is not None else "?",
    )
    return True


def _find_hero(ctx: TaskContext, hero: dict[str, Any]) -> Any | None:
    """在当前列表和有限滚动范围内寻找目标英雄名称。"""
    for attempt in range(MAX_HERO_SWIPES + 1):
        screen = ctx.screenshot()
        hit = _find(ctx, screen, hero["template"], 0.64, region=HERO_CARD_REGION)
        if hit:
            logger.info("找到目标英雄 {} @({},{}) swipe={}", hero["name"], hit.x, hit.y, attempt)
            return hit
        if attempt >= MAX_HERO_SWIPES:
            break
        # 列表从上到下滚动；避开底部次数/按钮区域。
        ctx.device.swipe(540, 1350, 540, 600, duration_ms=500)
        time.sleep(0.8)
    return None


def _hero_card_point(hit) -> tuple[int, int]:
    # 名称位于卡片右侧，点击卡片中央触发详情，避免直接点文本。
    return max(180, min(540, hit.x - 240)), hit.y + 120


def open_target_hero(ctx: TaskContext, hero: dict[str, Any]) -> bool:
    """打开面板选择的目标英雄详情，不操作编队武将。"""
    hit = _find_hero(ctx, hero)
    if not hit:
        return False
    point = _hero_card_point(hit)
    _debug_capture(
        ctx,
        "hero_before",
        ctx.screenshot(),
        region=HERO_CARD_REGION,
        hit=hit,
        click_point=point,
        note=f"目标英雄={hero['name']}",
    )
    logger.info("点击目标英雄卡片 {} @{}", hero["name"], point)
    _tap(ctx, point)
    result = _wait(ctx, is_hero_detail, 8.0)
    _debug_capture(
        ctx,
        "hero_after",
        ctx.screenshot(),
        note=f"is_hero_detail={result}",
    )
    return result


def _click_challenge(ctx: TaskContext) -> bool:
    screen = ctx.screenshot()
    challenge_region = (250, 1450, 600, 300)
    hit = _find(ctx, screen, "legend_challenge", 0.62, region=challenge_region)
    _debug_capture(
        ctx,
        "challenge_before",
        screen,
        region=challenge_region,
        hit=hit,
        click_point=(hit.x, hit.y) if hit else CHALLENGE,
        note="英雄详情挑战按钮识别",
    )
    _tap(ctx, (hit.x, hit.y) if hit else CHALLENGE)
    result = _wait(ctx, is_form_page, 8.0)
    _debug_capture(
        ctx,
        "challenge_after",
        ctx.screenshot(),
        note=f"is_form_page={result}",
    )
    if not result:
        prompt = _find(
            ctx,
            ctx.screenshot(),
            "legend_buy_title",
            BUY_TITLE_THRESHOLD,
            region=BUY_TITLE_REGION,
        )
        if prompt:
            logger.warning("点击挑战后出现增加挑战次数提示，说明剩余次数不足")
    return result


def _click_start_challenge(ctx: TaskContext, hero: dict[str, Any]) -> bool:
    """编队已经自动完成，只匹配并点击唯一的“开始挑战”按钮。

    这里禁止固定坐标兜底，也不做任何武将选择/排序；模板未匹配到时
    只等待下一帧，避免误点编队行或底层详情页按钮。
    """
    for attempt in range(3):
        screen = ctx.screenshot()
        if not is_form_page(ctx, screen):
            time.sleep(0.4)
            continue

        hit = _find(
            ctx,
            screen,
            "legend_start_challenge_area",
            0.58,
            region=START_CHALLENGE_REGION,
        )
        _debug_capture(
            ctx,
            f"start_before_{attempt + 1}",
            screen,
            region=START_CHALLENGE_REGION,
            hit=hit,
            click_point=(hit.x, hit.y) if hit else None,
            note="仅允许点击开始挑战",
        )
        if hit:
            logger.info(
                "编队已自动完成，仅点击开始挑战 @({},{}), score={:.3f}, attempt={}",
                hit.x,
                hit.y,
                hit.score,
                attempt + 1,
            )
            _tap(ctx, (hit.x, hit.y))
            deadline = time.time() + 8.0
            captured_after = False
            after = screen
            while time.time() < deadline:
                time.sleep(0.4)
                after = ctx.screenshot()
                if not captured_after:
                    _debug_capture(
                        ctx,
                        f"start_after_{attempt + 1}",
                        after,
                        note=f"is_battle_page={is_battle_page(ctx, after)}",
                    )
                    captured_after = True
                if is_battle_page(ctx, after):
                    logger.info("开始挑战已生效，已进入战斗页")
                    return True
            _debug_capture(
                ctx,
                f"start_timeout_{attempt + 1}",
                after,
                note="点击后未离开编队弹窗",
            )
            logger.warning("开始挑战点击后未离开编队弹窗，下一次只重试同一按钮")
            continue

        logger.debug(
            "编队弹窗已出现但未匹配到开始挑战按钮，等待下一帧，不点击其他区域"
        )
        time.sleep(0.6)

    logger.warning("未能点击编队弹窗开始挑战按钮")
    return False


def _return_from_battle(ctx: TaskContext, hero: dict[str, Any]) -> bool:
    """开始战斗后立即返回，并点击空白处跳过结算/奖励页面。"""
    deadline = time.time() + 8.0
    while time.time() < deadline:
        screen = ctx.screenshot()
        hit = _find(ctx, screen, "legend_battle_back", 0.60, region=BATTLE_BACK_REGION)
        if is_battle_page(ctx, screen):
            point = (hit.x, hit.y) if hit else BATTLE_BACK_FALLBACK
            _debug_capture(
                ctx,
                "battle_back_before",
                screen,
                region=BATTLE_BACK_REGION,
                hit=hit,
                click_point=point,
                note="战斗页专用返回，只点击左上角箭头",
            )
            logger.info("战斗已开始，立即点击战斗页左上角返回 @{}", point)
            _tap(ctx, point)
            return _skip_challenge_result(ctx, hero)
        time.sleep(0.35)

    logger.warning("开始挑战后未识别到战斗页左上角返回箭头")
    return False


def _skip_challenge_result(ctx: TaskContext, hero: dict[str, Any]) -> bool:
    """连续点击安全空白点，直到回到见证传奇列表。"""
    for index in range(MAX_RESULT_SKIP_TAPS):
        screen = ctx.screenshot()
        if is_legend_list(ctx, screen):
            logger.info("{} 本次挑战已返回见证传奇列表，跳过结算 {} 次", hero["name"], index)
            return True
        if is_main_city(ctx, screen):
            logger.warning("跳过挑战结算时意外回到主城")
            return False
        point = RESULT_SKIP_POINTS[index % len(RESULT_SKIP_POINTS)]
        if index == 0 or index == MAX_RESULT_SKIP_TAPS - 1:
            _debug_capture(
                ctx,
                f"result_skip_{index + 1}",
                screen,
                click_point=point,
                note=f"连续点击空白处跳过结算，第{index + 1}次",
            )
        logger.debug("点击空白处跳过见证传奇结算 @{}，第 {}/{} 次", point, index + 1, MAX_RESULT_SKIP_TAPS)
        _tap(ctx, point)
        time.sleep(0.55)

    final = ctx.screenshot()
    if is_legend_list(ctx, final):
        logger.info("{} 跳过结算后已回到见证传奇列表", hero["name"])
        return True
    logger.warning("连续点击空白处后仍未回到见证传奇列表")
    return False


def _buy_one(ctx: TaskContext) -> bool:
    if not is_legend_list(ctx):
        return False
    logger.info("见证传奇免费次数用尽，点击 + 购买 1 次")
    before = ctx.screenshot()
    before_state = _times_state(before)
    before_remaining = before_state[0] if before_state else None
    before_signature = before_state[2] if before_state else None
    logger.info("购买前见证传奇剩余次数：{}", before_remaining if before_remaining is not None else "无法识别")
    add_region = (560, 1650, 300, 260)
    hit = _find(ctx, before, "legend_add", 0.58, region=add_region)
    _debug_capture(
        ctx,
        "buy_add_before",
        before,
        region=add_region,
        hit=hit,
        click_point=(hit.x, hit.y) if hit else None,
        note="点击增加挑战次数",
    )
    _tap(ctx, (hit.x, hit.y) if hit else ADD_CHANCE)
    time.sleep(0.8)

    # 购买弹窗确认优先使用通用确定模板，限制在弹窗右下区域。
    for attempt in range(12):
        screen = ctx.screenshot()
        title = _find(
            ctx,
            screen,
            "legend_buy_title",
            BUY_TITLE_THRESHOLD,
            region=BUY_TITLE_REGION,
        )
        confirm = _find(
            ctx,
            screen,
            "legend_buy_confirm_area",
            0.58,
            region=BUY_CONFIRM_REGION,
        )
        _debug_capture(
            ctx,
            f"buy_confirm_before_{attempt + 1}",
            screen,
            region=BUY_CONFIRM_REGION,
            hit=confirm,
            click_point=(confirm.x, confirm.y) if confirm else None,
            note=f"title={'yes' if title else 'no'}",
        )
        if confirm:
            _tap(ctx, (confirm.x, confirm.y))
            deadline = time.time() + 6.0
            captured_after = False
            after = screen
            while time.time() < deadline:
                time.sleep(0.4)
                after = ctx.screenshot()
                still_title = _find(
                    ctx,
                    after,
                    "legend_buy_title",
                    BUY_TITLE_THRESHOLD,
                    region=BUY_TITLE_REGION,
                )
                still_confirm = _find(
                    ctx,
                    after,
                    "legend_buy_confirm_area",
                    0.58,
                    region=BUY_CONFIRM_REGION,
                )
                if not captured_after:
                    _debug_capture(
                        ctx,
                        f"buy_confirm_after_{attempt + 1}",
                        after,
                        region=BUY_CONFIRM_REGION,
                        hit=still_confirm,
                        note=f"title={'yes' if still_title else 'no'}",
                    )
                    captured_after = True
                if not still_title and not still_confirm and is_legend_list(ctx, after):
                    after_state = _times_state(after)
                    after_remaining = after_state[0] if after_state else None
                    after_signature = after_state[2] if after_state else None
                    signature_unchanged = (
                        before_signature is not None
                        and after_signature is not None
                        and before_signature == after_signature
                    )
                    if signature_unchanged or (
                        before_remaining is not None
                        and after_remaining is not None
                        and after_remaining < before_remaining
                    ):
                        logger.warning(
                            "购买弹窗已关闭，但次数框未增加（购买后剩余={}）；停止重复点击，避免重复消费",
                            after_remaining if after_remaining is not None else "无法识别",
                        )
                        _debug_capture(
                            ctx,
                            f"buy_count_unchanged_{attempt + 1}",
                            after,
                            note=f"before={before_remaining} after={after_remaining}",
                        )
                        return False
                    if after_remaining is None:
                        if (
                            before_signature is not None
                            and after_signature is not None
                            and before_signature != after_signature
                        ):
                            logger.info(
                                "购买确认已生效，次数框签名已变化（剩余数字暂未归类）：{} -> {}",
                                before_signature,
                                after_signature,
                            )
                            return True
                        logger.warning("购买弹窗已关闭，但无法确认剩余次数是否增加")
                        return False
                    logger.info(
                        "见证传奇购买确认已生效，剩余次数由 {} 变为 {}，次数框签名已更新",
                        before_remaining if before_remaining is not None else "?",
                        after_remaining,
                    )
                    return True
            _debug_capture(
                ctx,
                f"buy_confirm_timeout_{attempt + 1}",
                after,
                region=BUY_CONFIRM_REGION,
                note="购买确认后弹窗仍未关闭",
            )
            logger.warning("购买确认点击后弹窗未关闭，下一次只重试确定按钮")
        time.sleep(0.3)
    logger.warning("未识别见证传奇购买确认按钮")
    return False


def _close_to_list(ctx: TaskContext) -> None:
    for _ in range(4):
        if is_legend_list(ctx):
            return
        _tap(ctx, UI_BACK_FALLBACK)
        time.sleep(0.8)


def _run_one_challenge(ctx: TaskContext, hero: dict[str, Any]) -> bool:
    if not is_legend_list(ctx):
        return False
    if not open_target_hero(ctx, hero):
        return False
    if not _click_challenge(ctx):
        return False
    if not _click_start_challenge(ctx, hero):
        return False
    if not _return_from_battle(ctx, hero):
        return False
    # 返回列表即视为本场完成；不会再等待目标卡片的“英雄历练中”状态结束。
    return True

def leave_to_main(ctx: TaskContext) -> None:
    for _ in range(7):
        dismiss_confirm_dialogs(ctx, max_rounds=1)
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return
        if is_hero_detail(ctx, screen) or is_form_page(ctx, screen) or is_legend_list(ctx, screen) or is_explore_page(ctx, screen):
            ui_back(ctx)
            continue
        _tap(ctx, UI_BACK_FALLBACK)
        time.sleep(0.8)
    ensure_main_city(ctx)


class LegendTask(BaseTask):
    id = "legend"
    name = "见证传奇"
    description = "征战→探险→见证传奇→选择英雄→挑战"
    required_templates = [
        "nav_war",
        "war_title",
        "legend_explore_tab",
        "legend_entry",
        "legend_title",
        "legend_add",
        "legend_challenge",
        "legend_form_title",
        "legend_start_challenge_area",
        "legend_buy_title",
        "legend_buy_confirm_area",
        "legend_battle_back",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        dismiss_confirm_dialogs(ctx, max_rounds=2)
        hero = _hero_target()
        if hero is None:
            return TaskResult(TaskStatus.SKIPPED, "未选择见证传奇英雄")

        if not open_legend_list(ctx):
            leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法进入见证传奇")

        completed, purchased = _progress_today()
        extra_target = _extra_purchases()
        initial_state = _times_state(ctx.screenshot())
        if initial_state is None:
            leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法识别见证传奇当前剩余挑战次数")

        initial_remaining, initial_total, _initial_signature = initial_state
        observed_completed = (
            max(0, initial_total - initial_remaining)
            if initial_total is not None
            else max(0, FREE_CHANCES - initial_remaining)
        )
        completed = max(completed, observed_completed)

        # 能识别总次数时，优先用总次数判断账号是否已经手动购买过额外次数。
        # 例如 0/4 不应再被当作 0/2 重复购买；识别不到时回退到任务进度。
        observed_extra = (
            max(0, initial_total - FREE_CHANCES)
            if initial_total is not None
            else purchased
        )
        purchased = max(purchased, min(extra_target, observed_extra))
        purchases_to_make = max(0, extra_target - purchased)
        purchased_this_run = purchases_to_make

        logger.info(
            "见证传奇入口状态：剩余={}/{}，已完成估计={}，配置购买={}，还需购买={}，本轮应挑战={}次",
            initial_remaining,
            initial_total if initial_total is not None else "?",
            completed,
            extra_target,
            purchases_to_make,
            initial_remaining + purchases_to_make,
        )

        # 0/2 且配置购买0，或 0/4 且配置购买次数已全部存在，今日无需再做。
        if initial_remaining == 0 and purchases_to_make == 0:
            if initial_total is not None:
                completed = max(completed, initial_total)
            _save_progress(completed, purchased)
            leave_to_main(ctx)
            return TaskResult(TaskStatus.SUCCESS, f"今日见证传奇已完成：{hero['name']} 共{completed}次")

        # 先购买本次还缺少的额外次数，再开始任何英雄挑战。
        while purchases_to_make > 0:
            logger.info(
                "见证传奇先购买额外挑战次数：第 {}/{} 次",
                extra_target - purchases_to_make + 1,
                extra_target,
            )
            if not _buy_one(ctx):
                leave_to_main(ctx)
                return TaskResult(
                    TaskStatus.FAILED,
                    f"购买第 {extra_target - purchases_to_make + 1} 次挑战机会失败",
                )
            purchased += 1
            purchases_to_make -= 1
            _save_progress(completed, purchased)

        # 购买后允许显示 0/3、0/4 等状态；这里只确认次数框仍可读取，
        # 不再要求剩余数字必须至少为 2。
        if not _verify_times_readable(ctx):
            leave_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "购买后无法确认见证传奇次数状态")

        # 入口剩余次数 + 本轮新购买次数，才是本轮需要实际执行的挑战数：
        # 0/2 + 购买2次执行2次；2/2 + 购买2次执行4次。
        remaining_to_run = initial_remaining + purchased_this_run
        while remaining_to_run > 0:
            if not _run_one_challenge(ctx, hero):
                leave_to_main(ctx)
                return TaskResult(
                    TaskStatus.FAILED,
                    f"{hero['name']}本轮还剩 {remaining_to_run} 次挑战未完成",
                )
            completed += 1
            remaining_to_run -= 1
            _save_progress(completed, purchased)
            logger.info("见证传奇 {} 本轮完成1次，剩余本轮挑战{}次", hero["name"], remaining_to_run)

        leave_to_main(ctx)
        return TaskResult(
            TaskStatus.SUCCESS,
            f"见证传奇完成：{hero['name']}，共{completed}次（购买{purchased}次）",
        )
