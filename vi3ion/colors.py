"""Small named colour set + nearest-name matching, shared by the shape and
composition passes.

Names are deliberately coarse: the brief describes what it can defend, so a
region is "dark red", never "crimson". Matching happens in Lab so equal
distances look equal to a reader.
"""

from __future__ import annotations

import numpy as np

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (200, 40, 40),
    "dark red": (120, 20, 20),
    "orange": (230, 140, 40),
    "amber": (210, 180, 80),
    "pale or white": (238, 238, 236),
    "grey": (130, 130, 132),
    "black": (18, 16, 18),
    "green": (60, 150, 90),
    "blue": (60, 90, 180),
    "brown": (120, 70, 45),
}


def _to_lab(x: np.ndarray) -> np.ndarray:
    """Quick sRGB -> Lab (D65) approximation."""
    def f(t: np.ndarray) -> np.ndarray:
        delta = 6 / 29
        return np.where(t > delta ** 3, np.cbrt(t), t / (3 * delta ** 2) + 4 / 29)

    x = x / 255.0
    lin = np.where(x > 0.04045, ((x + 0.055) / 1.055) ** 2.4, x / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T
    xyz *= np.array([0.9505, 1.0, 1.0890])
    fx, fy, fz = f(xyz[:, 0]), f(xyz[:, 1]), f(xyz[:, 2])
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=1)


def nearest_named(bgr_mean) -> str:
    """Name the closest entry of ``NAMED_COLORS`` for a BGR mean."""
    rgb = np.array([[bgr_mean[2], bgr_mean[1], bgr_mean[0]]], dtype=np.float64)
    rgb = np.repeat(rgb, len(NAMED_COLORS), axis=0)
    refs = np.array(list(NAMED_COLORS.values()), dtype=np.float64)
    dist = np.sqrt(((_to_lab(rgb) - _to_lab(refs)) ** 2).sum(axis=1))
    return list(NAMED_COLORS.keys())[int(np.argmin(dist))]


def brightness_word(bgr_mean) -> str:
    """Coarse brightness band for a BGR mean."""
    value = (bgr_mean[0] + bgr_mean[1] + bgr_mean[2]) / 3
    return "dark" if value < 70 else "mid" if value < 180 else "bright"
