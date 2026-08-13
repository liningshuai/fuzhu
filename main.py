"""兵临天下辅助 - 启动入口。

用法:
  uv run python main.py              # 启动 Web 控制面板
  uv run python main.py --check      # 环境自检
  uv run python main.py --screenshot # 立即截一张图
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def setup_logging() -> None:
    from loguru import logger

    from src.config import config

    log_dir = Path(config.get("bot", "log_dir") or "logs")
    if not log_dir.is_absolute():
        log_dir = ROOT / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    )
    logger.add(
        log_dir / "bot_{time:YYYYMMDD}.log",
        rotation="00:00",
        retention="14 days",
        encoding="utf-8",
        level="DEBUG",
    )


def cmd_check() -> int:
    from loguru import logger

    from src.adb.device import AdbDevice
    from src.config import config

    adb_path = config.get("device", "adb_path")
    serial = config.get("device", "serial")
    package = config.get("game", "package")
    logger.info("ADB 路径: {}", adb_path)
    logger.info("设备序列号: {}", serial)
    logger.info("游戏包名: {}", package)

    if not Path(adb_path).exists():
        logger.error("ADB 不存在，请检查 config/default.yaml")
        return 1

    dev = AdbDevice()
    devices = dev.list_devices()
    logger.info("在线设备: {}", devices or "(无)")
    if serial not in devices:
        logger.warning("配置的 serial 不在设备列表中，可在面板中切换")
    if not devices:
        return 1

    online = dev.is_online()
    logger.info("当前设备在线: {}", online)
    if online:
        w, h = dev.get_screen_size()
        logger.info("分辨率: {}x{}", w, h)
        logger.info("游戏前台: {}", dev.is_game_foreground())
    logger.info("环境检查完成")
    return 0 if online else 1


def cmd_screenshot() -> int:
    from loguru import logger

    from src.adb.device import AdbDevice

    path = AdbDevice().save_screenshot("cli_shot.png")
    logger.info("截图已保存: {}", path)
    return 0


def cmd_run_task(task_id: str) -> int:
    """单次执行某个任务（不进入挂机循环）。"""
    from loguru import logger

    from src.adb.device import AdbDevice
    from src.tasks.base import TaskContext
    from src.tasks.registry import create_task
    from src.vision.match import TemplateMatcher

    device = AdbDevice()
    if not device.is_online():
        logger.error("设备离线")
        return 1
    task = create_task(task_id)
    task.enabled = True
    ctx = TaskContext(device=device, matcher=TemplateMatcher())
    result = task.run(ctx)
    logger.info("任务结果: {} - {}", result.status.value, result.message)
    return 0 if result.status.value in ("success", "skipped") else 1


def cmd_serve() -> int:
    import uvicorn

    from src.config import config

    host = config.get("web", "host") or "127.0.0.1"
    port = int(config.get("web", "port") or 8787)
    print(f"\n  兵临天下辅助已启动")
    print(f"  控制面板: http://{host}:{port}")
    print(f"  按 Ctrl+C 停止\n")
    uvicorn.run(
        "src.web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="兵临天下辅助")
    parser.add_argument("--check", action="store_true", help="环境自检")
    parser.add_argument("--screenshot", action="store_true", help="截图测试")
    parser.add_argument(
        "--run",
        metavar="TASK_ID",
        help="单次执行任务，例如 auto_mail",
    )
    args = parser.parse_args()
    setup_logging()

    if args.check:
        return cmd_check()
    if args.screenshot:
        return cmd_screenshot()
    if args.run:
        return cmd_run_task(args.run)
    return cmd_serve()


if __name__ == "__main__":
    raise SystemExit(main())
