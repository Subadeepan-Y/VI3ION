"""Shape descriptions in plain language (Step 2).

Detects large/mid-sized regions and emits one sentence per region: shape class,
size in words, position in words, dominant colour from a small named set, and
text-overlap notes. Three passes feed the list: Canny contours (panels and
background bands), pale column projection (tall columns), and large colour
areas (saturated bands and blobs the edge pass misses). A closing sentence
summarises how the frame is divided.

No object identification happens here — the reading model does that.

Boundary: shape data is evidence, not interpretation. We never say "this is a
button"; we say "a small rectangular area in the upper right".
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .colors import nearest_named
from .composition import (  # noqa: F401  (color_map_grid re-exported)
    Region,
    color_map_grid,
    colour_regions,
    compose_summary,
    containment_note,
    contains,
    position_words,
    size_words,
    text_overlap_notes,
)
from .text_merge import TextItem

MAX_REGIONS = 12
MIN_AREA_FRACTION = 0.004
MIN_DIM_PX = 40
MIN_FILL = 0.35

# Tall vertical bands (pillars/columns) are found by column projection rather
# than contours: on an illustration they are part of, or inside, the large
# background contour, so RETR_EXTERNAL never exposes them separately.
TALL_MIN_VALUE = 120
TALL_MAX_SATURATION = 60
TALL_BAND_FRACTION = 0.7
TALL_MIN_WIDTH_PX = 8
TALL_MAX_WIDTH_FRACTION = 0.12
TALL_MIN_HEIGHT_FRACTION = 0.4
TALL_MIN_ASPECT = 3.0

# A colour region already described by the edge or column pass is not repeated.
DUPLICATE_OVERLAP = 0.45
# A bbox larger than this share of the frame is the scene itself, not a region.
MAX_FRAME_SHARE = 0.45


@dataclass
class Candidate:
    """One described region: an outline, its box, and a measured colour."""

    contour: np.ndarray
    bbox: tuple[float, float, float, float]
    colour: str | None = None
    kind: str | None = None

    @property
    def area(self) -> float:
        return abs(cv2.contourArea(self.contour))


@dataclass
class SceneDescription:
    shapes: list[str]
    composition: str


def _column_bands(occupied: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) runs of True columns."""
    bands: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(occupied):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            bands.append((start, index))
            start = None
    if start is not None:
        bands.append((start, len(occupied)))
    return bands


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return np.array(
        [[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]], dtype=np.int32
    )


def _tall_regions(bgr: np.ndarray) -> list[Candidate]:
    """Tall vertical bands (columns/pillars) by pale, desaturated columns.

    A band qualifies when its columns stay pale for most of the image height,
    it is narrow relative to the image, and it is at least three times taller
    than it is wide.
    """
    height, width = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    pale = (hsv[:, :, 2] > TALL_MIN_VALUE) & (hsv[:, :, 1] < TALL_MAX_SATURATION)
    column_share = pale.mean(axis=0)

    tall: list[Candidate] = []
    for x0, x1 in _column_bands(column_share >= TALL_BAND_FRACTION):
        band_w = x1 - x0
        if band_w < TALL_MIN_WIDTH_PX or band_w > TALL_MAX_WIDTH_FRACTION * width:
            continue
        rows = np.where(pale[:, x0:x1].mean(axis=1) >= 0.5)[0]
        if rows.size == 0:
            continue
        top, bottom = int(rows.min()), int(rows.max()) + 1
        band_h = bottom - top
        if band_h < TALL_MIN_HEIGHT_FRACTION * height or band_h < TALL_MIN_ASPECT * band_w:
            continue
        tall.append(
            Candidate(
                contour=_rectangle(x0, top, x1 - 1, bottom - 1),
                bbox=(float(x0), float(top), float(x1), float(bottom)),
            )
        )
    return tall


def _edge_regions(bgr: np.ndarray) -> list[Candidate]:
    """Large closed regions from a Canny pass (panels, background bands)."""
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    low = max(30, int(np.percentile(blur, 30)))
    high = max(low + 30, int(np.percentile(blur, 95)))
    edges = cv2.Canny(blur, low, high)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = MIN_AREA_FRACTION * width * height
    kept: list[Candidate] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < MIN_DIM_PX or h < MIN_DIM_PX:
            continue
        # open contours (low fill) are usually noise unless very large
        fill_ratio = area / (w * h) if w * h > 0 else 0
        if fill_ratio < MIN_FILL and area < 0.05 * width * height:
            continue
        # skip full-frame outer contour
        if w > 0.98 * width and h > 0.98 * height:
            continue
        # a bbox covering most of the frame is the scene, not a describable region
        if (w * h) > MAX_FRAME_SHARE * width * height:
            continue
        bbox = (float(x), float(y), float(x + w), float(y + h))
        if any(contains(other.bbox, bbox) for other in kept):
            continue
        kept.append(Candidate(contour=contour, bbox=bbox))
    return kept


def _iou(a, b) -> float:
    """Intersection over union, so a thin region inside a wide one is not a
    duplicate of it (the column pass and the band pass both see the frame)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    union = (
        (a[2] - a[0]) * (a[3] - a[1])
        + (b[2] - b[0]) * (b[3] - b[1])
        - inter
    )
    return inter / union if union > 0 else 0.0


def _colour_candidates(regions: list[Region]) -> list[Candidate]:
    """Colour areas as contours, with their measured colour carried through."""
    candidates: list[Candidate] = []
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        w, h = x1 - x0, y1 - y0
        if region.kind == "round shape":
            centre = (int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2)))
            axes = (max(1, int(w / 2)), max(1, int(h / 2)))
            contour = cv2.ellipse2Poly(centre, axes, 0, 0, 360, 5).reshape(-1, 1, 2)
        else:
            contour = _rectangle(x0, y0, x1, y1)
        candidates.append(
            Candidate(
                contour=contour,
                bbox=region.bbox,
                colour=region.colour,
                kind=region.kind,
            )
        )
    return candidates


def describe_scene(
    bgr: np.ndarray,
    text_items: list[TextItem],
    max_regions: int = MAX_REGIONS,
) -> SceneDescription:
    """Describe the regions of an image and how the frame is divided."""
    height, width = bgr.shape[:2]
    colour_areas = colour_regions(bgr)
    columns = _tall_regions(bgr)

    # Specific passes first: a measured colour area outranks an edge contour
    # that happens to enclose it.
    pool: list[Candidate] = list(columns)
    pool.extend(_colour_candidates(colour_areas))
    pool.extend(_edge_regions(bgr))

    kept: list[Candidate] = []
    for candidate in pool:
        if any(_iou(candidate.bbox, other.bbox) >= DUPLICATE_OVERLAP for other in kept):
            continue
        kept.append(candidate)

    kept.sort(key=lambda candidate: -candidate.area)
    kept = kept[:max_regions]
    mask = np.zeros((height, width), dtype=np.uint8)
    described: list[str] = []
    siblings: list[tuple[tuple, str, str]] = []

    for candidate in kept:
        bbox = candidate.bbox
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        aspect = w / h if h > 0 else 1.0
        fill = candidate.area / (w * h) if w * h > 0 else 0

        if candidate.kind == "wedge":
            shape, noun = "a broad area widening toward the bottom", "broad area"
        elif candidate.kind == "mass":
            shape, noun = "a dark mass", "mass"
        elif h > 3 * w:
            shape, noun = "a tall vertical column", "column"
        elif 0.85 <= aspect <= 1.15 and fill >= 0.6:
            shape, noun = "a round shape", "round shape"
        elif w > 3 * h:
            shape, noun = "a horizontal band", "horizontal band"
        else:
            shape, noun = "a rectangular area", "rectangular area"

        if candidate.colour:
            colour = candidate.colour
            colour_hex = ""
        else:
            mask[:] = 0
            cv2.drawContours(mask, [candidate.contour], -1, 255, thickness=-1)
            mean_bgr = cv2.mean(bgr, mask=mask)[:3]
            colour = nearest_named(mean_bgr)
            colour_hex = "#{:02x}{:02x}{:02x}".format(
                int(round(mean_bgr[2])), int(round(mean_bgr[1])), int(round(mean_bgr[0]))
            )

        siblings.append((bbox, colour, noun))
        sentence = (
            f"{shape} ({size_words(bbox, height, width)}) "
            f"in the {position_words(bbox, height, width)}, {colour}"
        )
        if colour_hex:
            # The measured fill colour, unquoted so the fidelity scorer keeps
            # counting only text values.
            sentence += f" ({colour_hex})"
        overlap_notes = text_overlap_notes(bbox, text_items)
        if overlap_notes:
            sentence += "; " + "; ".join(overlap_notes[:2])
        described.append(sentence + ".")

    # Second pass: say which regions sit inside which, largest first.
    described = [
        sentence[:-1] + containment_note(candidate.bbox, siblings) + "."
        for sentence, candidate in zip(described, kept)
    ]

    composition = compose_summary(
        bgr, [column.bbox for column in columns], text_items, colour_areas
    )
    return SceneDescription(shapes=described, composition=composition)


def describe_shapes(
    bgr: np.ndarray,
    text_items: list[TextItem],
    max_regions: int = MAX_REGIONS,
) -> list[str]:
    """Just the per-region sentences (composition is available separately)."""
    return describe_scene(bgr, text_items, max_regions).shapes
