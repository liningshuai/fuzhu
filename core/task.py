# -*- coding: utf-8 -*-
"""任务执行器：解析 tasks/*.yaml 中的步骤定义并逐步执行。

支持的步骤 action:
  sleep         : {action: sleep, seconds: 2}
  tap_xy        : {action: tap_xy, x: 100, y: 200}
  tap_image     : {action: tap_image, template: mail/icon.png,
                   threshold: 0.85, timeout: 10, optional: false,
                   after_sleep: 1.0, region: [x1,y1,x2,y2]}
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

    # ------------------------------------------------------------------ #
    def run(self) -> bool:
        log.info("== 开始任务: %s ==", self.name)
        try:
            self._run_steps(self.spec["steps"])
            log.info("== 任务完成: %s ==", self.name)
            return True
        except TaskError as e:
            log.error("任务 %s 失败: %s", self.name, e)
            return False

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
        self.adb.tap(step["x"], step["y"])
        time.sleep(float(step.get("after_sleep", 0.8)))

    def _find_with_timeout(self, step, want_gone: bool = False):
        """轮询截屏查找模板，直到超时。"""
        template = vision.load_template(self.template_dir, step["template"])
        threshold = float(step.get("threshold", 0.85))
        timeout = float(step.get("timeout", 10))
        region = tuple(step["region"]) if step.get("region") else None
        interval = float(step.get("interval", 1.0))
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            screen = self.adb.screenshot()
            last = vision.find(screen, template, threshold, region)
            if want_gone and not last.found:
                return last
            if not want_gone and last.found:
                return last
            time.sleep(interval)
        return last

    def _do_tap_image(self, step):
        m = self._find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                log.info("可选步骤未找到 %s，跳过 (score=%.3f)",
                         step["template"], m.score if m else 0)
                return
            raise TaskError(
                f"超时未找到模板 {step['template']} "
                f"(最高相似度 {m.score:.3f}，阈值 {step.get('threshold', 0.85)})"
            )
        self.adb.tap(m.x, m.y)
        time.sleep(float(step.get("after_sleep", 0.8)))

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
            time.sleep(float(step.get("between_sleep", 0.6)))
        time.sleep(float(step.get("after_sleep", 0.5)))

    def _do_wait_image(self, step):
        m = self._find_with_timeout(step)
        if m is None or not m.found:
            if step.get("optional", False):
                return
            raise TaskError(f"超时未等到 {step['template']}")

    def _do_wait_gone(self, step):
        m = self._find_with_timeout(step, want_gone=True)
        if m is not None and m.found and not step.get("optional", False):
            raise TaskError(f"超时后 {step['template']} 仍未消失")

    def _do_swipe(self, step):
        x1, y1 = step["from"]
        x2, y2 = step["to"]
        self.adb.swipe(x1, y1, x2, y2, int(step.get("duration", 300)))
        time.sleep(float(step.get("after_sleep", 0.8)))

    def _do_back(self, step):
        for _ in range(int(step.get("times", 1))):
            self.adb.key_back()
            time.sleep(float(step.get("between_sleep", 0.8)))

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
        sub_steps = step.get("steps", [])
        if not sub_steps:
            raise TaskError("repeat 步骤缺少 steps")
        max_loops = times if times > 0 else int(step.get("max_loops", 50))
        for i in range(max_loops):
            if until_gone:
                template = vision.load_template(self.template_dir, until_gone)
                screen = self.adb.screenshot()
                m = vision.find(screen, template,
                                float(step.get("threshold", 0.85)))
                if not m.found:
                    log.info("repeat: %s 已消失，结束循环（第 %d 轮）",
                             until_gone, i)
                    return
            self._run_steps(sub_steps)
        log.info("repeat: 达到最大循环次数 %d", max_loops)
