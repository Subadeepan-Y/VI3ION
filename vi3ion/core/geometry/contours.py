"""Contour extraction. Contours are geometry, not semantics."""

from __future__ import annotations

import cv2
import numpy as np


def extract_contours(
    edges: np.ndarray,
    min_area: float = 120.0,
    max_area_ratio: float = 0.98,
) -> list[np.ndarray]:
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(edges.shape[0] * edges.shape[1])
    kept: list[np.ndarray] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area or area > image_area * max_area_ratio:
            continue
        kept.append(contour)
    kept.sort(key=lambda c: cv2.contourArea(c), reverse=True)
    return kept
