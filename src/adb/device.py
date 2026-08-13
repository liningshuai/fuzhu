"""雷电模拟器 ADB 封装。"""

from __future__ import annotations

import random
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger
from PIL import Image

from src.config import config


class AdbError(RuntimeError):
    pass


class AdbDevice:
    def __init__(
        self,
        adb_path: Optional[str] = None,
        serial: Optional[str] = None,
    ) -> None:
        self.adb_path = adb_path or config.get("device", "adb_path")
        self.serial = serial or config.get("device", "serial")
        self._input_transform_cache: tuple[float, tuple[int, int, int]] | None = None

    # ------------------------------------------------------------------ #
    # 底层命令
    # ------------------------------------------------------------------ #
    def _run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        check: bool = True,
        binary: bool = False,
    ) -> subprocess.CompletedProcess:
        cmd = [self.adb_path, "-s", self.serial, *args]
        logger.debug("adb {}", " ".join(cmd[1:]))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdbError(f"找不到 ADB: {self.adb_path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB 超时: {' '.join(args)}") from exc

        if check and result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore")
            raise AdbError(f"ADB 失败 ({result.returncode}): {err or args}")
        return result

    def shell(self, command: str, timeout: float = 30) -> str:
        result = self._run(["shell", command], timeout=timeout)
        return result.stdout.decode("utf-8", errors="ignore").strip()

    # ------------------------------------------------------------------ #
    # 设备状态
    # ------------------------------------------------------------------ #
    def is_online(self) -> bool:
        try:
            out = self.shell("echo ok", timeout=5)
            return out == "ok"
        except AdbError:
            return False

    def get_screen_size(self) -> tuple[int, int]:
        out = self.shell("wm size")
        # Physical size: 1920x1080
        if ":" in out:
            size = out.split(":")[-1].strip()
        else:
            size = out.strip()
        w, h = size.lower().split("x")
        return int(w), int(h)

    def get_display_rotation(self) -> int:
        """Return the current Android display rotation as 0/1/2/3.

        The game is rendered in portrait logical coordinates while this emulator
        reports a landscape physical display. ADB input coordinates must follow
        the physical display orientation, so screenshot coordinates need a
        rotation transform before tapping or swiping.
        """
        try:
            output = self.shell(
                "dumpsys window displays | grep -E 'mRotation=|mDisplayRotation=' | head -40",
                timeout=8,
            )
        except AdbError:
            return 0

        numeric = re.findall(r"\bmRotation=(\d)\b", output)
        if numeric:
            return int(numeric[-1]) % 4
        named = re.findall(r"ROTATION_(\d+)", output)
        if named:
            return (int(named[-1]) // 90) % 4
        return 0

    def _input_transform(self) -> tuple[int, int, int]:
        """Get (input_width, input_height, rotation), cached briefly.

        ``wm size`` reports the physical panel orientation on this emulator,
        while ``input`` accepts the logical portrait viewport coordinates used
        by the game. Prefer the input viewport instead of blindly rotating the
        physical panel dimensions.
        """
        now = time.monotonic()
        if self._input_transform_cache and now - self._input_transform_cache[0] < 1.0:
            return self._input_transform_cache[1]

        value = self._get_input_viewport()
        if value is None:
            physical = self.get_screen_size()
            rotation = self.get_display_rotation()
            value = (physical[0], physical[1], rotation)
        self._input_transform_cache = (now, value)
        return value

    def _get_input_viewport(self) -> tuple[int, int, int] | None:
        """Read Android's logical input viewport and raw-to-display rotation."""
        try:
            output = self.shell(
                "dumpsys input | grep -E 'logicalFrame=|RawToDisplay Transform:' | head -40",
                timeout=8,
            )
        except AdbError:
            return None

        frame = re.search(r"logicalFrame=\[0, 0, (\d+), (\d+)\]", output)
        if frame is None:
            return None
        width, height = int(frame.group(1)), int(frame.group(2))
        rotation_match = re.search(r"RawToDisplay Transform: \(ROT_(\d+)\)", output)
        rotation = int(rotation_match.group(1)) // 90 if rotation_match else 0
        return width, height, rotation % 4

    @staticmethod
    def map_content_point_to_input(
        x: int,
        y: int,
        *,
        content_size: tuple[int, int],
        physical_size: tuple[int, int],
        rotation: int,
    ) -> tuple[int, int]:
        """Map portrait screenshot coordinates to Android input coordinates."""
        content_w, content_h = content_size
        physical_w, physical_h = physical_size
        rotation %= 4

        if rotation == 1:  # ROTATION_90
            return (
                round((content_h - y) * physical_w / content_h),
                round(x * physical_h / content_w),
            )
        if rotation == 2:  # ROTATION_180
            return (
                round((content_w - x) * physical_w / content_w),
                round((content_h - y) * physical_h / content_h),
            )
        if rotation == 3:  # ROTATION_270
            return (
                round(y * physical_w / content_h),
                round((content_w - x) * physical_h / content_w),
            )
        return (
            round(x * physical_w / content_w),
            round(y * physical_h / content_h),
        )

    def _map_input_point(self, x: int, y: int) -> tuple[int, int]:
        content_w = int(config.get("device", "screen_width") or 1080)
        content_h = int(config.get("device", "screen_height") or 1920)
        input_w, input_h, rotation = self._input_transform()
        mapped = self.map_content_point_to_input(
            x,
            y,
            content_size=(content_w, content_h),
            physical_size=(input_w, input_h),
            rotation=rotation,
        )
        if mapped != (x, y):
            logger.debug(
                "坐标转换 content=({}, {}) -> input=({}, {}), physical={} rotation={}",
                x,
                y,
                mapped[0],
                mapped[1],
                (input_w, input_h),
                rotation,
            )
        return mapped

    def list_devices(self) -> list[str]:
        cmd = [self.adb_path, "devices"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        devices: list[str] = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    # ------------------------------------------------------------------ #
    # 游戏控制
    # ------------------------------------------------------------------ #
    def _resolve_launcher_activity(self, package: str) -> Optional[str]:
        """Resolve the launchable activity on devices without ``monkey``."""
        try:
            output = self.shell(
                f"cmd package resolve-activity --brief {package}",
                timeout=8,
            )
        except AdbError as exc:
            logger.debug("解析游戏启动 Activity 失败: {}", exc)
            return None

        prefix = f"{package}/"
        for line in reversed(output.splitlines()):
            component = line.strip()
            if component.startswith(prefix):
                return component
        return None

    def start_game(self) -> None:
        package = config.get("game", "package")
        activity = config.get("game", "activity") or ""
        wait = float(config.get("game", "launch_wait") or 15)
        if activity:
            self.shell(f"am start -n {package}/{activity}")
        else:
            component = self._resolve_launcher_activity(package)
            if component:
                self.shell(f"am start -n {component}")
            else:
                # Older images may not expose package resolution; preserve the
                # legacy fallback for those devices.
                self.shell(
                    f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
                )
        logger.info("已启动游戏 {}, 等待 {}s", package, wait)
        time.sleep(wait)

    def stop_game(self) -> None:
        package = config.get("game", "package")
        self.shell(f"am force-stop {package}")
        logger.info("已强制停止 {}", package)

    def is_game_foreground(self) -> bool:
        package = config.get("game", "package")
        focus = self.shell(
            "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' || true"
        )
        return package in focus

    # ------------------------------------------------------------------ #
    # 截图
    # ------------------------------------------------------------------ #
    def screenshot(self, save_path: Optional[Path] = None) -> np.ndarray:
        """返回 BGR numpy 数组（OpenCV 格式）。"""
        from io import BytesIO

        result = self._run(["exec-out", "screencap", "-p"], binary=True, timeout=20)
        raw = result.stdout
        if not raw:
            raise AdbError("截图为空，请检查模拟器与 ADB 连接")

        image = None
        # 正常 PNG 头是 b"\x89PNG\r\n\x1a\n"，不要盲目替换 \r\n
        for candidate in (raw, raw.replace(b"\r\n", b"\n")):
            try:
                image = Image.open(BytesIO(candidate)).convert("RGB")
                break
            except Exception:  # noqa: BLE001
                continue

        if image is None:
            # 回退：写入模拟器再 pull，兼容个别 ADB 实现
            remote = "/sdcard/bltx_screen.png"
            self.shell(f"screencap -p {remote}")
            pull = self._run(["pull", remote, str(Path.cwd() / "_tmp_screen.png")], check=False)
            tmp = Path.cwd() / "_tmp_screen.png"
            if not tmp.exists():
                raise AdbError(f"截图失败，pull 返回: {pull.stderr!r}")
            image = Image.open(tmp).convert("RGB")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

        arr = np.array(image)[:, :, ::-1].copy()  # RGB -> BGR
        if save_path is not None:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            # 用 imencode 避免中文路径问题
            ok, buf = __import__("cv2").imencode(".png", arr)
            if ok:
                buf.tofile(str(save_path))
            else:
                Image.fromarray(arr[:, :, ::-1]).save(save_path)
            logger.debug("截图已保存: {}", save_path)
        return arr

    def save_screenshot(self, name: str = "debug.png") -> Path:
        directory = Path(config.get("vision", "screenshot_dir") or "assets/screenshots")
        if not directory.is_absolute():
            directory = config.root / directory
        path = directory / name
        self.screenshot(save_path=path)
        return path

    # ------------------------------------------------------------------ #
    # 输入
    # ------------------------------------------------------------------ #
    def tap(self, x: int, y: int, jitter: bool = True) -> None:
        x, y = self._map_input_point(int(x), int(y))
        if jitter:
            x += random.randint(-2, 2)
            y += random.randint(-2, 2)
        # 直接 shell，避免额外包装导致延迟
        self.shell(f"input tap {int(x)} {int(y)}")
        logger.debug("tap ({}, {})", int(x), int(y))
        self._action_sleep()

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 400,
    ) -> None:
        x1, y1 = self._map_input_point(int(x1), int(y1))
        x2, y2 = self._map_input_point(int(x2), int(y2))
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        logger.debug("swipe ({},{}) -> ({},{}) {}ms", x1, y1, x2, y2, duration_ms)
        self._action_sleep()

    def back(self) -> None:
        self.shell("input keyevent 4")
        self._action_sleep()

    def home(self) -> None:
        self.shell("input keyevent 3")
        self._action_sleep()

    def text(self, content: str) -> None:
        # 空格需转义；中文建议配合 ADBKeyboard
        escaped = content.replace(" ", "%s").replace("'", "\\'")
        self.shell(f"input text {escaped}")
        self._action_sleep()

    def _action_sleep(self) -> None:
        lo, hi = config.get("bot", "action_jitter") or [0.3, 1.0]
        time.sleep(random.uniform(float(lo), float(hi)))
