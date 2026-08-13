"""模板匹配：在截图中定位按钮/图标。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from src.config import config


@dataclass
class MatchResult:
    name: str
    x: int  # 中心点
    y: int
    score: float
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def top_left(self) -> tuple[int, int]:
        return self.x - self.w // 2, self.y - self.h // 2


class TemplateMatcher:
    def __init__(self, template_dir: Optional[Path] = None) -> None:
        raw = template_dir or config.get("vision", "template_dir") or "assets/templates"
        path = Path(raw)
        if not path.is_absolute():
            path = config.root / path
        self.template_dir = path
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, np.ndarray] = {}
        self.default_threshold = float(
            config.get("vision", "match_threshold") or 0.82
        )

    @staticmethod
    def _imread(path: Path) -> Optional[np.ndarray]:
        """兼容中文路径的 imread（Windows 下 cv2.imread 会失败）。"""
        try:
            data = np.fromfile(str(path), dtype=np.uint8)
            if data.size == 0:
                return None
            return cv2.imdecode(data, cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def imwrite(path: Path, image: np.ndarray) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix or ".png"
        ok, buf = cv2.imencode(ext, image)
        if not ok:
            raise RuntimeError(f"编码图片失败: {path}")
        buf.tofile(str(path))

    def _load(self, name: str) -> np.ndarray:
        if name in self._cache:
            return self._cache[name]
        # 支持 name 或 name.png
        candidates = [
            self.template_dir / name,
            self.template_dir / f"{name}.png",
            self.template_dir / f"{name}.jpg",
        ]
        for path in candidates:
            if path.exists():
                img = self._imread(path)
                if img is None:
                    raise FileNotFoundError(f"无法读取模板: {path}")
                self._cache[name] = img
                return img
        raise FileNotFoundError(
            f"模板不存在: {name} (目录: {self.template_dir})"
        )

    def reload(self) -> None:
        self._cache.clear()

    def find(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> Optional[MatchResult]:
        """
        在 screen 中查找模板。
        region: (x, y, w, h) 可选搜索区域，可加速并降低误匹配。
        """
        thr = self.default_threshold if threshold is None else threshold
        template = self._load(template_name)
        search = screen
        offset_x = offset_y = 0
        if region is not None:
            x, y, w, h = region
            search = screen[y : y + h, x : x + w]
            offset_x, offset_y = x, y

        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            logger.warning("搜索区域小于模板: {}", template_name)
            return None

        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < thr:
            logger.debug(
                "未匹配 {} score={:.3f} < {:.3f}", template_name, max_val, thr
            )
            return None

        th, tw = template.shape[:2]
        cx = offset_x + max_loc[0] + tw // 2
        cy = offset_y + max_loc[1] + th // 2
        match = MatchResult(
            name=template_name,
            x=cx,
            y=cy,
            score=float(max_val),
            w=tw,
            h=th,
        )
        logger.debug("匹配到 {} @({},{}) score={:.3f}", template_name, cx, cy, max_val)
        return match

    def find_all(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: Optional[float] = None,
        max_count: int = 20,
    ) -> list[MatchResult]:
        thr = self.default_threshold if threshold is None else threshold
        template = self._load(template_name)
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= thr)
        th, tw = template.shape[:2]
        matches: list[MatchResult] = []
        # 简单 NMS：按分数排序后去重
        points = list(zip(locations[1], locations[0], result[locations]))
        points.sort(key=lambda p: p[2], reverse=True)
        used: list[tuple[int, int]] = []
        for x, y, score in points:
            cx, cy = x + tw // 2, y + th // 2
            if any(abs(cx - ux) < tw * 0.6 and abs(cy - uy) < th * 0.6 for ux, uy in used):
                continue
            used.append((cx, cy))
            matches.append(
                MatchResult(
                    name=template_name,
                    x=cx,
                    y=cy,
                    score=float(score),
                    w=tw,
                    h=th,
                )
            )
            if len(matches) >= max_count:
                break
        return matches

    def exists(
        self,
        screen: np.ndarray,
        template_name: str,
        threshold: Optional[float] = None,
    ) -> bool:
        return self.find(screen, template_name, threshold=threshold) is not None
