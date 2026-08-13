from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAREHOUSE_SOURCE = Path(
    r"C:\Users\liningshuai\AppData\Local\Temp\codex-clipboard-c6af9293-b499-482e-94c2-4bcae1471a28.png"
)
DEFAULT_MAIN_CITY_SOURCE = Path(
    r"C:\Users\liningshuai\AppData\Local\Temp\codex-clipboard-657b99e6-a608-46de-834e-3c9942293eed.png"
)
NORMALIZED_SIZE = (1080, 1920)
DEFAULT_VIEWPORTS = {
    ("warehouse", (549, 975)): (0, 0, 549, 975),
    ("main_city", (588, 1014)): (0, 39, 549, 975),
}


@dataclass(frozen=True)
class TemplateCrop:
    name: str
    source: str
    box: tuple[int, int, int, int]


REFERENCE_NAMES = {
    "warehouse": "warehouse_reference_screen.png",
    "main_city": "warehouse_reference_main_city.png",
}

TEMPLATE_CROPS = (
    TemplateCrop("warehouse_title", "warehouse", (278, 142, 524, 112)),
    TemplateCrop("warehouse_back", "warehouse", (0, 108, 132, 146)),
    TemplateCrop("warehouse_tab_items", "warehouse", (0, 286, 220, 94)),
    TemplateCrop("warehouse_tab_skill_fragments", "warehouse", (220, 286, 220, 94)),
    TemplateCrop("warehouse_tab_arms_fragments", "warehouse", (440, 286, 220, 94)),
    TemplateCrop("warehouse_tab_treasure_fragments", "warehouse", (660, 286, 220, 94)),
    TemplateCrop("warehouse_tab_specialties", "warehouse", (876, 286, 204, 94)),
    TemplateCrop("warehouse_entry", "main_city", (590, 1760, 128, 118)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare normalized warehouse reference screenshots and templates."
    )
    parser.add_argument(
        "--warehouse-source",
        type=Path,
        default=DEFAULT_WAREHOUSE_SOURCE,
        help="Source screenshot for the warehouse screen.",
    )
    parser.add_argument(
        "--main-city-source",
        type=Path,
        default=DEFAULT_MAIN_CITY_SOURCE,
        help="Source screenshot for the main-city screen.",
    )
    parser.add_argument(
        "--warehouse-viewport",
        type=str,
        default=None,
        help="Override warehouse viewport as x,y,width,height.",
    )
    parser.add_argument(
        "--main-city-viewport",
        type=str,
        default=None,
        help="Override main-city viewport as x,y,width,height.",
    )
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=PROJECT_ROOT / "assets" / "screenshots",
        help="Destination directory for normalized reference screenshots.",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=PROJECT_ROOT / "assets" / "templates",
        help="Destination directory for template crops.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    screenshots_dir = _resolve_inside_project(args.screenshots_dir)
    templates_dir = _resolve_inside_project(args.templates_dir)

    warehouse = _prepare_source(
        kind="warehouse",
        path=args.warehouse_source,
        viewport_override=_parse_box(args.warehouse_viewport),
    )
    main_city = _prepare_source(
        kind="main_city",
        path=args.main_city_source,
        viewport_override=_parse_box(args.main_city_viewport),
    )

    references = {"warehouse": warehouse, "main_city": main_city}
    for key, image in references.items():
        _write_png(screenshots_dir / REFERENCE_NAMES[key], image)

    for spec in TEMPLATE_CROPS:
        source = references[spec.source]
        crop = _crop_checked(source, spec.box, label=spec.name)
        if float(crop.std()) < 2.0:
            raise RuntimeError(
                f"Crop '{spec.name}' appears too flat to be a live template; "
                "pass explicit viewport overrides and inspect the source screenshots."
            )
        _write_png(templates_dir / f"{spec.name}.png", crop)

    return 0


def _prepare_source(
    *,
    kind: str,
    path: Path,
    viewport_override: tuple[int, int, int, int] | None,
) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"{kind} source screenshot does not exist: {path}")
    image = _read_png(path)
    viewport = viewport_override or _default_viewport(kind, image.shape[1], image.shape[0])
    cropped = _crop_checked(image, viewport, label=f"{kind} viewport")
    return cv2.resize(cropped, NORMALIZED_SIZE, interpolation=cv2.INTER_AREA)


def _default_viewport(kind: str, width: int, height: int) -> tuple[int, int, int, int]:
    key = (kind, (width, height))
    viewport = DEFAULT_VIEWPORTS.get(key)
    if viewport is None:
        raise RuntimeError(
            f"No safe default viewport is known for {kind} screenshot size "
            f"{width}x{height}. Pass --{kind.replace('_', '-')}-viewport x,y,width,height."
        )
    return viewport


def _resolve_inside_project(path: Path) -> Path:
    resolved = path if path.is_absolute() else (PROJECT_ROOT / path)
    resolved = resolved.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Output path must stay inside the project root: {resolved}") from exc
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _parse_box(raw: str | None) -> tuple[int, int, int, int] | None:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Expected x,y,width,height, got: {raw!r}")
    x, y, width, height = (int(part) for part in parts)
    return x, y, width, height


def _crop_checked(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    label: str,
) -> np.ndarray:
    x, y, width, height = box
    if width <= 0 or height <= 0:
        raise ValueError(f"{label} must have positive width and height, got {box}")
    max_y, max_x = image.shape[:2]
    if x < 0 or y < 0 or x + width > max_x or y + height > max_y:
        raise RuntimeError(
            f"{label} box {box} exceeds image bounds {(max_x, max_y)}; "
            "provide explicit viewport overrides instead of using guessed pixels."
        )
    crop = image[y : y + height, x : x + width]
    if crop.size == 0:
        raise RuntimeError(f"{label} crop is empty for box {box}")
    return crop


def _read_png(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Failed to decode image: {path}")
    return image


def _write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"Failed to encode image: {path}")
    buffer.tofile(str(path))


if __name__ == "__main__":
    raise SystemExit(main())
