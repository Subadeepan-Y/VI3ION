"""Composition: the large colour areas of a frame and one sentence about how
the frame is divided.

Everything here stays evidence. A region is described by colour, size and
position ("a red horizontal band across the bottom"), never by what it depicts,
and the summary only counts what the earlier passes already found.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .colors import brightness_word, nearest_named
from .text_merge import TextItem

WORK_WIDTH = 320
HUE_BINS = 8
MIN_SATURATION = 70
MIN_VALUE = 45
MIN_COMPONENT_SHARE = 0.012
MAX_COLOUR_REGIONS = 5
MIN_ACCENT_SHARE = 0.01

# Dark saturated masses (a navy building, a dim red roof) sit below the main
# value floor, so they get their own scan rather than being lost.
DARK_MIN_VALUE = 20
DARK_MAX_VALUE = 80
DARK_MIN_SATURATION = 90
DARK_MIN_SHARE = 0.012


@dataclass(frozen=True)
class Region:
    """A large colour area: bbox in image pixels, its colour and pixel share."""

    bbox: tuple[float, float, float, float]
    colour: str
    share: float
    kind: str


def position_words(bbox, height: int, width: int) -> str:
    """Position in words; an axis the region spans is not named."""
    cx = (bbox[0] + bbox[2]) / 2 / width
    cy = (bbox[1] + bbox[3]) / 2 / height
    spans_x = (bbox[2] - bbox[0]) > 0.6 * width
    spans_y = (bbox[3] - bbox[1]) > 0.6 * height
    if cx < 0.33:
        xs = "left"
    elif cx > 0.66:
        xs = "right"
    elif cx > 0.55:
        xs = "centre-right"
    elif cx < 0.45:
        xs = "centre-left"
    else:
        xs = "centre"
    ys = "top" if cy < 0.33 else "bottom" if cy > 0.66 else "centre"
    if spans_x:
        xs = "centre"
    if spans_y:
        ys = ""
    if xs == ys == "centre":
        return "centre"
    if ys == "centre":
        return xs
    if not ys:
        return xs if xs != "centre" else "centre"
    if xs == "centre":
        return f"{ys} centre"
    return f"{ys} {xs}"


def _kind(aspect: float, fill: float) -> str:
    if aspect > 3.0:
        return "horizontal band"
    if aspect < 0.33:
        return "vertical band"
    if 0.8 <= aspect <= 1.25 and fill >= 0.6:
        return "round shape"
    return "block"


def _widens(label_mask: np.ndarray, box_w: int, box_h: int) -> bool:
    """True when a component is much wider near its bottom than near its top."""
    if box_w < 1.5 * box_h:
        return False
    rows = np.where(label_mask.any(axis=1))[0]
    if rows.size < 8:
        return False

    def width_at(fraction: float) -> int:
        y = int(rows[int(fraction * (len(rows) - 1))])
        columns = np.where(label_mask[y])[0]
        return int(columns.max() - columns.min()) if columns.size else 0

    top, bottom = width_at(0.12), width_at(0.72)
    return bottom > 1.5 * max(1, top)


def color_map_grid(bgr: np.ndarray, cols: int = 4, rows: int = 3) -> list[str]:
    """4x3 mean-colour map, top-left first: `row r, col c: name, brightness`."""
    height, width = bgr.shape[:2]
    lines: list[str] = []
    for r in range(rows):
        for c in range(cols):
            cell = bgr[
                int(r * height / rows):int((r + 1) * height / rows),
                int(c * width / cols):int((c + 1) * width / cols),
            ]
            mean_bgr = tuple(float(v) for v in cv2.mean(cell)[:3])
            lines.append(
                f"row {r + 1}, col {c + 1}: {nearest_named(mean_bgr)}, "
                f"{brightness_word(mean_bgr)}"
            )
    return lines


def _dark_colour(mean_bgr) -> str:
    """Name a dark saturated mass, keeping a blue cast that `black` hides."""
    blue, green, red = mean_bgr[:3]
    name = nearest_named(mean_bgr)
    if name == "black" and blue > 1.3 * max(red, 1.0) and blue > 1.15 * max(green, 1.0):
        return "blue-grey"
    return name


def _scan_colour(
    small: np.ndarray,
    scale: float,
    total: float,
    value_low: int,
    value_high: int,
    min_share: float,
    dark: bool = False,
) -> list[Region]:
    """Connected components of saturated pixels within one value band."""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.int16)
    sat = hsv[:, :, 1].astype(np.int16)
    val = hsv[:, :, 2].astype(np.int16)

    regions: list[Region] = []
    bin_width = 180 // HUE_BINS
    for index in range(HUE_BINS):
        low, high = index * bin_width, (index + 1) * bin_width
        mask = (
            (hue >= low) & (hue < high)
            & (sat > MIN_SATURATION) & (val >= value_low) & (val < value_high)
        ).astype(np.uint8)
        if not mask.any():
            continue
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            share = float(area) / total
            if share < min_share:
                continue
            pixels = small[labels == label]
            mean_bgr = tuple(float(v) for v in pixels.mean(axis=0)[:3])
            bbox = (x / scale, y / scale, (x + w) / scale, (y + h) / scale)
            aspect = w / h if h else 1.0
            fill = area / float(w * h) if w * h else 0.0
            kind = _kind(aspect, fill)
            if kind == "horizontal band" and _widens(labels == label, w, h):
                kind = "wedge"
            elif dark and kind == "round shape":
                kind = "mass"
            regions.append(
                Region(
                    bbox=bbox,
                    colour=_dark_colour(mean_bgr) if dark else nearest_named(mean_bgr),
                    share=share,
                    kind=kind,
                )
            )
    return regions


def colour_regions(bgr: np.ndarray, max_regions: int = MAX_COLOUR_REGIONS) -> list[Region]:
    """Large saturated areas, by hue bin and connected component.

    Hue binning is used instead of clustering so the result is deterministic.
    Low-saturation areas (grey, white, black) are left to the edge and column
    passes, which already describe them. A second scan covers dark saturated
    masses that sit below the main value floor.
    """
    height, width = bgr.shape[:2]
    scale = WORK_WIDTH / float(width)
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    total = float(small.shape[0] * small.shape[1])

    regions = _scan_colour(small, scale, total, MIN_VALUE, 256, MIN_COMPONENT_SHARE)
    regions.extend(
        _scan_colour(
            small, scale, total, DARK_MIN_VALUE, DARK_MAX_VALUE, DARK_MIN_SHARE,
            dark=True,
        )
    )

    regions.sort(key=lambda region: -region.share)
    kept: list[Region] = []
    for region in regions:
        if any(_overlaps(region.bbox, other.bbox) for other in kept):
            continue
        kept.append(region)
        if len(kept) >= max_regions:
            break
    return kept


def size_words(bbox, height: int, width: int) -> str:
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if h > 0.6 * height or w > 0.6 * width:
        return "spans most of the image height" if h > w else "spans most of the image width"
    if h > 0.3 * height or w > 0.3 * width:
        return "about a third of the image" if max(h / height, w / width) > 0.3 else "a large area"
    if w > 0.15 * width or h > 0.15 * height:
        return "about a fifth of the width" if w / width > 0.15 else "about a fifth of the height"
    if w > 0.08 * width or h > 0.08 * height:
        return "about a tenth of the width" if w / width > 0.08 else "about a tenth of the height"
    if w > 0.04 * width or h > 0.04 * height:
        return "about a twentieth of the width" if w / width > 0.04 else "about a twentieth of the height"
    return "small"


def contains(outer, inner) -> bool:
    return (
        inner[0] >= outer[0] and inner[1] >= outer[1]
        and inner[2] <= outer[2] and inner[3] <= outer[3]
    )


def text_overlap_notes(bbox, text_items: list[TextItem]) -> list[str]:
    """Text units that sit mostly inside a region."""
    notes = []
    x0, y0, x1, y1 = bbox
    for item in text_items:
        tx0, ty0, tx1, ty1 = item.bbox
        ix = min(x1, tx1) - max(x0, tx0)
        iy = min(y1, ty1) - max(y0, ty0)
        if ix <= 0 or iy <= 0:
            continue
        text_area = (tx1 - tx0) * (ty1 - ty0)
        if text_area > 0 and (ix * iy) / text_area > 0.5:
            notes.append(f"text '{item.value}' sits over this region")
    return notes


COUNT_WORDS = {2: "two", 3: "three", 4: "four"}


def containment_note(bbox, siblings: list[tuple[tuple, str, str]], limit: int = 2) -> str:
    """Name the regions sitting inside this one, largest first, merging repeats."""
    inner = [
        (box, colour, noun)
        for box, colour, noun in siblings
        if box != bbox and contains(bbox, box)
    ]
    if not inner:
        return ""
    inner.sort(key=lambda s: -((s[0][2] - s[0][0]) * (s[0][3] - s[0][1])))
    groups: dict[tuple[str, str], int] = {}
    for _, colour, noun in inner:
        groups[(colour, noun)] = groups.get((colour, noun), 0) + 1
    parts = []
    for (colour, noun), count in list(groups.items())[:limit]:
        if count > 1:
            parts.append(f"{COUNT_WORDS.get(count, count)} {colour} {noun}s")
        else:
            parts.append(f"a {colour} {noun}")
    joined = " and ".join(parts)
    return f"; {joined} sit inside it" if len(parts) > 1 else f"; {joined} sits inside it"


def _overlaps(a, b, tolerance: float = 0.6) -> bool:
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return False
    inter = ix * iy
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and inter / smaller >= tolerance


def compose_summary(
    bgr: np.ndarray,
    columns: list[tuple[float, float, float, float]],
    text_items: list[TextItem],
    regions: list[Region],
) -> str:
    """One sentence describing how the frame is divided.

    Built only from what the other passes measured: tall columns, the largest
    colour area, where the text sits horizontally, and the strongest accent.
    """
    height, width = bgr.shape[:2]
    clauses: list[str] = []

    if columns:
        positions = sorted((box[0] + box[2]) / 2 / width for box in columns)
        where = " and ".join(f"{position:.0%}" for position in positions[:3])
        name = "column" if len(columns) == 1 else "columns"
        clauses.append(
            f"{len(columns)} tall pale {name} at {where} of the width split the frame"
        )

    if regions:
        largest = regions[0]
        clauses.append(
            f"the largest colour area is {_article(largest)} in the "
            f"{position_words(largest.bbox, height, width)} "
            f"({largest.share:.0%} of the frame)"
        )

    if text_items:
        thirds = [0, 0, 0]
        for item in text_items:
            centre = (item.bbox[0] + item.bbox[2]) / 2
            thirds[min(2, int(centre / max(1.0, width) * 3))] += 1
        names = ("left", "middle", "right")
        order = sorted(range(3), key=lambda i: -thirds[i])
        busiest = [names[i] for i in order[:2] if thirds[i]]
        quietest = names[order[-1]]
        if len(busiest) == 2:
            clause = f"text is concentrated in the {' and '.join(busiest)} thirds"
            if thirds[order[-1]] <= max(2, thirds[order[1]] // 4):
                clause += f", with the {quietest} third nearly empty"
            clauses.append(clause)
        elif busiest:
            clauses.append(f"text sits only in the {busiest[0]} third")

    accent = _strongest_accent(bgr, regions)
    if accent is not None and (not regions or accent is not regions[0]):
        clauses.append(
            f"the strongest colour accent is {_article(accent)} in the "
            f"{position_words(accent.bbox, height, width)}"
        )

    return "; ".join(clauses) + "." if clauses else ""


def _article(region: Region) -> str:
    return f"a {region.colour} {region.kind}"


def _strongest_accent(bgr: np.ndarray, regions: list[Region]) -> Region | None:
    """Region with the highest saturation x share, if it is worth naming."""
    if not regions:
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    best: Region | None = None
    best_score = 0.0
    for region in regions:
        if region.share < MIN_ACCENT_SHARE:
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in region.bbox)
        patch = hsv[max(0, y0):y1, max(0, x0):x1]
        if patch.size == 0:
            continue
        score = float(patch[:, :, 1].mean()) * region.share
        if score > best_score:
            best_score = score
            best = region
    return best
