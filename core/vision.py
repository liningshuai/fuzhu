# -*- coding: utf-8 -*-
"""图像识别：模板匹配定位屏幕元素。"""
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("fuzhu.vision")

_template_cache = {}


class MatchResult:
    def __init__(self, found: bool, x: int = 0, y: int = 0, score: float = 0.0,
                 w: int = 0, h: int = 0):
        self.found = found
        self.x = x          # 中心点 x
        self.y = y          # 中心点 y
        self.score = score
        self.w = w
        self.h = h

    def __repr__(self):
        if not self.found:
            return f"<MatchResult 未命中 score={self.score:.3f}>"
        return f"<MatchResult ({self.x},{self.y}) score={self.score:.3f}>"


def load_template(template_dir: str, name: str) -> np.ndarray:
    """加载模板图（带缓存）。name 支持子目录，如 mail/claim_all.png"""
    path = Path(template_dir) / name
    key = str(path)
    if key in _template_cache:
        return _template_cache[key]
    if not path.exists():
        raise FileNotFoundError(
            f"模板图不存在: {path}\n"
            f"请先用 tools/capture.py 截屏并裁剪出该按钮/图标，保存到 templates/ 下"
        )
    # imdecode 方式读取，避免 Windows 中文路径问题
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取模板图: {path}")
    _template_cache[key] = img
    return img


def find(screen: np.ndarray, template: np.ndarray,
         threshold: float = 0.85, region: tuple = None) -> MatchResult:
    """在 screen 中查找 template。

    region: (x1, y1, x2, y2) 只在该区域内搜索，可提高速度与准确率。
    返回匹配中心点坐标（全屏坐标系）。
    """
    offset_x, offset_y = 0, 0
    search = screen
    if region:
        x1, y1, x2, y2 = region
        search = screen[y1:y2, x1:x2]
        offset_x, offset_y = x1, y1

    th, tw = template.shape[:2]
    if search.shape[0] < th or search.shape[1] < tw:
        log.warning("搜索区域比模板还小，跳过匹配")
        return MatchResult(False)

    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        cx = offset_x + max_loc[0] + tw // 2
        cy = offset_y + max_loc[1] + th // 2
        return MatchResult(True, cx, cy, max_val, tw, th)
    return MatchResult(False, score=max_val)


def find_all(screen: np.ndarray, template: np.ndarray,
             threshold: float = 0.85, max_count: int = 20) -> list:
    """查找所有匹配位置（例如一排可领取的奖励图标）。"""
    th, tw = template.shape[:2]
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    matches = []
    result_copy = result.copy()
    for _ in range(max_count):
        _, max_val, _, max_loc = cv2.minMaxLoc(result_copy)
        if max_val < threshold:
            break
        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        matches.append(MatchResult(True, cx, cy, max_val, tw, th))
        # 抹掉已命中的区域，避免重复
        x0 = max(0, max_loc[0] - tw // 2)
        y0 = max(0, max_loc[1] - th // 2)
        result_copy[y0:max_loc[1] + th // 2 + 1, x0:max_loc[0] + tw // 2 + 1] = -1
    return matches
