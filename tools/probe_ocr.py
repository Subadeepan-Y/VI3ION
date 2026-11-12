"""Probe: OCR small regions at 2x/3x scale to see what the plain pass misses."""

from __future__ import annotations

import sys

import cv2

sys.path.insert(0, r"D:\PROJECTS\VI3ION")
from vi3ion.core.ocr.providers import get_ocr_provider  # noqa: E402

PATH = r"C:\Users\ADMIN\Pictures\Screenshots\Screenshot 2026-10-31 212904.png"
bgr = cv2.imread(PATH)
provider = get_ocr_provider()
print("provider available:", provider.available)

CROPS = {
    "top-left brand": (90, 28, 320, 80),
    "footer coords": (60, 905, 420, 948),
    "footer centre": (820, 915, 1100, 948),
    "footer right": (1540, 885, 1919, 948),
    "right list": (1680, 295, 1919, 665),
    "right list numbers": (1690, 330, 1760, 665),
    "bottom bar": (1430, 885, 1919, 918),
    "left meta": (100, 155, 400, 195),
    "poster body": (100, 660, 760, 740),
    "scroll hint": (100, 765, 300, 800),
    "watermark right": (1700, 130, 1919, 300),
}

for name, (x0, y0, x1, y1) in CROPS.items():
    crop = bgr[y0:y1, x0:x1]
    for scale in (1, 2, 3, 4):
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        lines = provider.recognize(big)
        summary = " | ".join(f"{l.text.strip()!r}@{l.confidence:.2f}" for l in lines if l.text.strip())
        if summary:
            print(f"[{name}] x{scale}: {summary}")
    print()
