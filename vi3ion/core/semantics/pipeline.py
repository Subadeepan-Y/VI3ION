"""Semantic evidence assembly.

Semantic output is always recorded as inferred, never as observed. Providers
return boxes in the working-canvas frame; this module maps them back to
original pixels via the CoordinateMapper.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ...schemas import BBox, Evidence, EvidenceKind, Provenance, make_evidence_id
from ..coordinates import WorkingImage
from .interface import SemanticProvider

MODULE = "semantics"
VERSION = "1.1.0"

MAX_OBJECTS = 40
MAX_CAPTIONS = 20
MAX_TAGS = 10


@dataclass
class SemanticResult:
    evidence: list[Evidence] = field(default_factory=list)
    provider: str = "none"
    model: str | None = None
    warning: str | None = None
    duration_ms: float = 0.0


def analyze_semantics(
    working: WorkingImage,
    image_id: str,
    providers: list[SemanticProvider] | None,
    regions: list[BBox] | None = None,
    scope: str = "image",
) -> SemanticResult:
    if not providers:
        return SemanticResult(warning="semantic provider disabled (deterministic evidence only)")

    started = time.perf_counter()
    warnings: list[str] = []
    names: list[str] = []
    models: list[str] = []
    created: list[Evidence] = []

    working_regions = None
    if regions:
        working_regions = [working.mapper.to_working_bbox(*region.as_list()) for region in regions]

    for provider in providers:
        try:
            response = provider.detect(working.bgr, regions=working_regions)
        except Exception as exc:  # noqa: BLE001 - provider boundary must not kill analysis
            response = None
            warnings.append(f"{provider.name}: failed: {type(exc).__name__}: {exc}")
        names.append(provider.name)
        if getattr(provider, "version", None):
            models.append(f"{provider.name}={provider.version}")
        if response is None:
            continue
        if response.error:
            warnings.append(f"{provider.name}: {response.error}")
        elif response.warning:
            warnings.append(f"{provider.name}: {response.warning}")
        if response.model:
            models.append(str(response.model))

        for index, obj in enumerate(response.objects[:MAX_OBJECTS]):
            if obj.bbox is not None:
                bbox = working.mapper.to_original_bbox(
                    obj.bbox.x0, obj.bbox.y0, obj.bbox.x1, obj.bbox.y1
                )
            else:
                bbox = None
            created.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        image_id, EvidenceKind.OBJECT, MODULE, provider.name,
                        obj.label, bbox, str(index),
                    ),
                    image_id=image_id,
                    kind=EvidenceKind.OBJECT,
                    label=obj.label[:80],
                    bbox=bbox,
                    confidence=max(0.0, min(1.0, obj.confidence)),
                    attributes={
                        "provider": provider.name,
                        "model": obj.source or provider.name,
                        "source": obj.source or provider.name,
                        "inference": True,
                        "note": "inferred by a semantic model; not a direct measurement",
                    },
                    provenance=Provenance(
                        module=MODULE,
                        method=f"{provider.name}_object",
                        version=VERSION,
                        params={"provider": provider.name, "model": obj.source or provider.name},
                    ),
                    observed=False,
                    scope=scope,
                )
            )

        for index, cap in enumerate(response.captions[:MAX_CAPTIONS]):
            bbox = None
            if cap.bbox is not None:
                bbox = working.mapper.to_original_bbox(
                    cap.bbox.x0, cap.bbox.y0, cap.bbox.x1, cap.bbox.y1
                )
            created.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        image_id, EvidenceKind.NOTE, MODULE, f"{provider.name}_caption",
                        cap.text[:40], bbox, str(index),
                    ),
                    image_id=image_id,
                    kind=EvidenceKind.NOTE,
                    label="region caption",
                    bbox=bbox,
                    confidence=max(0.0, min(1.0, cap.confidence)),
                    attributes={
                        "text": cap.text,
                        "provider": provider.name,
                        "source": cap.source or provider.name,
                        "inference": True,
                    },
                    provenance=Provenance(
                        module=MODULE,
                        method=f"{provider.name}_caption",
                        version=VERSION,
                        params={"provider": provider.name},
                    ),
                    observed=False,
                    scope=scope,
                )
            )

        for index, tag in enumerate(response.scene_tags[:MAX_TAGS]):
            created.append(
                Evidence(
                    evidence_id=make_evidence_id(
                        image_id, EvidenceKind.NOTE, MODULE, f"{provider.name}_scene_tag",
                        tag.tag, None, str(index),
                    ),
                    image_id=image_id,
                    kind=EvidenceKind.NOTE,
                    label="scene tag",
                    bbox=None,
                    confidence=max(0.0, min(1.0, tag.confidence)),
                    attributes={
                        "tag": tag.tag,
                        "suggested": True,
                        "provider": provider.name,
                        "source": tag.source or provider.name,
                        "inference": True,
                    },
                    provenance=Provenance(
                        module=MODULE,
                        method=f"{provider.name}_scene_tag",
                        version=VERSION,
                        params={"provider": provider.name},
                    ),
                    observed=False,
                    scope=scope,
                )
            )

    return SemanticResult(
        evidence=created,
        provider="+".join(names),
        model=",".join(models) or None,
        warning=" ".join(dict.fromkeys(warnings)) or None,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
