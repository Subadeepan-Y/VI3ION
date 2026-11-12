"""Colour-based region segmentation.

Coarse by design: finds where the dominant colours live, not what they mean.
Semantic meaning belongs to the semantics module, not here.
"""

from __future__ import annotations

import cv2
import numpy as np

from .colors import rgb_to_lab


def color_regions(
    bgr: np.ndarray,
    palette: list[dict],
    min_coverage: float = 0.012,
    max_regions: int = 8,
) -> list[dict]:
    if bgr.size == 0 or not palette:
        return []
    height, width = bgr.shape[:2]
    total = height * width
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.int16)
    regions: list[dict] = []

    # Skip near-white/near-black backgrounds: their connected masks describe the page, not content.
    candidates = [
        entry
        for entry in palette[1:4]
        if 0.015 <= entry["share"] <= 0.65
    ]
    for entry in candidates:
        target = np.array(rgb_to_lab(tuple(entry["rgb"])))
        target_cv = np.array(
            [target[0] * 255.0 / 100.0 + 0.0, target[1] + 128.0, target[2] + 128.0]
        )
        diff = np.linalg.norm(lab - target_cv, axis=2)
        mask = (diff < 26).astype(np.uint8) * 255
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for label_index in range(1, count):
            x, y, w, h, area = (
                int(stats[label_index, 0]),
                int(stats[label_index, 1]),
                int(stats[label_index, 2]),
                int(stats[label_index, 3]),
                int(stats[label_index, 4]),
            )
            coverage = area / total
            if coverage < min_coverage:
                continue
            if w < 8 or h < 8:
                continue
            regions.append(
                {
                    "bbox": [x, y, x + w, y + h],
                    "coverage": round(coverage, 4),
                    "hex": entry["hex"],
                    "color_name": entry["name"],
                    "area": area,
                }
            )
        if len(regions) >= max_regions:
            break

    regions.sort(key=lambda r: r["coverage"], reverse=True)
    return regions[:max_regions]
