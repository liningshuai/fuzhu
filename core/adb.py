# -*- coding: utf-8 -*-
"""ADB 客户端封装：连接雷电模拟器、截屏、点击、滑动、按键。"""
import logging
import subprocess
import time

import cv2
import numpy as np

log = logging.getLogger("fuzhu.adb")


class ADBError(Exception):
    pass


class ADBClient:
    def __init__(self, adb_path: str = "adb", serial: str = "127.0.0.1:5555"):
        self.adb_path = adb_path
        self.serial = serial

    # ------------------------------------------------------------------ #
    # 基础命令
    # ------------------------------------------------------------------ #
    def _run(self, *args: str, binary: bool = False, timeout: int = 30):
        cmd = [self.adb_path, "-s", self.serial, *args]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False
            )
        except FileNotFoundError:
            raise ADBError(
                f"找不到 adb 可执行文件: {self.adb_path}，"
                "请在 config.yaml 中把 adb_path 指向雷电安装目录下的 adb.exe"
            )
        except subprocess.TimeoutExpired:
            raise ADBError(f"adb 命令超时: {' '.join(cmd)}")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ADBError(f"adb 命令失败: {' '.join(args)} -> {stderr}")
        return result.stdout if binary else result.stdout.decode(
            "utf-8", errors="replace"
        )

    def connect(self) -> None:
        """连接模拟器（adb connect 不带 -s 参数）。"""
        cmd = [self.adb_path, "connect", self.serial]
        result = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
        out = result.stdout.decode("utf-8", errors="replace").strip()
        log.info("adb connect: %s", out)
        if "connected" not in out and "already" not in out:
            raise ADBError(
                f"无法连接到 {self.serial}，请确认雷电模拟器已启动，"
                "且在雷电设置-其他设置中开启了 ADB 调试(开启本地连接)"
            )

    def devices(self) -> str:
        result = subprocess.run(
            [self.adb_path, "devices"], capture_output=True, timeout=15, check=False
        )
        return result.stdout.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ #
    # 屏幕
    # ------------------------------------------------------------------ #
    def screenshot(self) -> np.ndarray:
        """截屏并返回 OpenCV BGR 图像。"""
        raw = self._run("exec-out", "screencap", "-p", binary=True)
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ADBError("截屏失败：无法解码图像数据")
        return img

    def screen_size(self) -> tuple:
        out = self._run("shell", "wm", "size")
        # 形如 "Physical size: 1920x1080"
        part = out.strip().split(":")[-1].strip()
        w, h = part.split("x")
        return int(w), int(h)

    # ------------------------------------------------------------------ #
    # 输入
    # ------------------------------------------------------------------ #
    def tap(self, x: int, y: int) -> None:
        log.debug("tap (%d, %d)", x, y)
        self._run("shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        log.debug("swipe (%d,%d)->(%d,%d) %dms", x1, y1, x2, y2, duration_ms)
        self._run(
            "shell", "input", "swipe",
            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
            str(int(duration_ms)),
        )

    def key_back(self) -> None:
        self._run("shell", "input", "keyevent", "4")

    def key_home(self) -> None:
        self._run("shell", "input", "keyevent", "3")

    # ------------------------------------------------------------------ #
    # 应用
    # ------------------------------------------------------------------ #
    def start_app(self, package: str) -> None:
        log.info("启动应用 %s", package)
        self._run(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        time.sleep(3)

    def stop_app(self, package: str) -> None:
        log.info("停止应用 %s", package)
        self._run("shell", "am", "force-stop", package)

    def current_app(self) -> str:
        """返回当前前台应用信息，用于查询游戏包名。"""
        try:
            out = self._run("shell", "dumpsys", "window")
            for line in out.splitlines():
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    return line.strip()
        except ADBError:
            pass
        # 备用方案
        out = self._run("shell", "dumpsys", "activity", "activities")
        for line in out.splitlines():
            if "mResumedActivity" in line:
                return line.strip()
        return "(未获取到前台应用)"
