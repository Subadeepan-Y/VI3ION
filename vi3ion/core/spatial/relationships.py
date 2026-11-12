"""Measured relationships between visible elements."""

from __future__ import annotations

from ...schemas import BBox
from .scene_graph import SceneEdge, SceneGraph, SceneElement


class RelationshipBuilder:
    def __init__(self, width: int, height: int, max_edges: int = 90):
        self.width = width
        self.height = height
        self.max_edges = max_edges
        self.graph = SceneGraph()

    def _add_edge(self, edge: SceneEdge) -> None:
        if len(self.graph.edges) >= self.max_edges:
            return
        key = (edge.subject, edge.predicate, edge.object)
        if any((e.subject, e.predicate, e.object) == key for e in self.graph.edges):
            return
        self.graph.edges.append(edge)

    def add_element(self, element: SceneElement) -> None:
        self.graph.nodes.append(element)

    def build(self, elements: list[SceneElement], exact_tolerance: float = 2.0) -> SceneGraph:
        self.graph.nodes = elements
        by_id = {element.id: element for element in elements}
        boxes = [element.bbox for element in elements]

        row_tolerance = max(4.0, _median_height(boxes) * 0.6)
        rows = _group_rows(boxes, row_tolerance)
        columns = _group_columns(boxes, max(5.0, self.width * 0.012))
        self.graph.rows = [[elements[i].id for i in row] for row in rows]
        self.graph.columns = [[elements[i].id for i in column] for column in columns]

        # Adjacency inside rows and columns: the layout skeleton.
        for row in rows:
            for first, second in zip(row, row[1:]):
                a, b = elements[first], elements[second]
                a_to_b = b.bbox.x0 - a.bbox.x1
                self._add_edge(
                    SceneEdge(
                        subject=a.id,
                        predicate="right_of",
                        object=b.id,
                        measurements={
                            "gap_px": round(a_to_b, 1),
                            "center_dx_px": round(b.bbox.center_x - a.bbox.center_x, 1),
                            "unit": "px",
                        },
                    )
                )
        for column in columns:
            for first, second in zip(column, column[1:]):
                a, b = elements[first], elements[second]
                a_to_b = b.bbox.y0 - a.bbox.y1
                self._add_edge(
                    SceneEdge(
                        subject=a.id,
                        predicate="below",
                        object=b.id,
                        measurements={
                            "gap_px": round(a_to_b, 1),
                            "center_dy_px": round(b.bbox.center_y - a.bbox.center_y, 1),
                            "unit": "px",
                        },
                    )
                )

        # Containment: usually a label inside a panel/button.
        for outer in elements:
            if outer.kind not in ("shape", "object"):
                continue
            for inner in elements:
                if inner.id == outer.id or inner.bbox.area <= 0:
                    continue
                if outer.bbox.contains(inner.bbox, tolerance=exact_tolerance) and inner.bbox.area < outer.bbox.area * 0.85:
                    if inner.kind in ("text", "object", "shape"):
                        self._add_edge(
                            SceneEdge(
                                subject=inner.id,
                                predicate="inside",
                                object=outer.id,
                                measurements={
                                    "coverage": round(inner.bbox.area / outer.bbox.area, 3),
                                    "inset_left_px": round(inner.bbox.x0 - outer.bbox.x0, 1),
                                    "inset_top_px": round(inner.bbox.y0 - outer.bbox.y0, 1),
                                    "unit": "px",
                                },
                                confidence=0.95,
                            )
                        )

        # Exact edge alignment, restricted to plausible neighbours.
        alignment_pairs = 0
        for i, a in enumerate(elements):
            for b in elements[i + 1 :]:
                if alignment_pairs >= 45:
                    break
                if _center_distance(a.bbox, b.bbox) > max(self.width, self.height) * 0.6:
                    continue
                if a.kind == "text" and b.kind == "text":
                    continue
                checks = [
                    ("aligned_left", a.bbox.x0, b.bbox.x0),
                    ("aligned_right", a.bbox.x1, b.bbox.x1),
                    ("aligned_top", a.bbox.y0, b.bbox.y0),
                    ("aligned_bottom", a.bbox.y1, b.bbox.y1),
                    ("aligned_center_x", a.bbox.center_x, b.bbox.center_x),
                ]
                best = None
                for predicate, va, vb in checks:
                    delta = vb - va
                    if abs(delta) <= exact_tolerance and (best is None or abs(delta) < abs(best[2])):
                        best = (predicate, va, delta)
                if best is not None:
                    predicate, _value, delta = best
                    self._add_edge(
                        SceneEdge(
                            subject=a.id,
                            predicate=predicate,
                            object=b.id,
                            measurements={
                                "delta_px": round(delta, 2),
                                "tolerance_px": round(exact_tolerance, 2),
                                "unit": "px",
                            },
                        )
                    )
                    alignment_pairs += 1

        # Overlaps among shapes (cards, panels, dialogs).
        for i, a in enumerate(elements):
            if a.kind != "shape":
                continue
            for b in elements[i + 1 :]:
                if b.kind != "shape":
                    continue
                iou = a.bbox.iou(b.bbox)
                if 0.08 <= iou < 0.9:
                    self._add_edge(
                        SceneEdge(
                            subject=a.id,
                            predicate="overlaps",
                            object=b.id,
                            measurements={"iou": round(iou, 3)},
                            confidence=0.9,
                        )
                    )
        return self.graph

    def relabel(self, by_id: dict[str, SceneElement]) -> None:
        for edge in self.graph.edges:
            edge.measurements.setdefault("subject_label", by_id.get(edge.subject, SceneElement("", "", BBox(0, 0, 0, 0), "")).label)


def _group_rows(boxes: list[BBox], tolerance: float) -> list[list[int]]:
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].center_y)
    rows: list[list[int]] = []
    for index in order:
        for row in rows:
            reference = boxes[row[0]]
            if abs(boxes[index].center_y - reference.center_y) <= tolerance:
                row.append(index)
                break
        else:
            rows.append([index])
    for row in rows:
        row.sort(key=lambda i: boxes[i].x0)
    return rows


def _group_columns(boxes: list[BBox], tolerance: float) -> list[list[int]]:
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].x0)
    columns: list[list[int]] = []
    for index in order:
        for column in columns:
            reference = boxes[column[0]]
            if abs(boxes[index].x0 - reference.x0) <= tolerance:
                column.append(index)
                break
        else:
            columns.append([index])
    for column in columns:
        column.sort(key=lambda i: boxes[i].y0)
    return columns


def _median_height(boxes: list[BBox]) -> float:
    heights = sorted(max(1.0, box.height) for box in boxes)
    if not heights:
        return 10.0
    return heights[len(heights) // 2]


def _center_distance(a: BBox, b: BBox) -> float:
    ax, ay = a.center
    bx, by = b.center
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
