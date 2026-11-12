"""Edge extraction.

Two complementary passes:
  * Canny on the luminance gradient (strong, clean edges)
  * adaptive threshold (low-contrast UI borders that Canny misses)

The union is intentionally permissive. Contour filtering and OCR-aware response
hygiene remove the resulting noise later.
"""

from __future__ import annotations

import cv2
import numpy as np


def edge_map(bgr: np.ndarray, sigma: float = 0.33) -> tuple[np.ndarray, dict]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    median = float(np.median(gray))
    lower = int(max(0, (1.0 - sigma) * median))
    upper = int(min(255, (1.0 + sigma) * median))
    if upper - lower < 20:
        lower, upper = max(0, lower - 20), min(255, upper + 20)
    canny = cv2.Canny(blurred, lower, upper, L2gradient=True)

    block = 15 if min(gray.shape[:2]) >= 120 else 9
    adaptive = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        block,
        3,
    )

    edges = cv2.bitwise_or(canny, adaptive)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    return edges, {
        "threshold_low": lower,
        "threshold_high": upper,
        "edge_density": round(float((edges > 0).mean()), 4),
        "median_luma": round(median, 1),
        "adaptive_block": block,
    }
