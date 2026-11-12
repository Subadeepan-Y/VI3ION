"""Per-element colour measurement.

Colour evidence in Vi3ion used to be global: a palette of the whole image plus
a few large colour areas. That tells a text-only model "the frame is mostly
white" but not "the Save button is #2B66E6". This module measures the colour
of an individual element and the background it sits on.

Everything here is measured, never guessed:

- background: the median colour of a thin ring just outside the element
- ink/fill: the median colour of the element's own pixels
- contrast: the WCAG-style luminance ratio between the two

For text, the glyph mask from ``text_merge._glyph_ink`` decides which pixels
belong to the letters, so light-on-dark and dark-on-light both work.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# A pixel counts as ink when it differs from the background by more than this
# (sum of absolute channel differences).
INK_THRESHOLD = 36

# Ring thickness (pixels) sampled around the element for the background.
RING = 3


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _to_rgb(bgr: np.ndarray) -> tuple[int, int, int]:
    b, g, r = (float(v) for v in bgr[:3])
    return (
        int(max(0, min(255, round(r)))),
        int(max(0, min(255, round(g)))),
        int(max(0, min(255, round(b)))),
    )


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Relative luminance (WCAG)."""
    channels = []
    for value in rgb:
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two RGB colours (1 .. 21)."""
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return round((lighter + 0.05) / (darker + 0.05), 1)


def _median_rgb(pixels: np.ndarray) -> tuple[int, int, int] | None:
    if pixels.size == 0:
        return None
    med = np.median(pixels.reshape(-1, 3), axis=0)
    return _to_rgb(med)


def _dominant_rgb(pixels: np.ndarray) -> tuple[int, int, int] | None:
    """Most common quantised colour of a pixel set."""
    if pixels.size == 0:
        return None
    quantised = (pixels.reshape(-1, 3).astype(np.int32) // 16) * 16 + 8
    colors, counts = np.unique(quantised, axis=0, return_counts=True)
    best = colors[int(np.argmax(counts))]
    return _to_rgb(best)


def _box_pixels(bgr: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    height, width = bgr.shape[:2]
    x0 = int(max(0, min(width - 1, round(box[0]))))
    y0 = int(max(0, min(height - 1, round(box[1]))))
    x1 = int(max(x0 + 1, min(width, round(box[2]))))
    y1 = int(max(y0 + 1, min(height, round(box[3]))))
    return bgr[y0:y1, x0:x1]


def _ring_pixels(
    bgr: np.ndarray, box: tuple[float, float, float, float]
) -> np.ndarray:
    """Pixels just outside the box: the local background."""
    height, width = bgr.shape[:2]
    x0 = int(max(0, min(width - 1, round(box[0]))))
    y0 = int(max(0, min(height - 1, round(box[1]))))
    x1 = int(max(x0 + 1, min(width, round(box[2]))))
    y1 = int(max(y0 + 1, min(height, round(box[3]))))
    rx0 = max(0, x0 - RING)
    ry0 = max(0, y0 - RING)
    rx1 = min(width, x1 + RING)
    ry1 = min(height, y1 + RING)
    ring = bgr[ry0:ry1, rx0:rx1].reshape(-1, 3)
    inner = bgr[y0:y1, x0:x1].reshape(-1, 3)
    if ring.shape[0] <= inner.shape[0]:
        return ring
    # Drop the inner pixels: only the border of the ring is background.
    border = np.concatenate(
        [
            bgr[ry0:y0, rx0:rx1].reshape(-1, 3),
            bgr[y1:ry1, rx0:rx1].reshape(-1, 3),
            bgr[y0:y1, rx0:x0].reshape(-1, 3),
            bgr[y0:y1, x1:rx1].reshape(-1, 3),
        ]
    )
    return border if border.size else ring


def measure_element(
    bgr: np.ndarray,
    box: tuple[float, float, float, float],
    glyph_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Measure one element's colour.

    ``glyph_mask`` is optional: for text it is the boolean mask of the letter
    strokes (see ``text_merge._glyph_ink``), which separates the ink colour
    from the background inside the box. Without it the box is treated as a
    filled area (a button, a colour band, an icon).

    Returns a dict with the ink/fill colour, the local background, the
    contrast between them and how much of the box the ink covers.
    """
    from ...colors import nearest_named

    if bgr is None or bgr.size == 0:
        return {}

    pixels = _box_pixels(bgr, box)
    if pixels.size == 0:
        return {}

    ring = _ring_pixels(bgr, box)
    bg_rgb = _median_rgb(ring) if ring.size else None
    if bg_rgb is None:
        bg_rgb = _dominant_rgb(pixels)

    inner = pixels.reshape(-1, 3)
    if glyph_mask is not None and glyph_mask.shape[:2] == pixels.shape[:2]:
        mask = glyph_mask.reshape(-1)
        if mask.any():
            selected = inner[mask]
        else:
            selected = inner
    else:
        # No glyph mask: take the pixels that differ from the background.
        diff = np.abs(inner.astype(np.int32) - np.array(bg_rgb[::-1], dtype=np.int32)).sum(axis=1)
        selected = inner[diff > INK_THRESHOLD]
        if selected.shape[0] == 0:
            selected = inner

    ink_rgb = _dominant_rgb(selected) or _median_rgb(selected) or bg_rgb
    if ink_rgb is None:
        return {}

    ink_share = round(float(selected.shape[0]) / float(inner.shape[0]), 3)
    uniform = int(np.abs(inner.astype(np.int32) - np.array(ink_rgb[::-1], dtype=np.int32)).sum(axis=1).max()) <= INK_THRESHOLD

    bgr_ink = np.array([ink_rgb[2], ink_rgb[1], ink_rgb[0]], dtype=np.float32)
    bgr_bg = np.array([bg_rgb[2], bg_rgb[1], bg_rgb[0]], dtype=np.float32)

    return {
        "ink_hex": _hex(ink_rgb),
        "ink_rgb": list(ink_rgb),
        "ink_name": nearest_named(bgr_ink),
        "bg_hex": _hex(bg_rgb),
        "bg_name": nearest_named(bgr_bg),
        "contrast": contrast_ratio(ink_rgb, bg_rgb),
        "ink_share": ink_share,
        "uniform": bool(uniform),
    }


def measure_many(
    bgr: np.ndarray,
    boxes: list[tuple[float, float, float, float]],
    glyph_masks: dict[int, np.ndarray] | None = None,
) -> list[dict[str, Any]]:
    """Measure several elements in one call."""
    out: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        mask = (glyph_masks or {}).get(index)
        out.append(measure_element(bgr, box, mask))
    return out


def color_suffix(color: dict[str, Any], full: bool = True) -> str:
    """Compact rendering of a measurement for the text brief.

    Colours are never quoted: the fidelity scorer only reads quoted strings,
    so an unquoted suffix keeps the score unchanged.
    """
    if not color or not color.get("ink_hex"):
        return ""
    parts = [f"ink:{color['ink_hex']}"]
    if full:
        parts.append(f"on:{color.get('bg_hex', '')}")
        contrast = color.get("contrast")
        if isinstance(contrast, (int, float)):
            parts.append(f"contrast:{contrast}")
    return " ".join(parts)
