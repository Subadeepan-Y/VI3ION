"""Small-scale scene evidence: counts, focus and corner content.

The shape pass describes large regions. This pass covers what a text model
needs to recognise surface and atmosphere: how many tiny bright points there
are and where, how many warm lit rectangles, which part of the frame carries
the fine detail, and what each corner holds. Everything is a measurement; no
object is named and nothing is inferred beyond the pixels.
"""

from __future__ import annotations

import cv2
import numpy as np

from .colors import brightness_word, nearest_named

SPECK_MIN_VALUE = 170
SPECK_MAX_AREA = 300
SPECK_MIN_COUNT = 40

LIT_HUE_LOW, LIT_HUE_HIGH = 8, 35
LIT_MIN_SATURATION = 90
LIT_MIN_VALUE = 150
LIT_MIN_AREA = 120
LIT_MAX_AREA = 8000
LIT_MIN_COUNT = 3

CORNER_FRACTION = 0.18
CORNER_PATCH_MIN = 100
CORNER_PATCH_MAX = 20000
CORNER_PATCH_SHARE = 0.04
# A saturated corner can be the corner's own subject (rocks, foliage) rather
# than a few patches on it. Above this share the whole-corner mean is reported.
CORNER_PATCH_MAX_SHARE = 0.25
CORNER_VALUE_DELTA = 30

EDGE_COLUMNS, EDGE_ROWS = 4, 3
COLUMN_NAMES = ("left", "centre-left", "centre-right", "right")
ROW_NAMES = ("top", "middle", "bottom")


def _cell_name(row: int, column: int) -> str:
    return f"{ROW_NAMES[row]} {COLUMN_NAMES[column]}"


def speck_field(bgr: np.ndarray) -> str | None:
    """Count tiny bright components and say where they cluster."""
    height = bgr.shape[0]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 2] > SPECK_MIN_VALUE).astype(np.uint8)
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
    areas = stats[1:, 4]
    selected = (areas >= 1) & (areas <= SPECK_MAX_AREA)
    total = int(selected.sum())
    if total < SPECK_MIN_COUNT:
        return None
    ys = centres[1:][selected][:, 1] / max(1.0, float(height))
    thirds = [
        float(((ys >= low) & (ys < high)).mean())
        for low, high in ((0.0, 0.33), (0.33, 0.66), (0.66, 1.01))
    ]
    if min(thirds) > 0.15 or max(thirds) < 0.5:
        spread = "spread over the whole frame"
    else:
        name = ("top", "middle", "bottom")[int(np.argmax(thirds))]
        spread = f"spread over the whole frame, densest in the {name} third"
    tiny = float((areas[selected] <= 20).mean())
    size = "mostly 1-20 px" if tiny > 0.5 else "a few px to a few tens of px"
    return f"About {int(round(total, -1))} small bright points ({size}), {spread}."


def lit_blocks(bgr: np.ndarray) -> str | None:
    """Count small warm bright rectangles (windows, lanterns, reflections)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = (
        (hsv[:, :, 0] >= LIT_HUE_LOW) & (hsv[:, :, 0] <= LIT_HUE_HIGH)
        & (hsv[:, :, 1] > LIT_MIN_SATURATION) & (hsv[:, :, 2] > LIT_MIN_VALUE)
    ).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
    keep = [i for i in range(1, count) if LIT_MIN_AREA <= stats[i, 4] <= LIT_MAX_AREA]
    if len(keep) < LIT_MIN_COUNT:
        return None
    width = bgr.shape[1]
    xs = centres[keep][:, 0] / max(1.0, float(width))
    sides = {
        "left": int((xs < 1 / 3).sum()),
        "middle": int(((xs >= 1 / 3) & (xs <= 2 / 3)).sum()),
        "right": int((xs > 2 / 3).sum()),
    }
    ranked = sorted(sides, key=lambda side: -sides[side])
    floor = max(3, len(keep) // 4)
    qualifying = [side for side in ranked if sides[side] >= floor]
    if len(qualifying) >= 3:
        where = "spread across the left, middle and right thirds"
    elif qualifying:
        where = "most on the " + " and ".join(qualifying[:2])
    else:
        where = "spread across the frame"
    size = int(round(float(np.median([np.sqrt(stats[i, 4]) for i in keep]))))
    return (
        f"{len(keep)} small warm lit rectangles (about {size} px across), "
        f"{where}."
    )


def detail_focus(bgr: np.ndarray) -> str | None:
    """Name the busiest and emptiest cell of a 4x3 edge-density grid."""
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 110)
    cells: list[tuple[float, int, int]] = []
    for row in range(EDGE_ROWS):
        for column in range(EDGE_COLUMNS):
            cell = edges[
                int(row * height / EDGE_ROWS):int((row + 1) * height / EDGE_ROWS),
                int(column * width / EDGE_COLUMNS):int((column + 1) * width / EDGE_COLUMNS),
            ]
            cells.append(((cell > 0).mean(), row, column))
    busiest = max(cells, key=lambda item: item[0])
    emptiest = min(cells, key=lambda item: item[0])
    mean = float(np.mean([cell[0] for cell in cells])) or 1e-6
    if busiest[0] < 1.5 * mean or emptiest[0] > 0.6 * mean:
        return None
    return (
        f"Fine detail is concentrated in the {_cell_name(busiest[1], busiest[2])} "
        f"({busiest[0]:.0%} of pixels on an edge) and sparsest in the "
        f"{_cell_name(emptiest[1], emptiest[2])} ({emptiest[0]:.0%})."
    )


def corner_notes(bgr: np.ndarray) -> list[str]:
    """Describe each corner that differs from the frame: patches or a colour cast."""
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    global_value = float(hsv[:, :, 2].mean())
    cw, ch = int(CORNER_FRACTION * width), int(CORNER_FRACTION * height)
    boxes = {
        "top left": (0, 0, cw, ch),
        "bottom right": (width - cw, height - ch, width, height),
        "bottom left": (0, height - ch, cw, height),
        "top right": (width - cw, 0, width, ch),
    }
    notes: list[str] = []
    for name, (x0, y0, x1, y1) in boxes.items():
        patch = hsv[y0:y1, x0:x1]
        saturated = (
            (patch[:, :, 1] > 90) & (patch[:, :, 2] > 60)
        ).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(saturated, 8)
        patches = [
            stats[i, 4] for i in range(1, count)
            if CORNER_PATCH_MIN <= stats[i, 4] <= CORNER_PATCH_MAX
        ]
        mean_bgr = tuple(float(v) for v in bgr[y0:y1, x0:x1].mean(axis=(0, 1))[:3])
        share = float(saturated.mean())
        if (
            len(patches) >= 2
            and CORNER_PATCH_SHARE <= share <= CORNER_PATCH_MAX_SHARE
        ):
            masked = bgr[y0:y1, x0:x1][saturated.astype(bool)]
            patch_bgr = tuple(float(v) for v in masked.mean(axis=0)[:3])
            notes.append(
                f"{len(patches)} small {nearest_named(patch_bgr)} patches in the "
                f"{name} corner"
            )
            continue
        if abs(float(patch[:, :, 2].mean()) - global_value) > CORNER_VALUE_DELTA:
            notes.append(
                f"the {name} corner is {nearest_named(mean_bgr)}, "
                f"{brightness_word(mean_bgr)}"
            )
    return notes[:2]


def describe_evidence(bgr: np.ndarray) -> list[str]:
    """All small-scale evidence sentences, in a stable order."""
    clauses = [speck_field(bgr), lit_blocks(bgr), detail_focus(bgr)]
    clauses.extend(corner_notes(bgr))
    sentences = []
    for clause in clauses:
        if not clause:
            continue
        if not clause.endswith("."):
            clause += "."
        sentences.append(clause[:1].upper() + clause[1:])
    return sentences
