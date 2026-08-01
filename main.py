# -*- coding: utf-8 -*-
"""fuzhu 主入口。

用法:
  python main.py info            查看设备连接状态和当前前台应用（用于查游戏包名）
  python main.py once            按顺序执行 config.yaml 中启用的全部任务
  python main.py loop            循环模式，按各任务的 interval_minutes 周期执行
  python main.py run <任务文件>   只执行单个任务，如 python main.py run mail.yaml
  python main.py shot            截一张屏保存到 captures/ 目录
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from core.adb import ADBClient, ADBError
from core.scheduler import Scheduler

BASE_DIR = Path(__file__).resolve().parent


def setup_logging(level: str = "INFO") -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logfile = log_dir / f"{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logfile, encoding="utf-8"),
        ],
    )


def load_config() -> dict:
    config_path = BASE_DIR / "config" / "config.yaml"
    if not config_path.exists():
        print(f"缺少配置文件: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_adb(config: dict) -> ADBClient:
    adb_cfg = config.get("adb", {})
    adb = ADBClient(
        adb_path=adb_cfg.get("adb_path", "adb"),
        serial=adb_cfg.get("serial", "127.0.0.1:5555"),
    )
    adb.connect()
    return adb


def cmd_info(config: dict) -> None:
    adb = make_adb(config)
    print(adb.devices())
    try:
        print("屏幕分辨率:", adb.screen_size())
    except ADBError as e:
        print("获取分辨率失败:", e)
    print("前台应用:", adb.current_app())
    print("\n提示: 先在模拟器里打开游戏，再运行本命令，"
          "mCurrentFocus 行里 '/' 前面的部分就是游戏包名，"
          "填到 config.yaml 的 game.package 中。")


def cmd_shot(config: dict) -> None:
    adb = make_adb(config)
    cap_dir = BASE_DIR / "captures"
    cap_dir.mkdir(exist_ok=True)
    img = adb.screenshot()
    out = cap_dir / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
    # imencode 方式写入，避免中文路径问题
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        print("截图编码失败")
        sys.exit(1)
    buf.tofile(str(out))
    print(f"已保存截图: {out}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    setup_logging(config.get("log_level", "INFO"))
    command = sys.argv[1]

    try:
        if command == "info":
            cmd_info(config)
        elif command == "shot":
            cmd_shot(config)
        elif command in ("once", "loop", "run"):
            adb = make_adb(config)
            scheduler = Scheduler(config, adb, str(BASE_DIR))
            if command == "once":
                scheduler.run_once()
            elif command == "loop":
                scheduler.run_loop()
            else:
                if len(sys.argv) < 3:
                    print("用法: python main.py run <任务文件名>，"
                          "如 python main.py run mail.yaml")
                    sys.exit(1)
                scheduler.run_single(sys.argv[2])
        else:
            print(f"未知命令: {command}")
            print(__doc__)
            sys.exit(1)
    except ADBError as e:
        print(f"[ADB 错误] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
