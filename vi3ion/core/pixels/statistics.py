"""Pixel statistics: brightness, contrast, sharpness, colorfulness, background."""

from __future__ import annotations

import cv2
import numpy as np

from .colors import describe_color, rgb_to_hex


def image_statistics(bgr: np.ndarray) -> dict:
    if bgr.ndim != 3 or bgr.size == 0:
        return {}
    rgb = bgr[:, :, ::-1]
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0].astype(np.float32) * (100.0 / 255.0)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].astype(np.float32) / 255.0

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Hasler-Süsstrunk colorfulness
    r, g, b = (rgb[:, :, i].astype(np.float32) for i in range(3))
    rg = r - g
    yb = 0.5 * (r + g) - b
    colorfulness = float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )

    edge_map = cv2.Canny(gray, 60, 160)
    edge_density = float((edge_map > 0).mean())

    # Background estimate from border pixels (median is robust to one bright edge).
    border = np.concatenate(
        [rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0
    )
    background_rgb = tuple(int(v) for v in np.median(border, axis=0))
    background = describe_color(background_rgb)

    quantized = (rgb // 32).astype(np.uint8).reshape(-1, 3)
    unique_quantized = len(np.unique(quantized, axis=0))
    total_pixels = int(rgb.shape[0] * rgb.shape[1])

    brightness = float(lightness.mean() / 100.0)
    contrast = float(lightness.std() / 100.0)
    tone = "dark" if brightness < 0.35 else "light" if brightness > 0.7 else "mid"

    return {
        "width": int(bgr.shape[1]),
        "height": int(bgr.shape[0]),
        "aspect_ratio": round(bgr.shape[1] / bgr.shape[0], 3) if bgr.shape[0] else None,
        "mean_color": describe_color(tuple(int(v) for v in rgb.reshape(-1, 3).mean(axis=0))),
        "background_color": background,
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "saturation": round(float(saturation.mean()), 3),
        "sharpness_laplacian": round(sharpness, 1),
        "edge_density": round(edge_density, 4),
        "colorfulness": round(colorfulness, 2),
        "unique_quantized_colors": unique_quantized,
        "color_diversity": round(unique_quantized / max(1, min(total_pixels, 4096)) * 100, 2),
        "tone": tone,
        "is_mostly_flat": bool(contrast < 0.06 and edge_density < 0.01),
        "background_hex": rgb_to_hex(background_rgb),
    }
