"""Geometry measurements used by spatial reasoning and claim verification."""

from __future__ import annotations

from ...schemas import BBox

ALIGNMENT_KEYS = ("left", "right", "top", "bottom", "center_x", "center_y")


def edge_deltas(a: BBox, b: BBox) -> dict[str, float]:
    return {
        "left": b.x0 - a.x0,
        "right": b.x1 - a.x1,
        "top": b.y0 - a.y0,
        "bottom": b.y1 - a.y1,
        "center_x": b.center_x - a.center_x,
        "center_y": b.center_y - a.center_y,
    }


def aligned_edges(a: BBox, b: BBox, tolerance: float) -> list[dict]:
    results = []
    for edge, delta in edge_deltas(a, b).items():
        if abs(delta) <= tolerance:
            results.append({"edge": edge, "delta": round(delta, 2), "tolerance": round(tolerance, 2)})
    return results


def relative_position(a: BBox, b: BBox) -> str:
    """Describe where `b` is relative to `a`."""
    if a.contains(b):
        return "inside"
    if b.contains(a):
        return "contains"
    if a.intersect(b) is not None:
        return "overlaps"
    if b.y0 >= a.y1:
        return "below"
    if b.y1 <= a.y0:
        return "above"
    if b.x0 >= a.x1:
        return "right_of"
    if b.x1 <= a.x0:
        return "left_of"
    return "disjoint"


def center_distance(a: BBox, b: BBox) -> float:
    ax, ay = a.center
    bx, by = b.center
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def horizontal_gap(a: BBox, b: BBox) -> float:
    return max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))


def vertical_gap(a: BBox, b: BBox) -> float:
    return max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))


def alignment_tolerance(width: int, height: int, fraction: float = 0.005) -> float:
    return max(2.0, min(width, height) * fraction)


def group_rows(boxes: list[BBox], tolerance: float) -> list[list[int]]:
    """Group indices of boxes whose vertical centres fall on the same line."""
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].center_y)
    rows: list[list[int]] = []
    for index in order:
        placed = False
        for row in rows:
            reference = boxes[row[0]]
            if abs(boxes[index].center_y - reference.center_y) <= tolerance:
                row.append(index)
                placed = True
                break
        if not placed:
            rows.append([index])
    for row in rows:
        row.sort(key=lambda i: boxes[i].x0)
    return rows


def group_columns(boxes: list[BBox], tolerance: float) -> list[list[int]]:
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].center_x)
    columns: list[list[int]] = []
    for index in order:
        placed = False
        for column in columns:
            reference = boxes[column[0]]
            if abs(boxes[index].center_x - reference.center_x) <= tolerance:
                column.append(index)
                placed = True
                break
        if not placed:
            columns.append([index])
    for column in columns:
        column.sort(key=lambda i: boxes[i].y0)
    return columns
