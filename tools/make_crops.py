"""Generate 2x review crops with grid overlays for human transcription.

Reads the fixture screenshot and writes zoomed crops to
tests/fixtures/crops/, each scaled 2x with a pixel grid overlay (every 50
original pixels) and coordinate labels along the axes.

Usage:
    python tools/make_crops.py [image_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = (
    Path.home()
    / "Pictures"
    / "Screenshots"
    / "Screenshot 2026-10-31 212904.png"
)
OUT_DIR = PROJECT / "tests" / "fixtures" / "crops"

SCALE = 2
GRID_STEP = 50  # original pixels between grid lines

CROPS = {
    "top_bar": (0, 0, 1919, 100),
    "left_column": (0, 140, 900, 800),
    "right_column": (1680, 140, 1919, 660),
    "bottom_bar": (0, 880, 1919, 949),
    "centre_scene": (480, 0, 1919, 949),
    "bottom_left": (0, 880, 420, 949),
    "right_edge_lower": (1680, 660, 1919, 949),
}


def draw_grid_and_labels(canvas: np.ndarray, x0: int, y0: int) -> np.ndarray:
    height, width = canvas.shape[:2]
    overlay = canvas.copy()
    for x in range(0, width, GRID_STEP * SCALE):
        cv2.line(overlay, (x, 0), (x, height), (0, 255, 255), 1)
        label = str(x0 + x // SCALE)
        cv2.putText(
            overlay,
            label,
            (x + 2, 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )
    for y in range(0, height, GRID_STEP * SCALE):
        cv2.line(overlay, (0, y), (width, y), (0, 255, 255), 1)
        label = str(y0 + y // SCALE)
        cv2.putText(
            overlay,
            label,
            (2, y + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )
    return cv2.addWeighted(overlay, 0.85, canvas, 0.15, 0)


def main() -> int:
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not image_path.exists():
        print(f"error: image not found: {image_path}", file=sys.stderr)
        return 2
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        print(f"error: could not decode image: {image_path}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (x0, y0, x1, y1) in CROPS.items():
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            print(f"warning: empty crop {name}", file=sys.stderr)
            continue
        up = cv2.resize(
            crop,
            (crop.shape[1] * SCALE, crop.shape[0] * SCALE),
            interpolation=cv2.INTER_CUBIC,
        )
        framed = draw_grid_and_labels(up, x0, y0)
        out = OUT_DIR / f"{name}.png"
        cv2.imwrite(str(out), framed)
        print(f"wrote {out} ({up.shape[1]}x{up.shape[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
