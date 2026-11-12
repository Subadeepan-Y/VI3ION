"""Shared evidence contract.

Every perception module speaks this language. Nothing else in the system is
allowed to invent its own result shape: OCR, geometry, semantics, spatial
reasoning and verification all return `Evidence` (or reference it by id).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.1.0"  # 1.1.0 adds measured per-element colours
COORDINATE_SPACE = "original_pixels"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceKind(str, Enum):
    IMAGE = "image"
    TEXT = "text"
    SHAPE = "shape"
    COLOR = "color"
    OBJECT = "object"
    RELATIONSHIP = "relationship"
    VERIFICATION = "verification"
    NOTE = "note"


class BBox(BaseModel):
    """Axis-aligned box in original image pixel coordinates: [x0, y0, x1, y1]."""

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 < self.x0:
            raise ValueError("x1 must be >= x0")
        if self.y1 < self.y0:
            raise ValueError("y1 must be >= y0")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @classmethod
    def from_any(cls, value: Any) -> "BBox":
        if isinstance(value, BBox):
            return value
        if isinstance(value, dict):
            keys = set(value)
            if {"x0", "y0", "x1", "y1"} <= keys:
                return cls(**{k: float(value[k]) for k in ("x0", "y0", "x1", "y1")})
            if {"x", "y", "width", "height"} <= keys:
                x, y = float(value["x"]), float(value["y"])
                return cls(x0=x, y0=y, x1=x + float(value["width"]), y1=y + float(value["height"]))
            raise ValueError("bbox object must be {x0,y0,x1,y1} or {x,y,width,height}")
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return cls(x0=float(value[0]), y0=float(value[1]), x1=float(value[2]), y1=float(value[3]))
        raise ValueError("bbox must be [x0, y0, x1, y1]")

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def as_rounded(self, digits: int = 1) -> list[float]:
        return [round(v, digits) for v in self.as_list()]

    def clamp(self, width: int, height: int) -> "BBox":
        x0 = min(max(self.x0, 0.0), float(width))
        y0 = min(max(self.y0, 0.0), float(height))
        x1 = min(max(self.x1, 0.0), float(width))
        y1 = min(max(self.y1, 0.0), float(height))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)

    def intersect(self, other: "BBox") -> "BBox | None":
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)

    def iou(self, other: "BBox") -> float:
        inter = self.intersect(other)
        if inter is None:
            return 0.0
        union = self.area + other.area - inter.area
        return inter.area / union if union > 0 else 0.0

    def contains(self, other: "BBox", tolerance: float = 0.0) -> bool:
        return (
            other.x0 >= self.x0 - tolerance
            and other.y0 >= self.y0 - tolerance
            and other.x1 <= self.x1 + tolerance
            and other.y1 <= self.y1 + tolerance
        )

    def center_inside(self, other: "BBox") -> bool:
        cx, cy = self.center
        return other.x0 <= cx <= other.x1 and other.y0 <= cy <= other.y1

    def expand(self, pad: float) -> "BBox":
        return BBox(x0=self.x0 - pad, y0=self.y0 - pad, x1=self.x1 + pad, y1=self.y1 + pad)

    def gap(self, other: "BBox") -> tuple[float, float]:
        """Horizontal and vertical gap between boxes (0 when overlapping on that axis)."""
        gx = max(0.0, max(self.x0, other.x0) - min(self.x1, other.x1))
        gy = max(0.0, max(self.y0, other.y0) - min(self.y1, other.y1))
        return gx, gy


class Provenance(BaseModel):
    """Where a piece of evidence came from and how it was produced."""

    module: str
    method: str
    version: str = SCHEMA_VERSION
    params: dict[str, Any] = Field(default_factory=dict)
    produced_at: datetime = Field(default_factory=utc_now)

    def model_dump_jsonable(self) -> dict[str, Any]:
        data = self.model_dump()
        data["produced_at"] = self.produced_at.isoformat()
        return data


class Evidence(BaseModel):
    evidence_id: str
    image_id: str
    kind: EvidenceKind
    label: str
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance
    observed: bool = True
    scope: str = "image"  # "image" | "region"

    @property
    def is_inferred(self) -> bool:
        return not self.observed

    def compact(self, detail: str = "standard") -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.evidence_id,
            "kind": self.kind.value,
            "label": self.label,
        }
        if self.bbox is not None:
            data["bbox"] = self.bbox.as_rounded()
        if self.confidence is not None:
            data["confidence"] = round(self.confidence, 3)
        if detail != "compact":
            attrs = self.attributes
            if detail == "standard":
                attrs = _trim_attributes(attrs)
            if attrs:
                data["attributes"] = attrs
            if not self.observed:
                data["observed"] = False
        return data

    def model_dump_jsonable(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["provenance"]["produced_at"] = self.provenance.produced_at.isoformat()
        if self.bbox is not None:
            data["bbox"] = self.bbox.as_list()
        return data


_HIDDEN_ATTRS = {"mask", "contour", "points", "raw", "embedding"}


def _trim_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key, value in attrs.items():
        if key in _HIDDEN_ATTRS:
            continue
        if isinstance(value, float):
            trimmed[key] = round(value, 3)
        elif isinstance(value, (list, tuple)) and len(value) > 24:
            trimmed[key] = list(value[:24])
        elif isinstance(value, dict):
            trimmed[key] = _trim_attributes(value)
        else:
            trimmed[key] = value
    return trimmed


def make_evidence_id(
    image_id: str,
    kind: EvidenceKind | str,
    module: str,
    method: str,
    label: str,
    bbox: BBox | None,
    discriminator: str = "",
) -> str:
    key = {
        "image": image_id,
        "kind": kind.value if isinstance(kind, EvidenceKind) else kind,
        "module": module,
        "method": method,
        "label": label,
        "bbox": bbox.as_rounded(2) if bbox else None,
        "disc": discriminator,
    }
    digest = hashlib.sha1(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()
    prefix = (kind.value if isinstance(kind, EvidenceKind) else kind)[:4]
    return f"{prefix}_{digest[:12]}"


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"


class VerificationMeasurement(BaseModel):
    name: str
    subject: str
    value: Any
    expected: Any | None = None
    delta: float | None = None
    unit: str = ""
    tolerance: float | None = None


class VerificationResult(BaseModel):
    claim: str
    status: ClaimStatus
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    measurements: list[VerificationMeasurement] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    method: str = "rule_based"

    def summary(self) -> str:
        return f"{self.status.value.upper()}: {self.explanation}"
