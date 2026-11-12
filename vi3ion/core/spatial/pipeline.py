"""Spatial evidence assembly over shapes, text and semantic objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...schemas import BBox, Evidence, EvidenceKind, Provenance, make_evidence_id
from .relationships import RelationshipBuilder
from .scene_graph import SceneEdge, SceneGraph, SceneElement

MODULE = "spatial"
VERSION = "1.0.0"


@dataclass
class SpatialResult:
    evidence: list[Evidence] = field(default_factory=list)
    graph: dict = field(default_factory=dict)
    relation_count: int = 0


def build_scene(
    image_id: str,
    evidence: list[Evidence],
    width: int,
    height: int,
    scope: str = "image",
) -> SpatialResult:
    elements: list[SceneElement] = []
    shape_candidates = [e for e in evidence if e.kind == EvidenceKind.SHAPE and e.bbox]
    shape_candidates.sort(key=lambda e: (e.bbox.area if e.bbox else 0), reverse=True)
    keep_shapes = {e.evidence_id for e in shape_candidates[:26]}

    for item in evidence:
        if item.bbox is None:
            continue
        if item.kind == EvidenceKind.SHAPE and item.evidence_id not in keep_shapes:
            continue
        if item.kind not in (EvidenceKind.SHAPE, EvidenceKind.TEXT, EvidenceKind.OBJECT):
            continue
        if item.kind == EvidenceKind.TEXT and len(elements) > 90:
            continue
        text = item.attributes.get("text") if item.kind == EvidenceKind.TEXT else None
        elements.append(
            SceneElement(
                id=item.evidence_id,
                label=item.label,
                bbox=item.bbox,
                kind=item.kind.value,
                text=str(text) if text else None,
            )
        )

    elements.sort(key=lambda e: (e.bbox.center_y, e.bbox.x0))
    if not elements:
        return SpatialResult(graph={"nodes": [], "edges": [], "rows": [], "columns": [], "node_count": 0, "edge_count": 0})

    builder = RelationshipBuilder(width, height)
    graph = builder.build(elements, exact_tolerance=max(2.0, min(width, height) * 0.003))
    by_id = {element.id: element for element in elements}

    result = SpatialResult()
    for edge in graph.edges:
        subject = by_id.get(edge.subject)
        obj = by_id.get(edge.object)
        if subject is None or obj is None:
            continue
        bbox = _union(subject.bbox, obj.bbox)
        evidence_id = make_evidence_id(
            image_id,
            EvidenceKind.RELATIONSHIP,
            MODULE,
            "measured_relation",
            f"{edge.predicate}:{edge.subject}:{edge.object}",
            bbox,
        )
        attributes = {
            "predicate": edge.predicate,
            "subject_id": edge.subject,
            "object_id": edge.object,
            "subject_label": subject.label,
            "object_label": obj.label,
            **edge.measurements,
            "note": "derived from bounding-box geometry, not visual judgement",
        }
        result.evidence.append(
            Evidence(
                evidence_id=evidence_id,
                image_id=image_id,
                kind=EvidenceKind.RELATIONSHIP,
                label=f"{subject.label} {edge.predicate.replace('_', ' ')} {obj.label}"[:160],
                bbox=bbox,
                confidence=edge.confidence,
                attributes=attributes,
                provenance=Provenance(
                    module=MODULE, method="measured_relation", version=VERSION
                ),
                observed=True,
                scope=scope,
            )
        )
    result.relation_count = len(result.evidence)
    result.evidence.append(
        Evidence(
            evidence_id=make_evidence_id(image_id, EvidenceKind.NOTE, MODULE, "scene_summary", scope, None),
            image_id=image_id,
            kind=EvidenceKind.NOTE,
            label="scene summary",
            attributes={
                "elements": len(elements),
                "relations": len(graph.edges),
                "rows": len(graph.rows),
                "columns": len(graph.columns),
            },
            provenance=Provenance(module=MODULE, method="scene_summary", version=VERSION),
            observed=True,
            scope=scope,
        )
    )
    result.graph = graph.as_dict() if isinstance(graph, SceneGraph) else {}
    return result


def _union(a: BBox, b: BBox) -> BBox:
    return BBox(x0=min(a.x0, b.x0), y0=min(a.y0, b.y0), x1=max(a.x1, b.x1), y1=max(a.y1, b.y1))
