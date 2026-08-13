"""Create the normalized replay and stable template for the attack command popup."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(
    r"C:\Users\LINING~1\AppData\Local\Temp\codex-clipboard-9950afe8-8a9e-4b26-864f-415042c6ef6f.png"
)
REPLAY = ROOT / "assets" / "screenshots" / "startup_command_order_attack_replay.png"
TEMPLATE = ROOT / "assets" / "templates" / "startup_command_order_attack.png"


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"unable to decode image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"unable to encode image: {path}")
    encoded.tofile(str(path))


def main() -> None:
    source = read_image(SOURCE)
    if source.shape[:2] != (1013, 592):
        raise RuntimeError(f"unexpected source shape: {source.shape}")

    # Remove the emulator top bar and right-side tool strip.  The remaining
    # 539x965 area is the game viewport shown in the supplied screenshot.
    viewport = source[48:1013, 0:539]
    replay = cv2.resize(viewport, (1080, 1920), interpolation=cv2.INTER_CUBIC)
    write_image(REPLAY, replay)

    # Keep the same title/banner geometry as the defense-command template.
    template = replay[1330:1510, 480:840]
    if template.shape[:2] != (180, 360):
        raise RuntimeError(f"unexpected template shape: {template.shape}")
    write_image(TEMPLATE, template)


if __name__ == "__main__":
    main()
