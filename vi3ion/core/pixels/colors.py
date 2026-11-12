"""Perceptual colour handling. RGB distance is not used for similarity; CIELAB is."""

from __future__ import annotations

import cv2
import numpy as np

# Compact reference palette for naming dominant colours.
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "near-black": (24, 24, 27),
    "charcoal": (54, 57, 63),
    "gray": (128, 128, 128),
    "silver": (192, 192, 192),
    "light-gray": (229, 231, 235),
    "off-white": (248, 248, 250),
    "white": (255, 255, 255),
    "red": (220, 38, 38),
    "crimson": (185, 28, 28),
    "pink": (236, 72, 153),
    "orange": (249, 115, 22),
    "amber": (245, 158, 11),
    "yellow": (250, 204, 21),
    "lime": (132, 204, 22),
    "green": (22, 163, 74),
    "emerald": (5, 150, 105),
    "teal": (13, 148, 136),
    "cyan": (6, 182, 212),
    "sky": (14, 165, 233),
    "blue": (37, 99, 235),
    "navy": (30, 58, 138),
    "indigo": (79, 70, 229),
    "violet": (124, 58, 237),
    "purple": (147, 51, 234),
    "magenta": (192, 38, 211),
    "brown": (120, 72, 40),
    "beige": (214, 197, 168),
    "olive": (101, 116, 40),
    "mint": (167, 243, 208),
}

_NAMED_LAB: dict[str, np.ndarray] | None = None


def rgb_to_lab(rgb: tuple[int, int, int] | np.ndarray) -> tuple[float, float, float]:
    """Return CIELAB in conventional units: L 0-100, a/b roughly -128..127."""
    arr = np.array(rgb, dtype=np.uint8).reshape(1, 1, 3)
    bgr = arr[:, :, ::-1]
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    return (
        float(lab[0] * 100.0 / 255.0),
        float(lab[1] - 128.0),
        float(lab[2] - 128.0),
    )


def rgb_to_hex(rgb: tuple[int, int, int] | np.ndarray) -> str:
    r, g, b = (int(round(float(v))) for v in np.asarray(rgb)[:3])
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def delta_e(lab_a: tuple[float, float, float], lab_b: tuple[float, float, float]) -> float:
    """CIE76 colour difference. Good enough to name colours, not for lab-grade calibration."""
    return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(lab_a, lab_b))))


def _named_lab() -> dict[str, np.ndarray]:
    global _NAMED_LAB
    if _NAMED_LAB is None:
        _NAMED_LAB = {name: np.array(rgb_to_lab(rgb)) for name, rgb in NAMED_COLORS.items()}
    return _NAMED_LAB


def name_color(rgb: tuple[int, int, int] | np.ndarray) -> tuple[str, float]:
    lab = np.array(rgb_to_lab(rgb))
    best_name, best_distance = "unknown", float("inf")
    for name, reference in _named_lab().items():
        distance = float(np.linalg.norm(lab - reference))
        if distance < best_distance:
            best_name, best_distance = name, distance
    return best_name, round(best_distance, 1)


def describe_color(rgb: tuple[int, int, int] | np.ndarray) -> dict:
    lab = rgb_to_lab(rgb)
    name, dist = name_color(rgb)
    return {
        "hex": rgb_to_hex(rgb),
        "rgb": [int(v) for v in np.asarray(rgb)[:3]],
        "lab": [round(v, 1) for v in lab],
        "name": name,
        "name_distance": dist,
    }


def dominant_colors(bgr: np.ndarray, k: int = 5, sample_limit: int = 20000) -> list[dict]:
    """Deterministic k-means palette over a bounded pixel sample."""
    if bgr.size == 0:
        return []
    pixels = bgr.reshape(-1, 3)
    if pixels.shape[0] > sample_limit:
        rng = np.random.default_rng(12345)
        idx = rng.choice(pixels.shape[0], size=sample_limit, replace=False)
        pixels = pixels[idx]
    pixels = pixels.astype(np.float32)
    unique = np.unique(pixels.astype(np.uint8), axis=0)
    k = max(1, min(k, len(unique)))
    if k == 1:
        # Flat (1, 3): np.array([[mean]]) would nest into (1, 1, 3) and break
        # the palette loop below.
        centers = np.asarray(pixels.mean(axis=0), dtype=np.float32).reshape(1, 3)
        labels = np.zeros((pixels.shape[0], 1), dtype=np.int32)
    else:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 0.5)
        cv2.setRNGSeed(7)
        _, labels, centers = cv2.kmeans(
            pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
    counts = np.bincount(labels.flatten(), minlength=len(centers))
    total = int(counts.sum()) or 1
    palette: list[dict] = []
    for index in np.argsort(counts)[::-1]:
        bgr_center = np.asarray(centers[index], dtype=np.float32).reshape(-1)[:3]
        rgb = tuple(int(v) for v in bgr_center[::-1])
        entry = describe_color(rgb)
        entry["share"] = round(float(counts[index]) / total, 4)
        palette.append(entry)
    return palette
