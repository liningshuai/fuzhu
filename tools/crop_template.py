# -*- coding: utf-8 -*-
"""模板裁剪工具：从截图中框选区域，保存为模板图。

用法:
  python tools/crop_template.py captures/screen_xxx.png

操作:
  - 鼠标左键拖一个矩形框住要识别的按钮/图标
  - 按 s 保存（会提示输入保存文件名，如 mail/mail_icon.png）
  - 按 r 重新框选
  - 移动鼠标时窗口标题显示当前坐标，方便查 tap_xy 用的坐标
  - 按 q 退出
"""
import sys
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

_state = {"start": None, "end": None, "drawing": False, "pos": (0, 0)}


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        _state["start"] = (x, y)
        _state["end"] = (x, y)
        _state["drawing"] = True
    elif event == cv2.EVENT_MOUSEMOVE:
        _state["pos"] = (x, y)
        if _state["drawing"]:
            _state["end"] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        _state["end"] = (x, y)
        _state["drawing"] = False
        print(f"已框选: {_state['start']} -> {_state['end']}，按 s 保存，按 r 重选")


def imread_unicode(path: str):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    img_path = sys.argv[1]
    img = imread_unicode(img_path)
    if img is None:
        print(f"无法读取图片: {img_path}")
        sys.exit(1)

    win = "crop_template  (drag=select, s=save, r=reset, q=quit)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    # 大图缩放显示，但保存时用原始坐标
    cv2.resizeWindow(win, min(img.shape[1], 1600), min(img.shape[0], 900))
    cv2.setMouseCallback(win, on_mouse)
    print("拖动鼠标框选区域；坐标显示在控制台。")

    while True:
        canvas = img.copy()
        if _state["start"] and _state["end"]:
            cv2.rectangle(canvas, _state["start"], _state["end"], (0, 0, 255), 2)
        cv2.putText(canvas, f"pos: {_state['pos']}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        cv2.imshow(win, canvas)
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            _state["start"] = _state["end"] = None
        if key == ord("s") and _state["start"] and _state["end"]:
            x1, y1 = _state["start"]
            x2, y2 = _state["end"]
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            if x2 - x1 < 5 or y2 - y1 < 5:
                print("框选区域太小，请重新框选")
                continue
            crop = img[y1:y2, x1:x2]
            name = input("保存文件名（相对 templates/，如 mail/mail_icon.png）: ").strip()
            if not name:
                print("已取消")
                continue
            if not name.endswith(".png"):
                name += ".png"
            out = TEMPLATE_DIR / name
            out.parent.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".png", crop)
            if ok:
                buf.tofile(str(out))
                print(f"已保存模板: {out}  尺寸 {x2-x1}x{y2-y1}")
                print(f"该区域中心点坐标（可用于 tap_xy）: "
                      f"({(x1+x2)//2}, {(y1+y2)//2})")
            else:
                print("保存失败")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
