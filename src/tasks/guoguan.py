"""过关斩将。

强制两步开战（缺一不可）：
  ① 准备页「开始挑战」(y≈1140)
  ② 创建编队「开始挑战」(y≈1580)

开战后（免费场 / 购买场 完全相同）：
  → 留在过关斩将「主界面」（大字「战斗中」+「查看战斗」）
  → 绝不要点「查看战斗」，不要进战斗详情（详情里有「下一战」）
  → 若误进详情：只点左上返回回到主界面，继续等
  → 等到主界面出现「获取奖励/领取奖励」再点

次数：
  max_runs — 免费次数打几轮
  buy_extra — 免费用完后是否 + 买 1 次再打（买完后仍走上面同一套等待）
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from src.config import config
from src.tasks.base import BaseTask, TaskContext, TaskResult, TaskStatus
from src.tasks.navigation import (
    dismiss_confirm_dialogs,
    ensure_main_city,
    is_guoguan_page,
    leave_to_main_from_war,
    open_guoguan,
)
from src.vision.match import TemplateMatcher

# 实测：旧模板曾裁到暗色背景，误匹配 y=1265；金色按钮中心约 y=1137
PREP_START = (540, 1140)
FORM_START = (540, 1580)
# 今日剩余次数右侧「+」（0/2 时仍可点，实测约 710,1110）
ADD_PLUS = (710, 1110)
# 购买弹窗右侧金色「确定」（取消在左，确定在右）
BUY_CONFIRM = (784, 1244)
# 返回箭头（过关斩将 / 征战列表 左上角，勿当作空白点）
UI_BACK = (80, 295)
# 准备页开始按钮合法 y 范围
PREP_START_Y_MIN, PREP_START_Y_MAX = 1080, 1220
FORM_START_Y_MIN = 1500
# 「获得奖励」弹层安全点击区（用户红框：中右上、左下、右下，绝不到左上返回）
GOT_REWARD_SAFE_TAPS = (
    (850, 520),
    (200, 1450),
    (850, 1450),
    (540, 800),
    (540, 1050),
    (700, 1300),
)


def _task_opt(key: str, default):
    meta = (config.get("tasks") or {}).get("guoguan") or {}
    return meta.get(key, default)


def _find(ctx: TaskContext, screen, name: str, threshold: float = 0.75):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold)
    except FileNotFoundError:
        return None


def _tap(ctx: TaskContext, xy: tuple[int, int]) -> None:
    ctx.device.tap(int(xy[0]), int(xy[1]))


# ------------------------------------------------------------------ #
# 页面识别（严格，优先级：战斗中 > 编队 > 领奖 > 准备页）
# ------------------------------------------------------------------ #
def _find_reward_button(ctx: TaskContext, screen=None):
    """「获取奖励/领取奖励」按钮。

    与「开始挑战」同为金按钮，必须用高阈值，否则会互串。
    真·获取奖励 live 约 0.99；准备页误匹配约 0.89。
    """
    screen = screen if screen is not None else ctx.screenshot()
    # 只用 tight 模板 + 高阈值（宽模板会和「开始挑战」金按钮互串）
    for name, thr in (
        ("guoguan_reward_tight", 0.93),
        ("guoguan_claim_tight", 0.93),
    ):
        hit = _find(ctx, screen, name, thr)
        if hit and PREP_START_Y_MIN <= hit.y <= PREP_START_Y_MAX + 40:
            return hit
    return None


def _has_reward(ctx: TaskContext, screen=None) -> bool:
    return _find_reward_button(ctx, screen) is not None


def _gray_start_hit(ctx: TaskContext, screen):
    """灰色「开始挑战」按钮（次数用尽时）。"""
    gray = _find(ctx, screen, "guoguan_start_gray_tight", 0.82) or _find(
        ctx, screen, "guoguan_start_gray", 0.80
    )
    if gray and 1050 <= gray.y <= 1450:
        return gray
    return None


def is_battle_detail(ctx: TaskContext, screen=None) -> bool:
    """是否误入战斗「详情」界面（有「下一战/x2」等，不应停留）。

    正确做法是留在过关斩将主界面等「战斗中」结束；详情页要返回。
    注意：本函数不能再调用 is_fighting / is_form_page（会循环）。
    """
    screen = screen if screen is not None else ctx.screenshot()
    if _has_reward(ctx, screen) or _is_got_reward_popup(ctx, screen):
        return False
    # 创建编队标题 → 不是详情
    if _find(ctx, screen, "guoguan_form_title", 0.80):
        return False
    # 主界面标志：大字「战斗中」→ 不是详情
    if _find(ctx, screen, "guoguan_fighting", 0.88):
        return False
    # 主界面「查看战斗」→ 不是详情
    view = _find(ctx, screen, "guoguan_view_battle_tight", 0.90) or _find(
        ctx, screen, "guoguan_view_battle", 0.93
    )
    if view and 1100 <= view.y <= 1350:
        return False
    # 准备页金/灰开始 → 不是详情
    gold = _find(ctx, screen, "guoguan_start_tight", 0.90)
    if gold and PREP_START_Y_MIN <= gold.y <= PREP_START_Y_MAX + 40:
        roi = screen[gold.y - 20 : gold.y + 20, gold.x - 60 : gold.x + 60]
        if roi.size and float(roi.mean()) >= 95:
            return False
    gray = _gray_start_hit(ctx, screen)
    if gray and gray.score >= 0.90:
        return False
    # 详情页：「下一战」按钮（右下）
    nxt = _find(ctx, screen, "guoguan_next_battle", 0.75)
    if nxt and nxt.y >= 1550 and nxt.x >= 600:
        return True
    # 兜底：有标题 + 右下「下一战」区域偏亮 + 无主界面按钮
    if not _find(ctx, screen, "guoguan_title", 0.72):
        return False
    roi = screen[1680:1820, 780:1040]
    if roi.size and float(roi.mean()) > 75:
        mid = screen[700:1200, 200:880]
        if mid.size and float(mid.mean()) > 45:
            return True
    return False


def leave_battle_detail(ctx: TaskContext) -> bool:
    """从战斗详情返回过关斩将主界面。只点返回，绝不点「下一战」。"""
    if not is_battle_detail(ctx):
        return True
    logger.info("检测到战斗详情，返回主界面等待（不点下一战/查看战斗）")
    for _ in range(4):
        if not is_battle_detail(ctx):
            return True
        # 只点左上返回
        ctx.device.tap(UI_BACK[0], UI_BACK[1])
        time.sleep(1.0)
        if (
            is_fighting(ctx)
            or _has_reward(ctx)
            or is_prep_page(ctx)
            or is_times_exhausted(ctx)
        ):
            logger.info("已回到过关斩将主界面")
            return True
    ok = not is_battle_detail(ctx)
    if not ok:
        logger.warning("未能离开战斗详情")
    return ok


def is_fighting(ctx: TaskContext, screen=None) -> bool:
    """过关斩将主界面「战斗中」（只认主界面，不认战斗详情）。

    准备页（含 0/2 灰按钮 / 金色开始挑战）可能误匹配「战斗中」，须排除。
    """
    screen = screen if screen is not None else ctx.screenshot()
    if _has_reward(ctx, screen) or _is_got_reward_popup(ctx, screen):
        return False
    # 战斗详情 ≠ 主界面等待
    if is_battle_detail(ctx, screen):
        return False
    # 灰按钮较高分 → 仍在准备页
    gray = _gray_start_hit(ctx, screen)
    if gray and gray.score >= 0.88:
        return False
    # 金色开始挑战高分+偏亮 → 准备页可开战，不是战斗中
    gold = _find(ctx, screen, "guoguan_start_tight", 0.90)
    if gold and PREP_START_Y_MIN <= gold.y <= PREP_START_Y_MAX + 40:
        roi = screen[gold.y - 20 : gold.y + 20, gold.x - 60 : gold.x + 60]
        if roi.size and float(roi.mean()) >= 95:
            return False
    # 主标志：大字「战斗中」（主界面）
    if _find(ctx, screen, "guoguan_fighting", 0.85):
        return True
    # 辅助：查看战斗按钮（只作识别，绝不点击）
    view = _find(ctx, screen, "guoguan_view_battle_tight", 0.92) or _find(
        ctx, screen, "guoguan_view_battle", 0.95
    )
    if view and 1180 <= view.y <= 1320:
        start = _find(ctx, screen, "guoguan_start_tight", 0.90)
        if start and PREP_START_Y_MIN <= start.y <= PREP_START_Y_MAX:
            if view.y > start.y + 60 and view.score >= start.score + 0.03:
                return True
        elif not start:
            return True
    return False


def is_form_page(ctx: TaskContext, screen=None) -> bool:
    """创建编队页：只认「创建编队」标题。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _has_reward(ctx, screen) or is_fighting(ctx, screen):
        return False
    hit = _find(ctx, screen, "guoguan_form_title", 0.80)
    if hit:
        logger.debug("识别到创建编队标题 @({},{}) score={:.3f}", hit.x, hit.y, hit.score)
        return True
    return False


def is_prep_page(ctx: TaskContext, screen=None) -> bool:
    """准备页：可点金色「开始挑战」（非战斗、非领奖、非编队、非次数用尽灰按钮）。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _has_reward(ctx, screen) or _is_got_reward_popup(ctx, screen):
        return False
    if is_fighting(ctx, screen):
        return False
    if is_form_page(ctx, screen):
        return False
    if is_times_exhausted(ctx, screen):
        return False
    hit = _find(ctx, screen, "guoguan_start_tight", 0.88) or _find(
        ctx, screen, "guoguan_start", 0.88
    )
    if not hit or not (PREP_START_Y_MIN <= hit.y <= PREP_START_Y_MAX):
        return False
    rw = _find_reward_button(ctx, screen)
    if rw and rw.score >= hit.score - 0.02:
        return False
    # 金色按钮应明显偏亮；灰色「开始挑战」偏暗
    roi = screen[hit.y - 20 : hit.y + 20, hit.x - 60 : hit.x + 60]
    if not roi.size or float(roi.mean()) < 95:
        return False
    return True


def is_times_exhausted(ctx: TaskContext, screen=None) -> bool:
    """今日免费次数用完：灰色「开始挑战」（0/2）。

    注意：不同账号/关卡按钮 y 可能在 1100~1400，不要卡死在金色准备页 y 带。
    灰模板阈值也不宜过高（跨界面约 0.80~0.90）。
    优先认灰按钮，避免「战斗中」模板误匹配挡住本判定。
    """
    screen = screen if screen is not None else ctx.screenshot()
    if _has_reward(ctx, screen) or _is_got_reward_popup(ctx, screen):
        return False
    if is_form_page(ctx, screen):
        return False
    gray = _gray_start_hit(ctx, screen)
    gold = _find(ctx, screen, "guoguan_start_tight", 0.88)
    if not gray:
        return False
    # 灰按钮区域应偏暗；金按钮明显更亮
    roi = screen[gray.y - 20 : gray.y + 20, gray.x - 60 : gray.x + 60]
    mean_b = float(roi.mean()) if roi.size else 255
    # 金按钮高分且明显更亮 → 还有次数，不是用尽
    if gold is not None and gold.score >= 0.92:
        gold_roi = screen[gold.y - 20 : gold.y + 20, gold.x - 60 : gold.x + 60]
        gold_mean = float(gold_roi.mean()) if gold_roi.size else 0
        if gold_mean >= 100 and gold.score >= gray.score + 0.03:
            return False
    # 高分灰按钮直接认（0/2 常见 score≈0.99）
    if gray.score >= 0.95:
        return True
    if gray.score >= 0.92 and (gold is None or gray.score >= gold.score + 0.04):
        return True
    if gold is None:
        if mean_b < 120 or gray.score >= 0.85:
            return True
        return False
    if gray.score >= gold.score + 0.04:
        return True
    if mean_b < 100 and gray.score >= gold.score - 0.02:
        return True
    return False


def _click_prep_start(ctx: TaskContext) -> bool:
    screen = ctx.screenshot()
    hit = _find(ctx, screen, "guoguan_start_tight", 0.75) or _find(
        ctx, screen, "guoguan_start", 0.75
    )
    if hit and PREP_START_Y_MIN <= hit.y <= PREP_START_Y_MAX:
        # 亮度校验：金色按钮区域应明显亮于暗背景
        roi = screen[hit.y - 25 : hit.y + 25, hit.x - 80 : hit.x + 80]
        bright = float(roi.mean()) if roi.size else 0
        if bright < 70:
            logger.warning(
                "准备页匹配点过暗 mean={:.1f} @({},{})，改用坐标 {}",
                bright,
                hit.x,
                hit.y,
                PREP_START,
            )
            _tap(ctx, PREP_START)
            return True
        logger.info(
            "① 点击准备页「开始挑战」@({},{}) bright={:.1f}", hit.x, hit.y, bright
        )
        _tap(ctx, (hit.x, hit.y))
        return True
    logger.info("① 点击准备页「开始挑战」坐标 {}", PREP_START)
    _tap(ctx, PREP_START)
    return True


def _click_form_start(ctx: TaskContext) -> bool:
    screen = ctx.screenshot()
    if not is_form_page(ctx, screen):
        logger.warning("未识别到创建编队标题，仍点编队开始坐标")
    hit = _find(ctx, screen, "guoguan_form_start_tight", 0.78) or _find(
        ctx, screen, "guoguan_form_start", 0.78
    )
    if hit and hit.y >= FORM_START_Y_MIN:
        logger.info("② 点击创建编队「开始挑战」@({},{})", hit.x, hit.y)
        _tap(ctx, (hit.x, hit.y))
        return True
    logger.info("② 点击创建编队「开始挑战」坐标 {}", FORM_START)
    _tap(ctx, FORM_START)
    return True


def _wait_form_page(ctx: TaskContext, timeout: float = 15.0) -> bool:
    """点完准备页后，等待「创建编队」标题出现。

    若已直接进入主界面「战斗中」，也视为开战成功（无需再点编队）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 误进详情则退回
        if is_battle_detail(ctx):
            leave_battle_detail(ctx)
        if is_form_page(ctx):
            return True
        if is_fighting(ctx):
            logger.info("未进编队页，但主界面已显示战斗中，视为已开战")
            return True
        if _has_reward(ctx):
            return True
        time.sleep(0.5)
    return False


def _start_two_step(ctx: TaskContext) -> tuple[bool, str]:
    """
    完整两步：
      必须点到准备页开始 → 等到创建编队 → 再点编队开始
    开战后只在主界面等待，绝不点「查看战斗」进详情。
    """
    # 误在详情：先回主界面
    if is_battle_detail(ctx):
        leave_battle_detail(ctx)

    screen = ctx.screenshot()

    # 已在主界面战斗中：无需再点
    if is_fighting(ctx, screen):
        logger.info("已在主界面战斗中，跳过开战点击")
        return True, "已在战斗中"

    # 已在编队：只需第二步
    if is_form_page(ctx, screen):
        logger.info("当前已是创建编队页，执行第②步")
        _click_form_start(ctx)
        time.sleep(1.5)
        if is_form_page(ctx):
            _click_form_start(ctx)
            time.sleep(1.2)
        # 若误进详情，退回主界面
        if is_battle_detail(ctx):
            leave_battle_detail(ctx)
        return True, "仅编队确认"

    # 必须在准备页做第①步
    if not is_prep_page(ctx, screen):
        for _ in range(6):
            time.sleep(0.8)
            if is_battle_detail(ctx):
                leave_battle_detail(ctx)
            screen = ctx.screenshot()
            if is_form_page(ctx, screen):
                return _start_two_step(ctx)
            if is_fighting(ctx, screen):
                return True, "已在战斗中"
            if is_prep_page(ctx, screen):
                break
            if _has_reward(ctx, screen):
                return False, "REWARD"
        else:
            return False, "既不在准备页也不在创建编队"

    # ①
    _click_prep_start(ctx)
    time.sleep(1.0)

    # 必须等到创建编队（或已直接进入主界面战斗中）
    logger.info("等待创建编队界面…")
    if not _wait_form_page(ctx, timeout=15.0):
        logger.warning("未出现创建编队，重试准备页开始挑战")
        if is_prep_page(ctx):
            _click_prep_start(ctx)
            time.sleep(1.0)
        if not _wait_form_page(ctx, timeout=10.0):
            return False, "点击准备页后未出现创建编队（第①步可能未生效）"

    # 已在战斗中则不必点编队
    if is_fighting(ctx) or _has_reward(ctx):
        return True, "两步点击完成（已开战）"

    if not is_form_page(ctx):
        # 可能已经开战
        if is_fighting(ctx):
            return True, "两步点击完成（已开战）"
        return False, "未确认创建编队"

    logger.info("已确认创建编队界面")
    # ②
    _click_form_start(ctx)
    time.sleep(1.3)
    if is_form_page(ctx):
        logger.info("编队仍在，再点一次第②步")
        _click_form_start(ctx)
        time.sleep(1.2)

    # 开战后若误进详情，立即退回主界面再等
    if is_battle_detail(ctx):
        leave_battle_detail(ctx)

    return True, "两步点击完成"


def _click_reward(ctx: TaskContext) -> None:
    """点击「获取奖励/领取奖励」。"""
    screen = ctx.screenshot()
    hit = _find_reward_button(ctx, screen)
    if hit:
        logger.info("④ 点击获取奖励 @({},{}) score={:.3f}", hit.x, hit.y, hit.score)
        _tap(ctx, (hit.x, hit.y))
    else:
        logger.info("④ 坐标点击获取奖励 {}", PREP_START)
        _tap(ctx, PREP_START)


def _is_got_reward_popup(ctx: TaskContext, screen=None) -> bool:
    """点击获取奖励后的「获得奖励」弹层（点空白关闭）。

    只认大字「获得奖励」；「点击任意区域关闭」与金按钮太像，不用。
    """
    screen = screen if screen is not None else ctx.screenshot()
    return _find(ctx, screen, "guoguan_got_reward", 0.85) is not None


def _still_on_guoguan(ctx: TaskContext, screen=None) -> bool:
    """是否仍在过关斩将相关界面（未误点返回退出）。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _find(ctx, screen, "guoguan_title", 0.75):
        return True
    if is_prep_page(ctx, screen) or is_form_page(ctx, screen):
        return True
    if is_fighting(ctx, screen) or _has_reward(ctx, screen):
        return True
    if _is_got_reward_popup(ctx, screen):
        return True
    return False


def _fast_tap(ctx: TaskContext, x: int, y: int) -> None:
    """快速点击（无随机抖动、短间隔），用于关弹层。"""
    # 硬性避开返回键热区
    if x < 160 and y < 380:
        logger.warning("拒绝点击返回热区 ({},{})，改点安全区", x, y)
        x, y = GOT_REWARD_SAFE_TAPS[0]
    ctx.device.shell(f"input tap {int(x)} {int(y)}")
    time.sleep(0.18)


def _dismiss_to_prep(ctx: TaskContext, timeout: float = 8.0) -> bool:
    """关闭「获得奖励」弹层：连点安全空白（用户红框），绝不点左上返回。

    为加速：先连点 3 下再截图判断，避免每次点击都截图拖慢。
    """
    deadline = time.time() + timeout
    i = 0
    while time.time() < deadline:
        # 快速连点 3 个安全区（少截图）
        for _ in range(3):
            pt = GOT_REWARD_SAFE_TAPS[i % len(GOT_REWARD_SAFE_TAPS)]
            logger.info("⑤ 点安全空白关闭「获得奖励」 {}", pt)
            _fast_tap(ctx, pt[0], pt[1])
            i += 1

        screen = ctx.screenshot()

        if is_times_exhausted(ctx, screen) and not _is_got_reward_popup(ctx, screen):
            logger.info("⑤ 已回到过关斩将页（次数用尽）")
            return True

        if is_prep_page(ctx, screen) and not _has_reward(ctx, screen):
            if not _is_got_reward_popup(ctx, screen):
                logger.info("⑤ 已回到过关斩将准备页，可继续下一场")
                return True

        if not _still_on_guoguan(ctx, screen):
            logger.warning("关闭弹层时离开了过关斩将（疑似误点返回）")
            return False

        if _has_reward(ctx, screen) and not _is_got_reward_popup(ctx, screen):
            _click_reward(ctx)
            time.sleep(0.25)
            continue

        if not _is_got_reward_popup(ctx, screen) and _still_on_guoguan(ctx, screen):
            # 弹层已消失
            logger.info("⑤ 获得奖励弹层已消失")
            return True

    screen = ctx.screenshot()
    if _still_on_guoguan(ctx, screen) and not _is_got_reward_popup(ctx, screen):
        logger.info("⑤ 弹层已关（超时兜底，仍在过关斩将）")
        return True
    logger.warning("关闭「获得奖励」弹层超时")
    return is_prep_page(ctx) or is_times_exhausted(ctx)


def _claim_reward_and_return(ctx: TaskContext) -> tuple[bool, str]:
    """获取奖励 → 安全快速点空白关闭获得奖励 → 留在过关斩将页。"""
    if not _has_reward(ctx) and not _is_got_reward_popup(ctx):
        if is_prep_page(ctx) or is_times_exhausted(ctx):
            return True, "已在过关斩将准备页"
        return False, "当前无获取奖励按钮"

    if _has_reward(ctx):
        _click_reward(ctx)
        time.sleep(0.35)

    ok = _dismiss_to_prep(ctx, timeout=8.0)
    if ok:
        return True, "已获取奖励并回到过关斩将页"
    if _still_on_guoguan(ctx):
        return True, "已获取奖励（仍在过关斩将内）"
    return False, "领奖后误退出过关斩将"


def _click_ui_back(ctx: TaskContext) -> None:
    """点左上角返回（仅用于任务正常收尾）。

    注意：不能用 _fast_tap——它会拦截返回热区并改点安全空白。
    """
    screen = ctx.screenshot()
    hit = _find(ctx, screen, "ui_back", 0.75)
    if hit and hit.x < 200 and hit.y < 400:
        logger.info("点击返回 @({},{})", hit.x, hit.y)
        _tap(ctx, (hit.x, hit.y))
    else:
        # 与 navigation.ui_back 一致：略偏左更稳
        logger.info("坐标点击返回 {}", UI_BACK)
        ctx.device.tap(UI_BACK[0], UI_BACK[1])
    time.sleep(0.8)


def exit_guoguan_to_main(ctx: TaskContext) -> None:
    """任务结束：过关斩将 → 返回 → 征战列表 → 返回 → 主城。"""
    logger.info("收尾：返回主城")
    # 公告 / 系统确定弹窗优先关掉，否则点不到返回
    dismiss_confirm_dialogs(ctx, max_rounds=3)
    # 若还在获得奖励弹层，先关掉
    for _ in range(6):
        if not _is_got_reward_popup(ctx) and not _has_reward(ctx):
            break
        if _has_reward(ctx):
            _click_reward(ctx)
            time.sleep(0.3)
        _dismiss_to_prep(ctx, timeout=3.0)

    # 优先复用 navigation 的稳定返回（坐标 + 模板双保险）
    from src.tasks.navigation import ui_back, is_main_city, is_war_list, has_confirm_dialog

    # 过关斩将页返回 → 征战
    for _ in range(5):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            logger.info("已回到主城")
            return
        if has_confirm_dialog(ctx, screen):
            dismiss_confirm_dialogs(ctx, max_rounds=2)
            continue
        if is_war_list(ctx, screen) or _find(ctx, screen, "war_title", 0.75):
            break
        if (
            _find(ctx, screen, "guoguan_title", 0.72)
            or is_times_exhausted(ctx, screen)
            or is_prep_page(ctx, screen)
            or _still_on_guoguan(ctx, screen)
        ):
            ui_back(ctx)
            continue
        # 未知但仍在子页：也点返回
        ui_back(ctx)

    # 征战列表返回 → 主城
    for _ in range(5):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen) or _find(ctx, screen, "nav_fief", 0.72):
            logger.info("已回到主城")
            return
        if has_confirm_dialog(ctx, screen):
            dismiss_confirm_dialogs(ctx, max_rounds=2)
            continue
        if is_war_list(ctx, screen) or _find(ctx, screen, "war_title", 0.72):
            ui_back(ctx)
            continue
        ui_back(ctx)
    ensure_main_city(ctx)
    logger.info("收尾结束")


def _buy_extra_once(ctx: TaskContext) -> bool:
    """免费用完后：点「+」→ 弹窗点「确定」→ 获得 1 次（今日第 3 轮）。

    流程对应界面：
      1) 今日剩余次数 0/2 旁的金色 +
      2) 「购买1个挑战次数 / 消耗 200 元宝」弹窗右侧确定
    成功后回到过关斩将准备页，金色「开始挑战」可点，再走正常两步开战。
    """
    # 注意：购买弹窗本身带「确定」，此处不要用 dismiss_confirm_dialogs 瞎点
    if not is_guoguan_page(ctx) and not open_guoguan(ctx):
        return False

    # 若购买弹窗已打开，直接点确定
    screen = ctx.screenshot()
    conf0 = _find(ctx, screen, "guoguan_buy_confirm", 0.70)
    title0 = _find(ctx, screen, "guoguan_buy_title", 0.68)
    if conf0 or title0:
        logger.info("购买弹窗已在，直接确认")
    else:
        plus = _find(ctx, screen, "guoguan_add", 0.72)
        if plus and 650 <= plus.x <= 850 and 1000 <= plus.y <= 1200:
            logger.info("① 点击次数旁「+」@({},{}) score={:.3f}", plus.x, plus.y, plus.score)
            _tap(ctx, (plus.x, plus.y))
        else:
            logger.info("① 坐标点击次数旁「+」 {}", ADD_PLUS)
            _tap(ctx, ADD_PLUS)
        time.sleep(1.5)

    for _ in range(14):
        screen = ctx.screenshot()
        # 优先认购买专用确定（右侧金色），避免点到左侧「取消」
        conf = _find(ctx, screen, "guoguan_buy_confirm", 0.68)
        title = _find(ctx, screen, "guoguan_buy_title", 0.65)
        # 仅当标题/购买确定模板命中时，才允许用通用确定（防误点底部其它按钮）
        if conf is None and title is not None:
            for name, thr in (("dialog_confirm_tight", 0.75), ("dialog_confirm", 0.74)):
                cand = _find(ctx, screen, name, thr)
                if cand and cand.x >= 550 and 1100 <= cand.y <= 1400:
                    conf = cand
                    break

        if conf or title:
            if conf and conf.x >= 500:
                logger.info(
                    "② 购买弹窗点击「确定」@({},{}) score={:.3f}",
                    conf.x,
                    conf.y,
                    conf.score,
                )
                _tap(ctx, (conf.x, conf.y))
            else:
                logger.info("② 购买弹窗坐标「确定」 {}", BUY_CONFIRM)
                _tap(ctx, BUY_CONFIRM)
            time.sleep(1.4)
            dismiss_confirm_dialogs(ctx, max_rounds=1)
            # 买成功后应出现金色开始挑战（不再 0/2 灰）
            if is_prep_page(ctx) or not is_times_exhausted(ctx):
                logger.info("购买成功，可开始挑战（今日购买场）")
                return True
            # 可能还在弹窗
            continue

        time.sleep(0.35)

    logger.warning("未识别购买弹窗，坐标点「确定」 {}", BUY_CONFIRM)
    _tap(ctx, BUY_CONFIRM)
    time.sleep(1.2)
    dismiss_confirm_dialogs(ctx, max_rounds=1)
    return not is_times_exhausted(ctx) or is_prep_page(ctx)


def _wait_battle_and_claim(
    ctx: TaskContext, battle_timeout: float, assume_started: bool = False
) -> tuple[bool, str]:
    """开战后（免费场/购买场相同）只在过关斩将主界面等待：

    - 主界面「战斗中」→ 只等，**绝不点「查看战斗」**
    - 若误进战斗详情（「下一战」）→ 点返回回主界面，继续等
    - 主界面「获取奖励」→ 点击 → 安全空白关闭获得奖励
    """
    logger.info(
        "③ 主界面等待战斗结束→获取奖励（最多 {} 秒；不点查看战斗/下一战）…",
        int(battle_timeout),
    )
    deadline = time.time() + battle_timeout
    saw_fighting = bool(assume_started)
    last_log = 0.0
    prep_streak = 0

    # 开局若在详情，先退回
    if is_battle_detail(ctx):
        leave_battle_detail(ctx)
        saw_fighting = True

    while time.time() < deadline:
        time.sleep(2.5)
        # 战斗等待中也可能弹出国家公告
        if dismiss_confirm_dialogs(ctx, max_rounds=1):
            continue

        # 误进详情：立即返回主界面（不点下一战）
        if is_battle_detail(ctx):
            leave_battle_detail(ctx)
            saw_fighting = True
            prep_streak = 0
            continue

        screen = ctx.screenshot()

        reward = _has_reward(ctx, screen)
        got = _is_got_reward_popup(ctx, screen)
        fighting = is_fighting(ctx, screen)
        form = is_form_page(ctx, screen)
        prep = is_prep_page(ctx, screen)
        zero = is_times_exhausted(ctx, screen)
        detail = is_battle_detail(ctx, screen)

        now = time.time()
        if now - last_log > 15:
            logger.info(
                "轮询: 领奖={} 获得弹层={} 主界面战斗中={} 详情={} 编队={} 准备页={} 次数尽={}",
                reward,
                got,
                fighting,
                detail,
                form,
                prep,
                zero,
            )
            last_log = now

        if got:
            logger.info("检测到「获得奖励」弹层，安全点关闭")
            _dismiss_to_prep(ctx, timeout=6.0)
            if is_prep_page(ctx) or is_times_exhausted(ctx):
                return True, "已获取奖励并关闭弹层"
            continue

        if reward:
            logger.info("检测到「获取奖励」（主界面）")
            ok, msg = _claim_reward_and_return(ctx)
            return ok, msg

        if fighting:
            # 主界面战斗中：只等，不点任何战斗按钮
            saw_fighting = True
            prep_streak = 0
            continue

        if form:
            logger.info("等待中仍见创建编队，补点第②步")
            _click_form_start(ctx)
            time.sleep(1.0)
            if is_battle_detail(ctx):
                leave_battle_detail(ctx)
            prep_streak = 0
            continue

        if zero:
            logger.info("次数已用尽")
            return True, "战斗流程结束（次数用尽）"

        if prep:
            prep_streak += 1
            if saw_fighting and prep_streak >= 2:
                logger.info("战斗结束且稳定回到准备页")
                return True, "战斗结束（已回准备页）"
            if assume_started and not saw_fighting and prep_streak >= 8:
                logger.warning("开战后长时间仍为准备页，可能未进入战斗")
                return False, "开战后未进入战斗（仍停在准备页）"
            continue

        prep_streak = 0
        # 其它未知界面：若已开战则继续等（不乱点）
        if saw_fighting or assume_started:
            continue

    return False, f"等待获取奖励超时（>{int(battle_timeout)}s）"


def _one_run(ctx: TaskContext, battle_timeout: float) -> tuple[bool, str]:
    """单场：开战 → 主界面等待 → 领奖。免费场与购买场共用。"""
    # 误在详情则先回主界面
    if is_battle_detail(ctx):
        leave_battle_detail(ctx)

    if not is_guoguan_page(ctx):
        if not open_guoguan(ctx):
            return False, "不在过关斩将界面"

    screen = ctx.screenshot()

    if _is_got_reward_popup(ctx, screen):
        logger.info("当前有「获得奖励」弹层")
        _dismiss_to_prep(ctx, timeout=6.0)
        screen = ctx.screenshot()

    if _has_reward(ctx, screen):
        logger.info("当前已是获取奖励界面")
        return _claim_reward_and_return(ctx)

    if is_fighting(ctx, screen):
        logger.info("当前主界面已在战斗中，等待结束（不点查看战斗）")
        return _wait_battle_and_claim(ctx, battle_timeout, assume_started=True)

    if is_times_exhausted(ctx, screen):
        return False, "无开始挑战（免费次数可能已用完）"

    ok, msg = _start_two_step(ctx)
    if msg == "REWARD":
        return _claim_reward_and_return(ctx)
    if not ok:
        return False, msg

    time.sleep(1.2)
    # 开战后再确认不在详情
    if is_battle_detail(ctx):
        leave_battle_detail(ctx)

    if is_fighting(ctx):
        logger.info("已确认主界面进入战斗中，开始等待")
    elif _has_reward(ctx):
        logger.info("开战流程后直接进入获取奖励")
        return _claim_reward_and_return(ctx)
    else:
        logger.info("两步已完成，主界面等待（assume_started，不点查看战斗）")

    return _wait_battle_and_claim(ctx, battle_timeout, assume_started=True)


class GuoguanTask(BaseTask):
    id = "guoguan"
    name = "过关斩将设置"
    description = "大开关=打免费2次；小开关 buy_extra=花元宝买第3次"
    required_templates = [
        "guoguan_start_tight",
        "guoguan_form_title",
        "war_title",
        "guoguan_entry_title",
    ]

    def execute(self, ctx: TaskContext) -> TaskResult:
        max_runs = int(_task_opt("max_runs", 2) or 2)
        buy_extra = bool(_task_opt("buy_extra", False))
        battle_timeout = float(_task_opt("battle_timeout", 900) or 900)

        # 任意时刻都可能被国家公告等挡住
        dismiss_confirm_dialogs(ctx, max_rounds=3)

        if not open_guoguan(ctx):
            exit_guoguan_to_main(ctx)
            return TaskResult(TaskStatus.FAILED, "无法进入过关斩将")

        done = 0
        messages: list[str] = []

        def _finish(msg: str, status: TaskStatus = TaskStatus.SUCCESS) -> TaskResult:
            messages.append(msg)
            exit_guoguan_to_main(ctx)
            return TaskResult(
                status,
                f"过关斩将完成 {done} 轮；" + "；".join(messages),
            )

        for i in range(max_runs):
            logger.info(
                "过关斩将 免费 {}/{}（buy_extra={}）", i + 1, max_runs, buy_extra
            )

            dismiss_confirm_dialogs(ctx, max_rounds=2)

            if not _still_on_guoguan(ctx):
                logger.warning("不在过关斩将内，重新进入")
                if not open_guoguan(ctx):
                    return _finish(f"[免费{i+1}] 无法回到过关斩将", TaskStatus.FAILED)

            # 先处理遗留弹层/领奖
            if _is_got_reward_popup(ctx):
                _dismiss_to_prep(ctx, timeout=6.0)
            if _has_reward(ctx):
                ok, msg = _claim_reward_and_return(ctx)
                messages.append(f"[领奖] {msg}")

            screen = ctx.screenshot()
            logger.info(
                "页面: 准备页={} 次数用尽={} 战斗中={} 领奖={} 获得弹层={}",
                is_prep_page(ctx, screen),
                is_times_exhausted(ctx, screen),
                is_fighting(ctx, screen),
                _has_reward(ctx, screen),
                _is_got_reward_popup(ctx, screen),
            )

            # 今日免费次数用完
            # buy_extra=关 → 直接成功返回主城
            # buy_extra=开 → 点 + → 确定 → 正常打第 3 轮（购买场）
            if is_times_exhausted(ctx, screen):
                logger.info("检测到今日免费次数已用完（0/2）")
                if buy_extra:
                    logger.info("buy_extra=开：购买 1 次后走正常过关斩将流程（今日第3轮）")
                    if _buy_extra_once(ctx):
                        messages.append("[购买] 已点+并确定（200元宝）")
                        ok, msg = _one_run(ctx, battle_timeout)
                        messages.append(f"[购买场/第3轮] {msg}")
                        if ok:
                            done += 1
                        else:
                            return _finish(f"购买场失败: {msg}", TaskStatus.FAILED)
                    else:
                        messages.append("[购买] 失败（+ 或确定未点上）")
                        return _finish("购买额外次数失败", TaskStatus.FAILED)
                    return _finish("免费2次用尽，已完成购买场")
                messages.append("[购买] buy_extra=关，停止任务")
                return _finish("免费次数用尽，默认完成")

            if is_fighting(ctx, screen):
                ok, msg = _wait_battle_and_claim(ctx, battle_timeout)
                messages.append(f"[免费{i+1}/等待] {msg}")
                if ok:
                    done += 1
                    continue
                return _finish(f"等待战斗失败: {msg}", TaskStatus.FAILED)

            ok, msg = _one_run(ctx, battle_timeout)
            messages.append(f"[免费{i+1}] {msg}")
            if ok:
                done += 1
                continue

            # 开战失败：再判一次是否次数用尽
            if is_times_exhausted(ctx) or "无开始" in msg or "既不在准备页" in msg:
                if buy_extra and not is_times_exhausted(ctx):
                    # 界面异常，尝试重进
                    if open_guoguan(ctx):
                        continue
                if is_times_exhausted(ctx) or "无开始" in msg:
                    if buy_extra:
                        if _buy_extra_once(ctx):
                            messages.append("[购买] + 并确定")
                            ok2, msg2 = _one_run(ctx, battle_timeout)
                            messages.append(f"[购买场] {msg2}")
                            if ok2:
                                done += 1
                        return _finish("免费用尽后已尝试购买")
                    messages.append("[购买] buy_extra=关，停止")
                    return _finish("免费次数用尽，默认完成")
            return _finish(f"中止: {msg}", TaskStatus.FAILED)

        # 打满 max_runs 后
        if buy_extra and not is_times_exhausted(ctx):
            # 若还有次数（不常见），不再强行买
            pass
        elif buy_extra and is_times_exhausted(ctx):
            logger.info("免费场打完且次数用尽，buy_extra=开，购买 1 次")
            if _buy_extra_once(ctx):
                messages.append("[购买] + 并确定")
                ok, msg = _one_run(ctx, battle_timeout)
                messages.append(f"[购买场] {msg}")
                if ok:
                    done += 1
        else:
            messages.append("[购买] buy_extra=关，跳过")

        return _finish("任务结束")
