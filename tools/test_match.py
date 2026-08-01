# -*- coding: utf-8 -*-
"""快速验证某个模板能否在当前屏幕上匹配到。

用法（模拟器开着游戏时运行）:
  python tools/test_match.py mail/mail_icon.png [阈值]

会输出匹配坐标与相似度，并把标注了命中位置的截图存到 captures/ 下。
"""
import sys
from datetime import datetime
from pathlib import Path

import cv2
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.adb import ADBClient           # noqa: E402
from core import vision                  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1]
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.85

    with open(BASE_DIR / "config" / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    adb_cfg = config.get("adb", {})
    adb = ADBClient(adb_cfg.get("adb_path", "adb"),
                    adb_cfg.get("serial", "127.0.0.1:5555"))
    adb.connect()

    screen = adb.screenshot()
    template = vision.load_template(str(BASE_DIR / "templates"), name)
    m = vision.find(screen, template, threshold)
    print(m)
    if m.found:
        cv2.rectangle(
            screen,
            (m.x - m.w // 2, m.y - m.h // 2),
            (m.x + m.w // 2, m.y + m.h // 2),
            (0, 0, 255), 3,
        )
    out = BASE_DIR / "captures" / f"match_{datetime.now():%H%M%S}.png"
    out.parent.mkdir(exist_ok=True)
    ok, buf = cv2.imencode(".png", screen)
    if ok:
        buf.tofile(str(out))
        print(f"标注图已保存: {out}")


if __name__ == "__main__":
    main()
