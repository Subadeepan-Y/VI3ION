"""Pixel-level evidence assembly."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ...schemas import BBox, Evidence, EvidenceKind, Provenance, make_evidence_id
from ..coordinates import WorkingImage
from .colors import dominant_colors
from .segmentation import color_regions
from .statistics import image_statistics

MODULE = "pixels"
VERSION = "1.0.0"


@dataclass
class PixelResult:
    evidence: list[Evidence] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    palette: list[dict] = field(default_factory=list)
    regions: list[dict] = field(default_factory=list)


def _prov(method: str, params: dict | None = None) -> Provenance:
    return Provenance(module=MODULE, method=method, version=VERSION, params=params or {})


def analyze_pixels(
    working: WorkingImage,
    image_id: str,
    scope: str = "image",
    palette_k: int = 5,
    segment: bool = True,
) -> PixelResult:
    bgr = working.bgr
    result = PixelResult()
    if bgr.size == 0:
        return result

    stats = image_statistics(bgr)
    palette = dominant_colors(bgr, k=palette_k)
    result.stats = stats
    result.palette = palette

    result.evidence.append(
        Evidence(
            evidence_id=make_evidence_id(image_id, EvidenceKind.IMAGE, MODULE, "image_statistics", scope, None),
            image_id=image_id,
            kind=EvidenceKind.IMAGE,
            label="image_statistics",
            confidence=None,
            attributes=stats,
            provenance=_prov("image_statistics"),
            observed=True,
            scope=scope,
        )
    )

    for entry in palette:
        result.evidence.append(
            Evidence(
                evidence_id=make_evidence_id(
                    image_id, EvidenceKind.COLOR, MODULE, "kmeans_palette", entry["hex"], None
                ),
                image_id=image_id,
                kind=EvidenceKind.COLOR,
                label=f"dominant color {entry['name']} {entry['hex']}",
                confidence=min(1.0, float(entry["share"])),
                attributes={
                    "hex": entry["hex"],
                    "rgb": entry["rgb"],
                    "lab": entry["lab"],
                    "color_name": entry["name"],
                    "share": entry["share"],
                },
                provenance=_prov("kmeans_palette", {"k": palette_k}),
                observed=True,
                scope=scope,
            )
        )

    if segment and working.region is None:
        regions = color_regions(bgr, palette)
        result.regions = regions
        for index, region in enumerate(regions):
            x0, y0, x1, y1 = region["bbox"]
            bbox = working.mapper.to_original_bbox(x0, y0, x1, y1)
            result.evidence.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        image_id, EvidenceKind.COLOR, MODULE, "color_component", str(index), bbox
                    ),
                    image_id=image_id,
                    kind=EvidenceKind.COLOR,
                    label=f"{region['color_name']} area ({region['hex']})",
                    bbox=bbox,
                    confidence=min(1.0, float(region["coverage"]) * 2.0),
                    attributes={
                        "hex": region["hex"],
                        "color_name": region["color_name"],
                        "coverage": region["coverage"],
                        "area_px": region["area"],
                    },
                    provenance=_prov("color_component"),
                    observed=True,
                    scope=scope,
                )
            )

    return result
