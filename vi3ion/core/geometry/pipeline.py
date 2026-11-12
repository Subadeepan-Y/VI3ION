"""Geometry evidence assembly: contours in, structured boxes out."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...schemas import BBox, Evidence, EvidenceKind, Provenance, make_evidence_id
from ..coordinates import WorkingImage
from .shapes import ShapeDetection, detect_shapes

MODULE = "geometry"
VERSION = "1.0.0"


@dataclass
class GeometryEvidenceResult:
    evidence: list[Evidence] = field(default_factory=list)
    shapes: list[ShapeDetection] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    boxes: list[BBox] = field(default_factory=list)
    shape_ids: list[str] = field(default_factory=list)


def analyze_geometry(working: WorkingImage, image_id: str, scope: str = "image") -> GeometryEvidenceResult:
    geometry = detect_shapes(working.bgr)
    result = GeometryEvidenceResult(
        shapes=geometry.shapes, diagnostics=geometry.diagnostics
    )

    for index, shape in enumerate(geometry.shapes, start=1):
        x0, y0, x1, y1 = shape.bbox
        bbox = working.mapper.to_original_bbox(x0, y0, x1, y1)
        evidence_id = make_evidence_id(
            image_id, EvidenceKind.SHAPE, MODULE, "contour_classify", f"{shape.shape}_{index}", bbox
        )
        result.shape_ids.append(evidence_id)
        result.boxes.append(bbox)
        result.evidence.append(
            Evidence(
                evidence_id=evidence_id,
                image_id=image_id,
                kind=EvidenceKind.SHAPE,
                label=f"{shape.shape} {index}",
                bbox=bbox,
                confidence=shape.confidence,
                attributes={
                    "shape": shape.shape,
                    "area_px": round(shape.area, 1),
                    "width_px": round(shape.w, 1),
                    "height_px": round(shape.h, 1),
                    "aspect_ratio": shape.aspect_ratio,
                    "solidity": shape.solidity,
                    "fill_ratio": shape.fill_ratio,
                    "circularity": shape.circularity,
                    "rotation_deg": shape.angle,
                    "touches_border": shape.touches_border,
                    "vertices": shape.vertices,
                    "note": "geometry only; object identity is not established",
                },
                provenance=Provenance(
                    module=MODULE,
                    method="contour_classify",
                    version=VERSION,
                    params={"min_area_ratio": 0.00028, "max_shapes": 60},
                ),
                observed=True,
                scope=scope,
            )
        )

    result.evidence.append(
        Evidence(
            evidence_id=make_evidence_id(image_id, EvidenceKind.NOTE, MODULE, "geometry_summary", scope, None),
            image_id=image_id,
            kind=EvidenceKind.NOTE,
            label="geometry summary",
            attributes=geometry.diagnostics,
            provenance=Provenance(module=MODULE, method="geometry_summary", version=VERSION),
            observed=True,
            scope=scope,
        )
    )
    return result
