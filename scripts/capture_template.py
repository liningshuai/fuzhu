"""从最新截图裁剪模板工具。

用法:
  1. 先让游戏停在目标界面，执行:
       uv run python main.py --screenshot
  2. 再执行本脚本，按提示输入坐标裁剪:
       uv run python scripts/capture_template.py --name mail_icon --x 100 --y 200 --w 80 --h 80

  坐标基于 1920x1080（或你当前模拟器分辨率）的截图像素。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="裁剪模板")
    parser.add_argument("--name", required=True, help="模板名，如 mail_icon")
    parser.add_argument("--x", type=int, required=True, help="左上角 x")
    parser.add_argument("--y", type=int, required=True, help="左上角 y")
    parser.add_argument("--w", type=int, required=True, help="宽度")
    parser.add_argument("--h", type=int, required=True, help="高度")
    parser.add_argument(
        "--src",
        default=str(ROOT / "assets" / "screenshots" / "cli_shot.png"),
        help="源截图路径",
    )
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        # 尝试 panel_latest
        alt = ROOT / "assets" / "screenshots" / "panel_latest.png"
        if alt.exists():
            src = alt
        else:
            print(f"源截图不存在: {src}")
            print("请先运行: uv run python main.py --screenshot")
            return 1

    img = Image.open(src)
    box = (args.x, args.y, args.x + args.w, args.y + args.h)
    crop = img.crop(box)
    out_dir = ROOT / "assets" / "templates"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.name}.png"
    crop.save(out)
    print(f"已保存模板: {out}  size={crop.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
