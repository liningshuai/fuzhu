# -*- coding: utf-8 -*-
"""任务执行器：解析 tasks/*.yaml 中的步骤定义并逐步执行。

支持的步骤 action:
  sleep         : {action: sleep, seconds: 2}
  tap_xy        : {action: tap_xy, x: 100, y: 200}
  tap_image     : {action: tap_image, template: mail/icon.png,
                   threshold: 0.85, timeout: 6, optional: false,
                   after_sleep: 0.35, interval: 0.3, region: [x1,y1,x2,y2]}
                   # optional 步骤默认 timeout=0.8（找不到尽快跳过）
  tap_image_all : 点击所有匹配位置（如一排领取按钮）
  wait_image    : 等待某图出现（不点击），参数同 tap_image
  wait_gone     : 等待某图消失（如加载动画）
  swipe         : {action: swipe, from: [x1,y1], to: [x2,y2], duration: 300}
  back          : {action: back, times: 1}
  start_app     : {action: start_app}   # 使用全局 package
  stop_app      : {action: stop_app}
  repeat        : {action: repeat, times: 5, until_gone: xx.png, steps: [...]}
                  # times 与 until_gone 二选一或组合（满足其一即停）
"""
import logging
import time
from pathlib import Path

import yaml

from core import vision

log = logging.getLogger("fuzhu.task")


class TaskError(Exception):
    pass


class TaskBlockedError(TaskError):
    """可预期阻塞：界面条件不满足、无可操作项等，映射为 JobStatus.blocked。"""


class Task:
    """一个任务 = 一个 yaml 文件里定义的一串步骤。"""

    def __init__(self, path: str, adb, template_dir: str, package: str = ""):
        self.path = Path(path)
        self.adb = adb
        self.template_dir = template_dir
        with open(self.path, "r", encoding="utf-8") as f:
            self.spec = yaml.safe_load(f)
        if not isinstance(self.spec, dict) or "steps" not in self.spec:
            raise TaskError(f"{path}: 任务文件必须包含 steps 列表")
        self.name = self.spec.get("name", self.path.stem)
        self.package = self.spec.get("package", package)
        self.step_events: list = []
        self.last_status: str = ""  # "" | "blocked" | "failed"
        self.last_exc = None

    # ------------------------------------------------------------------ #
    def run(self) -> bool:
        """执行任务。失败时 self.last_error 含原因，供上层 TaskResult 使用。"""
        self.last_error = ""
        self.last_status = ""
        self.last_exc = None
        self.step_events = []
        log.info("== 开始任务: %s ==", self.name)
        try:
            self._run_steps(self.spec["steps"])
            log.info("== 任务完成: %s ==", self.name)
            self.step_events.append("全部步骤完成")
            return True
        except TaskBlockedError as e:
            self.last_error = str(e)
            self.last_status = "blocked"
            self.last_exc = e
            log.warning("任务 %s 阻塞: %s", self.name, e)
            self.step_events.append(f"blocked: {e}")
            return False
        except TaskError as e:
            self.last_error = str(e)
            self.last_status = "failed"
            self.last_exc = e
            log.error("任务 %s 失败: %s", self.name, e)
            self.step_events.append(f"failed: {e}")
            return False

    def _raise_missing(self, step, msg: str) -> None:
        """按 on_missing 抛出 blocked 或 failed。"""
        mode = str(step.get("on_missing", "fail")).lower()
        if mode in ("blocked", "block"):
            raise TaskBlockedError(msg)
        raise TaskError(msg)

    def _run_steps(self, steps: list) -> None:
        for i, step in enumerate(steps, 1):
            action = step.get("action")
            log.debug("步骤 %d: %s", i, action)
            handler = getattr(self, f"_do_{action}", None)
            if handler is None:
                raise TaskError(f"未知的 action: {action}")
            handler(step)

    # ------------------------------------------------------------------ #
    # 各种步骤实现
    # ------------------------------------------------------------------ #
    def _do_sleep(self, step):
        time.sleep(float(step.get("seconds", 1)))

    def _do_tap_xy(self, step):
        if self._should_skip(step):
            return
        self.adb.tap(step["x"], step["y"])
        time.sleep(float(step.get("after_sleep", 0.35)))

    def _load_template_safe(self, step):
        """加载模板；文件不存在时，optional 步骤返回 None，否则报错。"""
        rel = step["template"]
        path = Path(self.template_dir) / rel
        if not path.exists():
            if step.get("optional", False):
                log.info("可选模板不存在，跳过: %s", rel)
                return None
            raise TaskError(f"模板文件不存在: {path}")
        return vision.load_template(self.template_dir, rel)

    def _find_with_timeout(self, step, want_gone: bool = False):
        """轮询截屏查找模板，直到超时。

        默认更快：轮询间隔 0.3s；可选步骤超时默认 0.8s（找不到就尽快跳过）。
        """
        template = self._load_template_safe(step)
        if template is None:
            return None
        threshold = float(step.get("threshold", 0.85))
        optional = bool(step.get("optional", False))
        # 可选步骤：找不到应尽快跳过，避免空等数秒
        default_timeout = 0.8 if optional else 6.0
        default_interval = 0.25 if optional else 0.3
        timeout = float(step.get("timeout", default_timeout))
        region = tuple(step["region"]) if step.get("region") else None
        interval = float(step.get("interval", default_interval))
        deadline = time.time() + timeout
        last = None
        while True:
            screen = self.adb.screenshot()
            last = vision.find(screen, template, threshold, region)
            if want_gone and not last.found:
                return last
            if not want_gone and last.found:
                return last
            if time.time() >= deadline:
                break
            time.sleep(interval)
        return last

    def _should_skip(self, step) -> bool:
        """若配置了 skip_if_image 且当前画面能匹配到该图，则跳过本步骤。"""
        skip_tpl = step.get("skip_if_image")
        if not skip_tpl:
            return False
        path = Path(self.template_dir) / skip_tpl
        if not path.exists():
            return False
        template = vision.load_template(self.template_dir, skip_tpl)
        thr = float(step.get("skip_threshold", step.get("threshold", 0.85)))
        screen = self.adb.screenshot()
        m = vision.find(screen, template, thr)
        if m.found:
            log.info("skip_if_image 命中 %s (score=%.3f)，跳过本步骤",
                     skip_tpl, m.score)
            return True
        return False

    def _do_tap_image(self, step):
        if self._should_skip(step):
            return
        m = self._find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                log.info("可选步骤未找到 %s，跳过 (score=%.3f)",
                         step["template"], m.score if m else 0)
                self.step_events.append(f"可选未命中 {step.get('template')}")
                return
            self._raise_missing(
                step,
                f"超时未找到模板 {step['template']} "
                f"(最高相似度 {m.score if m else 0:.3f}，阈值 {step.get('threshold', 0.85)})",
            )
        self.adb.tap(m.x, m.y)
        self.step_events.append(f"点击 {step.get('template')} @({m.x},{m.y})")
        time.sleep(float(step.get("after_sleep", 0.35)))

    def _do_tap_image_all(self, step):
        template = vision.load_template(self.template_dir, step["template"])
        threshold = float(step.get("threshold", 0.85))
        screen = self.adb.screenshot()
        matches = vision.find_all(screen, template, threshold)
        if not matches and not step.get("optional", False):
            raise TaskError(f"未找到任何 {step['template']}")
        log.info("找到 %d 个 %s", len(matches), step["template"])
        for m in matches:
            self.adb.tap(m.x, m.y)
            time.sleep(float(step.get("between_sleep", 0.35)))
        time.sleep(float(step.get("after_sleep", 0.3)))

    def _do_wait_image(self, step):
        m = self._find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                self.step_events.append(f"可选未等到 {step.get('template')}")
                return
            self._raise_missing(step, f"超时未等到 {step['template']}")
        self.step_events.append(f"确认出现 {step.get('template')}")

    def _do_wait_gone(self, step):
        m = self._find_with_timeout(step, want_gone=True)
        if m is not None and m.found and not step.get("optional", False):
            self._raise_missing(
                step, f"超时后 {step['template']} 仍未消失（后置验证失败）"
            )
        self.step_events.append(f"确认消失 {step.get('template')}")

    def _do_swipe(self, step):
        x1, y1 = step["from"]
        x2, y2 = step["to"]
        self.adb.swipe(x1, y1, x2, y2, int(step.get("duration", 300)))
        time.sleep(float(step.get("after_sleep", 0.35)))

    def _do_back(self, step):
        for _ in range(int(step.get("times", 1))):
            self.adb.key_back()
            time.sleep(float(step.get("between_sleep", 0.35)))

    def _do_start_app(self, step):
        pkg = step.get("package", self.package)
        if not pkg:
            raise TaskError("未配置游戏包名 package，请先运行 python main.py info 查询")
        self.adb.start_app(pkg)
        time.sleep(float(step.get("after_sleep", 5)))

    def _do_stop_app(self, step):
        pkg = step.get("package", self.package)
        if pkg:
            self.adb.stop_app(pkg)

    def _do_repeat(self, step):
        times = int(step.get("times", 0))
        until_gone = step.get("until_gone")
        until_image = step.get("until_image")  # 出现某图则停
        sub_steps = step.get("steps", [])
        if not sub_steps:
            raise TaskError("repeat 步骤缺少 steps")
        # require_progress: 至少成功点击一次非 optional 的 tap_image，否则 blocked
        require_progress = bool(step.get("require_progress", False))
        # empty_is_blocked: 首轮 until_gone 目标一开始就不存在 → blocked（无任务可做）
        empty_is_blocked = bool(step.get("empty_is_blocked", False))
        max_loops = times if times > 0 else int(step.get("max_loops", 50))
        progress = 0

        if empty_is_blocked and until_gone:
            path = Path(self.template_dir) / until_gone
            if path.exists():
                template = vision.load_template(self.template_dir, until_gone)
                screen = self.adb.screenshot()
                m = vision.find(
                    screen, template, float(step.get("threshold", 0.85))
                )
                if not m.found:
                    msg = step.get(
                        "empty_message",
                        f"未检测到可操作目标 {until_gone}，无法确认执行结果",
                    )
                    raise TaskBlockedError(msg)

        for i in range(max_loops):
            if until_gone:
                template = vision.load_template(self.template_dir, until_gone)
                screen = self.adb.screenshot()
                m = vision.find(screen, template,
                                float(step.get("threshold", 0.85)))
                if not m.found:
                    log.info("repeat: %s 已消失，结束循环（第 %d 轮）",
                             until_gone, i)
                    self.step_events.append(
                        f"repeat 结束：{until_gone} 已消失（轮次 {i}）"
                    )
                    if require_progress and progress <= 0 and i == 0:
                        raise TaskBlockedError(
                            step.get(
                                "empty_message",
                                f"循环开始时 {until_gone} 已不存在，未执行任何操作",
                            )
                        )
                    return
            if until_image:
                template = vision.load_template(self.template_dir, until_image)
                screen = self.adb.screenshot()
                m = vision.find(screen, template,
                                float(step.get("threshold", 0.85)))
                if m.found:
                    log.info("repeat: %s 已出现，结束循环（第 %d 轮）",
                             until_image, i)
                    self.step_events.append(
                        f"repeat 结束：出现 {until_image}（轮次 {i}）"
                    )
                    return
            before_events = len(self.step_events)
            self._run_steps(sub_steps)
            # 粗略进度：本轮产生了「点击」事件
            new_events = self.step_events[before_events:]
            if any(e.startswith("点击") for e in new_events):
                progress += 1

        log.info("repeat: 达到最大循环次数 %d", max_loops)
        self.step_events.append(f"repeat 达到 max_loops={max_loops}")
        if require_progress and progress <= 0:
            raise TaskBlockedError(
                step.get(
                    "empty_message",
                    "循环结束但未确认任何有效操作，不能标记为成功",
                )
            )
        # 有 until_gone 却跑满仍未消失：后置条件未满足
        if until_gone and not step.get("optional", False):
            self._raise_missing(
                step,
                f"达到最大循环后 {until_gone} 仍存在，未能确认任务完成",
            )
