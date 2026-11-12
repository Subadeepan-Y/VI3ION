"""Shape classification from contours.

A rectangle detector establishes a rectangular region. It does not establish
that the region is a button. That distinction is preserved in the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .contours import extract_contours
from .edges import edge_map

MIN_AREA_RATIO = 0.00028
MAX_SHAPES = 60


@dataclass
class ShapeDetection:
    shape: str
    x: float
    y: float
    w: float
    h: float
    area: float
    perimeter: float
    solidity: float
    fill_ratio: float
    circularity: float
    aspect_ratio: float
    vertices: int
    angle: float
    confidence: float
    touches_border: bool = False
    attributes: dict = field(default_factory=dict)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class GeometryResult:
    shapes: list[ShapeDetection] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    edges: np.ndarray | None = None


def _classify(contour: np.ndarray, image_area: float) -> ShapeDetection | None:
    area = float(cv2.contourArea(contour))
    if area <= 0:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    if w < 4 or h < 4:
        return None

    perimeter = float(cv2.arcLength(contour, True))
    if perimeter <= 0:
        return None
    approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
    vertices = int(len(approx))
    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull)) or 1.0
    solidity = max(0.0, min(1.0, area / hull_area))
    fill_ratio = max(0.0, min(1.0, area / float(w * h)))
    circularity = max(0.0, min(1.0, 4.0 * np.pi * area / (perimeter * perimeter)))
    aspect_ratio = w / float(h) if h else 0.0
    rect = cv2.minAreaRect(contour)
    angle = float(rect[2])

    is_convex = bool(cv2.isContourConvex(approx))
    shape = "polygon"
    confidence = 0.35 + 0.25 * solidity

    if vertices == 4 and is_convex and fill_ratio >= 0.72:
        if 0.88 <= aspect_ratio <= 1.12:
            shape, confidence = "square", min(0.95, 0.55 + 0.45 * fill_ratio)
        else:
            shape, confidence = "rectangle", min(0.95, 0.55 + 0.45 * fill_ratio)
    elif vertices == 3 and fill_ratio >= 0.45:
        shape, confidence = "triangle", min(0.9, 0.45 + 0.5 * fill_ratio)
    elif circularity >= 0.78 and vertices >= 6:
        shape, confidence = "circle", min(0.95, circularity)
    elif fill_ratio >= 0.9 and circularity >= 0.65:
        shape, confidence = "ellipse", min(0.9, circularity)
    elif 4 <= vertices <= 12 and is_convex and fill_ratio >= 0.8 and solidity >= 0.85 and circularity < 0.72:
        # Rounded rectangles land here: corners inflate the vertex count.
        shape, confidence = "rectangle", min(0.92, 0.6 + 0.35 * fill_ratio)
    elif vertices <= 6 and fill_ratio >= 0.55:
        shape, confidence = "polygon", min(0.85, 0.4 + 0.4 * fill_ratio)

    # Extremely elongated, low-fill contours are usually rules/dividers, not elements.
    if max(w, h) / max(1.0, min(w, h)) > 30 and fill_ratio < 0.4:
        return None
    if min(w, h) < 6:
        return None
    if area / image_area > 0.95:
        return None

    return ShapeDetection(
        shape=shape,
        x=float(x),
        y=float(y),
        w=float(w),
        h=float(h),
        area=area,
        perimeter=perimeter,
        solidity=round(solidity, 4),
        fill_ratio=round(fill_ratio, 4),
        circularity=round(circularity, 4),
        aspect_ratio=round(aspect_ratio, 3),
        vertices=vertices,
        angle=round(angle, 2),
        confidence=round(float(confidence), 3),
        attributes={"approx_vertices": vertices, "convex": is_convex},
    )


def detect_shapes(
    bgr: np.ndarray,
    min_area_ratio: float = MIN_AREA_RATIO,
    max_shapes: int = MAX_SHAPES,
) -> GeometryResult:
    height, width = bgr.shape[:2]
    image_area = float(width * height)
    edges, stats = edge_map(bgr)
    contours = extract_contours(edges, min_area=max(80.0, min_area_ratio * image_area))

    detections: list[ShapeDetection] = []
    for contour in contours:
        detection = _classify(contour, image_area)
        if detection is None:
            continue
        x0, y0, x1, y1 = detection.bbox
        detection.touches_border = bool(
            x0 <= 1 or y0 <= 1 or x1 >= width - 1 or y1 >= height - 1
        )
        detections.append(detection)

    # Drop near-duplicate boxes (nested contours of the same visible frame).
    detections.sort(key=lambda d: d.area, reverse=True)
    kept: list[ShapeDetection] = []
    for candidate in detections:
        duplicate = False
        for existing in kept:
            ix = max(0.0, min(candidate.x + candidate.w, existing.x + existing.w) - max(candidate.x, existing.x))
            iy = max(0.0, min(candidate.y + candidate.h, existing.y + existing.h) - max(candidate.y, existing.y))
            intersection = ix * iy
            union = candidate.area + existing.area - intersection
            if union > 0 and intersection / union > 0.9:
                duplicate = True
                break
            # Nested contour of the same visible element (rounded border + inner frame).
            smaller, larger = (candidate, existing) if candidate.area <= existing.area else (existing, candidate)
            if (
                larger.area > 0
                and smaller.area / larger.area > 0.55
                and larger.x <= smaller.x + 3
                and larger.y <= smaller.y + 3
                and larger.x + larger.w >= smaller.x + smaller.w - 3
                and larger.y + larger.h >= smaller.y + smaller.h - 3
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
        if len(kept) >= max_shapes:
            break

    kept.sort(key=lambda d: (d.y, d.x))
    lines = detect_lines(edges)
    diagnostics = {
        **stats,
        "contours_total": len(contours),
        "shapes_kept": len(kept),
        "shape_counts": _count_shapes(kept),
        "horizontal_lines": lines["horizontal"],
        "vertical_lines": lines["vertical"],
        "grid_like": bool(lines["horizontal"] >= 3 and lines["vertical"] >= 3),
        "analysis_size": [width, height],
    }
    return GeometryResult(shapes=kept, diagnostics=diagnostics, edges=edges)


def _count_shapes(shapes: list[ShapeDetection]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for shape in shapes:
        counts[shape.shape] = counts.get(shape.shape, 0) + 1
    return counts


def detect_lines(edges: np.ndarray, min_length_ratio: float = 0.04) -> dict:
    height, width = edges.shape[:2]
    min_length = max(20, int(min(width, height) * min_length_ratio))
    segments = cv2.HoughLinesP(
        edges, 1, np.pi / 180.0, threshold=50, minLineLength=min_length, maxLineGap=8
    )
    horizontal = vertical = diagonal = 0
    if segments is not None:
        segments = np.asarray(segments)
        if segments.ndim == 3:
            segments = segments[:, 0]
        for line in segments:
            x1, y1, x2, y2 = (int(v) for v in line[:4])
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx >= dy * 6:
                horizontal += 1
            elif dy >= dx * 6:
                vertical += 1
            else:
                diagonal += 1
    return {"horizontal": horizontal, "vertical": vertical, "diagonal": diagonal}
