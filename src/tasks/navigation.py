"""主城导航与通用弹窗处理。

分辨率基准：1080 x 1920（竖屏）。

经验：
- 邮件/更多弹窗的 X 按钮经常点不中，侧边空白 (30,500) 更稳
- 「更多」按钮受周边 HUD 影响，模板易失效，坐标 (985,1625) 更稳
- 不要在已是主城时反复点底栏「封地」，会打开子界面挡住更多
"""

from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from src.session.activity_popup import ActivityPopupDetector
from src.tasks.base import TaskContext


# 关闭弹层：优先侧边（实测比顶部空白、X 按钮更稳）
CLOSE_POINTS = (
    (30, 500),
    (50, 900),
    (1030, 900),
    (540, 160),
)

MORE_FALLBACK_POINTS = (
    (985, 1625),
    (1000, 1610),
    (970, 1640),
)

MAIL_ICON_FALLBACK = (925, 785)
# 「更多」弹窗内邮件图标的安全搜索区域。限制区域后可以适当放宽模板
# 阈值，不会把主城其它图标误判成邮件入口。
MAIL_ENTRY_REGION = (700, 620, 350, 380)
MAIL_ENTRY_POINTS = (
    (925, 785),
    (920, 800),
    (930, 790),
)

# 底栏「征战」坐标（1080x1920）
NAV_WAR_FALLBACK = (420, 1820)
NAV_FIEF_FALLBACK = (80, 1820)
# 过关斩将入口横幅 / 开始挑战 / 加次数
GUOGUAN_ENTRY_FALLBACK = (540, 550)
GUOGUAN_START_FALLBACK = (540, 1260)
GUOGUAN_ADD_FALLBACK = (760, 1140)
UI_BACK_FALLBACK = (50, 290)  # 略偏左，中心点有时点不中
HIGHLIGHT_CLOSE_POINT = (30, 500)
HIGHLIGHT_TEMPLATE_NAMES = (
    "startup_highlight_close_hint_reward",
    "startup_highlight_close_hint",
)


def _find_on(
    screen,
    ctx: TaskContext,
    name: str,
    threshold: float = 0.78,
    region=None,
):
    try:
        return ctx.matcher.find(screen, name, threshold=threshold, region=region)
    except FileNotFoundError:
        # 可选模板（如 guoguan_reward）首次运行前不存在，静默跳过
        return None


def _find(ctx: TaskContext, name: str, threshold: float = 0.78):
    return _find_on(ctx.screenshot(), ctx, name, threshold=threshold)


def is_mail_open(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find_on(screen, ctx, "mail_title", threshold=0.82) is not None


def is_more_open(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    return _find_on(screen, ctx, "more_title", threshold=0.82) is not None


def is_main_city(ctx: TaskContext, screen=None) -> bool:
    """底栏可见且无邮件/更多弹窗。"""
    screen = screen if screen is not None else ctx.screenshot()
    if is_more_open(ctx, screen) or is_mail_open(ctx, screen):
        return False
    return _find_on(screen, ctx, "nav_fief", threshold=0.78) is not None


def tap_blank(ctx: TaskContext, point: Optional[tuple[int, int]] = None) -> None:
    x, y = point or CLOSE_POINTS[0]
    ctx.device.tap(x, y)


def dismiss_popup(ctx: TaskContext) -> None:
    """用侧边点击关掉当前弹层。"""
    tap_blank(ctx, CLOSE_POINTS[0])
    time.sleep(0.7)


# 通用「确定」弹窗（国家公告、系统提示等）—— 任何任务都可能被挡住
DIALOG_CONFIRM_FALLBACK = (540, 1305)
DIALOG_CONFIRM_TEMPLATES = (
    ("dialog_confirm_tight", 0.82),
    ("dialog_confirm", 0.80),
)
DIALOG_TITLE_TEMPLATES = (
    ("dialog_nation_title", 0.78),
)


def has_confirm_dialog(ctx: TaskContext, screen=None) -> bool:
    """是否有带「确定」的系统/公告弹窗。"""
    screen = screen if screen is not None else ctx.screenshot()
    for name, thr in DIALOG_TITLE_TEMPLATES:
        if _find_on(screen, ctx, name, thr):
            return True
    for name, thr in DIALOG_CONFIRM_TEMPLATES:
        hit = _find_on(screen, ctx, name, thr)
        # 弹窗确定通常在屏幕中下部
        if hit and 1050 <= hit.y <= 1500 and 250 <= hit.x <= 850:
            return True
    return False


def dismiss_highlight_popup(ctx: TaskContext, screen=None) -> bool:
    """仅在命中“点击任意区域关闭”提示时点击安全空白。"""
    screen = screen if screen is not None else ctx.screenshot()
    if getattr(ctx.matcher, "template_dir", None) is not None:
        blocker_status = ActivityPopupDetector(ctx.matcher).business_blocker_status(screen)
        if blocker_status is not False:
            logger.debug("business popup blocks legacy highlight dismissal")
            return False

    hit = None
    hit_name = None
    for name in HIGHLIGHT_TEMPLATE_NAMES:
        hit = _find_on(screen, ctx, name, threshold=0.78)
        if hit is not None:
            hit_name = name
            break
    if hit is None:
        return False

    logger.info(
        "关闭高亮弹窗，点击安全空白 @({}, {}) score={:.3f}",
        HIGHLIGHT_CLOSE_POINT[0],
        HIGHLIGHT_CLOSE_POINT[1],
        hit.score,
    )
    logger.debug("高亮提示模板: {}", hit_name)
    ctx.device.tap(*HIGHLIGHT_CLOSE_POINT)
    time.sleep(0.7)
    return True


def dismiss_activity_popups(
    ctx: TaskContext,
    max_rounds: int = 3,
    detector: ActivityPopupDetector | None = None,
) -> int:
    """Close only positively identified safe activity/guide overlays.

    The detector must identify the overlay before the fixed safe point is used.
    A fresh screenshot is taken after every tap so consecutive pages are handled
    one at a time and the bounded limit cannot turn into an unbounded loop.
    """
    if max_rounds < 0:
        raise ValueError("max_rounds must be non-negative")

    popup_detector = detector or ActivityPopupDetector(ctx.matcher)
    closed = 0
    while True:
        screen = ctx.screenshot()
        try:
            match = popup_detector.detect(screen)
        except Exception as exc:  # noqa: BLE001
            logger.debug("safe activity popup detection failed: {}", exc)
            return closed

        if match is None:
            return closed
        if closed >= max_rounds:
            logger.warning(
                "safe activity popup dismissal reached limit {}/{}; leaving overlay untouched",
                closed,
                max_rounds,
            )
            return closed

        ctx.device.tap(*HIGHLIGHT_CLOSE_POINT)
        closed += 1
        logger.info(
            "closed safe activity popup source={} reason={} score={:.3f} count={}/{}",
            match.source,
            match.reason,
            match.confidence,
            closed,
            max_rounds,
        )
        time.sleep(0.7)


def dismiss_confirm_dialogs(ctx: TaskContext, max_rounds: int = 4) -> int:
    """关闭「国家公告 / 系统提示」等带金色「确定」的弹窗。

    任何功能流程都可能被公告打断；在导航、开战、收尾前都应调用。
    返回实际关掉的次数。

    注意：购买次数弹窗也有「确定」，应优先点到匹配位置，
    禁止在未匹配时乱点屏幕中部（会点空/点到取消区）。
    """
    closed = 0
    for _ in range(max_rounds):
        screen = ctx.screenshot()

        # 若是「购买次数」弹窗，交给 guoguan 购买逻辑处理，这里不瞎点
        buy_title = _find_on(screen, ctx, "guoguan_buy_title", 0.70)
        buy_conf = _find_on(screen, ctx, "guoguan_buy_confirm", 0.72)
        if buy_title or (buy_conf and buy_conf.x >= 550):
            logger.debug("检测到购买次数弹窗，跳过通用关弹窗")
            break

        if dismiss_highlight_popup(ctx, screen):
            closed += 1
            continue

        activity_closed = dismiss_activity_popups(ctx, max_rounds=1)
        if activity_closed:
            closed += activity_closed
            continue

        hit = None
        # 先高阈值，再略放宽
        for thr_delta in (0.0, -0.05):
            for name, thr in DIALOG_CONFIRM_TEMPLATES:
                cand = _find_on(screen, ctx, name, thr + thr_delta)
                if cand and 1050 <= cand.y <= 1500 and 300 <= cand.x <= 900:
                    hit = cand
                    break
            if hit:
                break

        # 仅标题命中时，用右侧确定坐标（国家公告确定偏中下）
        if hit is None and has_confirm_dialog(ctx, screen):
            # 有标题但没匹配到确定按钮：才用兜底坐标
            logger.info("坐标点击弹窗「确定」 {}", DIALOG_CONFIRM_FALLBACK)
            ctx.device.tap(*DIALOG_CONFIRM_FALLBACK)
            closed += 1
            time.sleep(0.9)
            continue

        if hit is None:
            break

        logger.info(
            "关闭弹窗「确定」@({},{}) score={:.3f} [{}]",
            hit.x,
            hit.y,
            hit.score,
            hit.name,
        )
        ctx.device.tap(hit.x, hit.y)
        closed += 1
        time.sleep(0.9)
    if closed:
        logger.info("已关闭 {} 个确定类弹窗", closed)
    return closed


def dismiss_command_order_popups(
    ctx: TaskContext,
    max_rounds: int = 1,
    detector: ActivityPopupDetector | None = None,
    screen=None,
) -> int:
    """Dismiss command-order overlays that may appear during any task.

    Only the dedicated command-order detector is used here.  This prevents a
    task-owned purchase/reward dialog from being closed by the global safety
    hook.  The caller may provide its already captured screen to avoid a
    recursive screenshot while TaskContext is performing the hook.
    """
    if max_rounds < 0:
        raise ValueError("max_rounds must be non-negative")

    popup_detector = detector or ActivityPopupDetector(ctx.matcher)
    closed = 0
    pending_screen = screen
    while closed < max_rounds:
        current = pending_screen if pending_screen is not None else ctx.screenshot()
        pending_screen = None
        try:
            match = popup_detector.detect_command_order(current)
        except Exception as exc:  # noqa: BLE001
            logger.debug("命令弹窗检测失败: {}", exc)
            return closed

        if match is None:
            return closed

        ctx.device.tap(*HIGHLIGHT_CLOSE_POINT)
        closed += 1
        logger.info(
            "关闭命令弹窗 source={} reason={} score={:.3f} count={}/{}",
            match.source,
            match.reason,
            match.confidence,
            closed,
            max_rounds,
        )
        time.sleep(0.7)
    return closed


def close_overlays(ctx: TaskContext, max_rounds: int = 5) -> None:
    for i in range(max_rounds):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return

        # 优先：国家公告 / 系统「确定」弹窗（会挡住返回与所有操作）
        if has_confirm_dialog(ctx, screen):
            dismiss_confirm_dialogs(ctx, max_rounds=2)
            continue

        if is_mail_open(ctx, screen) or is_more_open(ctx, screen):
            logger.debug("关闭弹层 round={} point={}", i, CLOSE_POINTS[i % len(CLOSE_POINTS)])
            # 先试关闭模板，再侧边点击
            if is_mail_open(ctx, screen):
                ctx.tap_template("mail_close", threshold=0.75)
            if is_more_open(ctx, screen):
                ctx.tap_template("more_close", threshold=0.75)
            tap_blank(ctx, CLOSE_POINTS[i % len(CLOSE_POINTS)])
            time.sleep(0.75)
            continue

        # 未知遮挡：先试确定，再侧边
        if dismiss_confirm_dialogs(ctx, max_rounds=1):
            continue
        tap_blank(ctx, CLOSE_POINTS[i % len(CLOSE_POINTS)])
        time.sleep(0.5)


def ensure_main_city(ctx: TaskContext, retries: int = 5) -> bool:
    for _ in range(retries):
        if is_main_city(ctx):
            return True
        close_overlays(ctx, max_rounds=4)
        time.sleep(0.25)
    ok = is_main_city(ctx)
    if not ok:
        logger.warning("未能确认回到主城（可能仍有遮挡）")
    return ok


def open_more_menu(ctx: TaskContext) -> bool:
    """主城 → 更多。优先坐标（模板不稳定）。"""
    if is_more_open(ctx):
        return True

    ensure_main_city(ctx)

    # 1) 模板
    for name in ("btn_more", "btn_more_wide"):
        if ctx.wait_and_tap(name, retries=1, interval=0.5, threshold=0.70):
            time.sleep(0.9)
            if is_more_open(ctx):
                return True

    # 2) 坐标兜底（主路径）
    logger.info("使用坐标打开「更多」")
    for x, y in MORE_FALLBACK_POINTS:
        # 若被遮挡先侧边点一下
        if is_mail_open(ctx) or is_more_open(ctx):
            break
        ctx.device.tap(x, y)
        time.sleep(1.0)
        if is_more_open(ctx):
            return True

    return is_more_open(ctx)


def open_mail(ctx: TaskContext) -> bool:
    """主城 → 更多 → 邮件。"""
    if is_mail_open(ctx):
        return True

    if not open_more_menu(ctx):
        logger.error("无法打开「更多」菜单")
        return False

    def wait_mail_open(timeout: float = 3.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_mail_open(ctx):
                return True
            time.sleep(0.25)
        return is_mail_open(ctx)

    # 更多弹窗的邮件图标在页面加载/动画期间模板分数会明显下降。
    # 在已确认的邮件区域内，逐步放宽阈值，并在每次点击后等待页面完成跳转。
    for name in ("btn_mail_icon", "btn_mail"):
        for threshold in (0.66, 0.56, 0.48):
            for _ in range(2):
                screen = ctx.screenshot()
                if is_mail_open(ctx, screen):
                    return True
                hit = _find_on(
                    screen,
                    ctx,
                    name,
                    threshold=threshold,
                    region=MAIL_ENTRY_REGION,
                )
                if hit:
                    logger.info(
                        "点击邮件入口模板 {} @({},{}) score={:.3f}",
                        name,
                        hit.x,
                        hit.y,
                        hit.score,
                    )
                    ctx.device.tap(hit.x, hit.y)
                    if wait_mail_open(timeout=3.5):
                        return True
                time.sleep(0.45)

    # 模板仍未稳定时，邮件入口坐标是固定的；多点仅用于覆盖图标边缘/动画偏移。
    logger.info("邮件入口模板未确认，使用坐标尝试打开「邮件」")
    for point in MAIL_ENTRY_POINTS:
        if not is_more_open(ctx):
            break
        ctx.device.tap(*point)
        if wait_mail_open(timeout=3.8):
            return True

    return is_mail_open(ctx)


# ------------------------------------------------------------------ #
# 征战 / 过关斩将
# ------------------------------------------------------------------ #
def is_war_list(ctx: TaskContext, screen=None) -> bool:
    screen = screen if screen is not None else ctx.screenshot()
    if _find_on(screen, ctx, "war_title", threshold=0.75):
        return True
    # 列表页常有过关斩将入口横幅
    if _find_on(screen, ctx, "guoguan_entry_title", threshold=0.78):
        # 详情页也有「过关斩将」标题，需排除详情
        if not _find_on(screen, ctx, "guoguan_start_tight", threshold=0.78):
            if not _find_on(screen, ctx, "guoguan_start", threshold=0.78):
                return True
    return False


def is_guoguan_page(ctx: TaskContext, screen=None) -> bool:
    """过关斩将详情页（有标题或开始挑战按钮）。"""
    screen = screen if screen is not None else ctx.screenshot()
    if _find_on(screen, ctx, "guoguan_title", threshold=0.8):
        return True
    if _find_on(screen, ctx, "guoguan_start_tight", threshold=0.78):
        return True
    if _find_on(screen, ctx, "guoguan_start", threshold=0.78):
        return True
    # 领取奖励按钮（若已采集）
    if _find_on(screen, ctx, "guoguan_reward", threshold=0.78):
        return True
    return False


def ui_back(ctx: TaskContext) -> None:
    # 返回前先清掉公告类弹窗，否则点不到左上角返回
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    # 优先固定偏左坐标（模板中心点偶发点不中）
    ctx.device.tap(*UI_BACK_FALLBACK)
    time.sleep(1.0)
    # 若模板能点到再补一次
    ctx.tap_template("ui_back", threshold=0.8)
    time.sleep(0.5)


def open_war_list(ctx: TaskContext) -> bool:
    """主城底栏 → 征战列表。"""
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    if is_war_list(ctx):
        return True
    if is_guoguan_page(ctx):
        ui_back(ctx)
        if is_war_list(ctx):
            return True

    ensure_main_city(ctx)
    dismiss_confirm_dialogs(ctx, max_rounds=1)

    if ctx.wait_and_tap("nav_war", retries=2, interval=0.6, threshold=0.72):
        time.sleep(1.1)
        if is_war_list(ctx):
            return True

    logger.info("使用坐标打开「征战」")
    ctx.device.tap(*NAV_WAR_FALLBACK)
    time.sleep(1.2)
    return is_war_list(ctx)


def open_guoguan(ctx: TaskContext) -> bool:
    """主城 → 征战 → 过关斩将详情。"""
    dismiss_confirm_dialogs(ctx, max_rounds=2)
    if is_guoguan_page(ctx):
        return True

    if not open_war_list(ctx):
        logger.error("无法打开征战列表")
        return False

    dismiss_confirm_dialogs(ctx, max_rounds=1)
    for name in ("guoguan_entry_title", "guoguan_entry"):
        if ctx.wait_and_tap(name, retries=2, interval=0.6, threshold=0.72):
            time.sleep(1.2)
            dismiss_confirm_dialogs(ctx, max_rounds=1)
            if is_guoguan_page(ctx):
                return True

    logger.info("使用坐标进入「过关斩将」")
    ctx.device.tap(*GUOGUAN_ENTRY_FALLBACK)
    time.sleep(1.2)
    dismiss_confirm_dialogs(ctx, max_rounds=1)
    return is_guoguan_page(ctx)


def leave_to_main_from_war(ctx: TaskContext) -> None:
    """从征战/过关斩将尽量退回主城。"""
    for _ in range(5):
        screen = ctx.screenshot()
        if is_main_city(ctx, screen):
            return
        if has_confirm_dialog(ctx, screen):
            dismiss_confirm_dialogs(ctx, max_rounds=2)
            continue
        if is_guoguan_page(ctx, screen) or is_war_list(ctx, screen):
            ui_back(ctx)
            continue
        if is_mail_open(ctx, screen) or is_more_open(ctx, screen):
            close_overlays(ctx, max_rounds=2)
            continue
        # 未知：先确定弹窗，再返回
        if dismiss_confirm_dialogs(ctx, max_rounds=1):
            continue
        ui_back(ctx)
    ensure_main_city(ctx)
