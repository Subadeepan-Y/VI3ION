"""Semantic vision interface. Replaceable by design; never used for measurement.

Contract
-------
- Providers receive the working-canvas image (BGR) and optional region boxes in
  the SAME coordinate frame as that image. They return boxes in that same
  frame; the engine maps them back to original pixels via the CoordinateMapper.
- Detections are `objects`, region-level descriptions are `captions`,
  whole-image tags are `scene_tags`. Every item carries a `source` naming the
  model that produced it.
- `error` is populated when a provider could not run (missing weights, missing
  dependency). Warnings are advisory; errors mean no output was produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ...schemas import BBox


@dataclass
class SemanticObject:
    label: str
    bbox: BBox | None = None  # input-image frame; engine maps to original
    confidence: float = 0.5
    source: str = ""


@dataclass
class SemanticCaption:
    text: str
    bbox: BBox | None = None
    confidence: float = 0.5
    source: str = ""


@dataclass
class SceneTag:
    tag: str
    confidence: float = 0.5
    source: str = ""


@dataclass
class SemanticResult:
    objects: list[SemanticObject] = field(default_factory=list)
    captions: list[SemanticCaption] = field(default_factory=list)
    scene_tags: list[SceneTag] = field(default_factory=list)
    error: str | None = None
    warning: str | None = None
    provider: str = "none"
    model: str | None = None
    duration_ms: float = 0.0


class SemanticProvider(Protocol):
    name: str
    version: str

    def detect(
        self,
        image: np.ndarray,
        regions: list[BBox] | None = None,
    ) -> SemanticResult: ...
