"""Normalize the supplied stargaze screenshots and create stable crops."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = Path(r"C:\Users\LINING~1\AppData\Local\Temp")
SCREENSHOT_DIR = ROOT / "assets" / "screenshots"
TEMPLATE_DIR = ROOT / "assets" / "templates"


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"unable to decode {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"unable to encode {path}")
    encoded.tofile(str(path))


def main() -> None:
    source_names = {
        "stargaze_main_city_replay.png": "codex-clipboard-71a37d31-81b1-47c4-ac27-5f165101ba33.png",
        "stargaze_fief_replay.png": "codex-clipboard-40c53a22-300a-45c5-ac4f-7e67a19aed5f.png",
        "stargaze_academy_replay.png": "codex-clipboard-69e3ddc3-012b-46d4-81f9-9d55f9215a6f.png",
        "stargaze_dialog_replay.png": "codex-clipboard-673d1728-89e0-4781-9730-9b1b5081e582.png",
    }
    normalized = {}
    for target_name, source_name in source_names.items():
        source = read_image(SOURCE_DIR / source_name)
        image = cv2.resize(source, (1080, 1920), interpolation=cv2.INTER_CUBIC)
        target = SCREENSHOT_DIR / target_name
        write_image(target, image)
        normalized[target_name] = image

    # Source coordinates are in the supplied 543x965 screenshots.  Crop only
    # stable object/button pixels and avoid red annotation borders.
    academy = normalized["stargaze_academy_replay.png"]
    dialog = normalized["stargaze_dialog_replay.png"]

    def crop_scaled(image: np.ndarray, left: int, top: int, right: int, bottom: int):
        scale_x = 1080 / 543
        scale_y = 1920 / 965
        return image[
            round(top * scale_y) : round(bottom * scale_y),
            round(left * scale_x) : round(right * scale_x),
        ]

    crops = {
        "stargaze_academy.png": crop_scaled(academy, 173, 374, 265, 451),
        "stargaze_free_marker.png": crop_scaled(academy, 185, 313, 246, 380),
        "stargaze_title.png": crop_scaled(dialog, 16, 200, 526, 233),
        "stargaze_free_item.png": crop_scaled(dialog, 57, 744, 207, 797),
        "stargaze_paid_observe.png": crop_scaled(dialog, 338, 744, 489, 797),
        "stargaze_close.png": crop_scaled(dialog, 14, 201, 65, 233),
    }
    for name, crop in crops.items():
        write_image(TEMPLATE_DIR / name, crop)


if __name__ == "__main__":
    main()
