"""Coordinate mapping between a working canvas and original image pixels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..schemas import BBox


@dataclass(frozen=True)
class CoordinateMapper:
    """Maps working-canvas coordinates back to original image pixels.

    original = offset + working / scale
    """

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    original_width: int = 0
    original_height: int = 0

    def to_original_bbox(self, x0: float, y0: float, x1: float, y1: float) -> BBox:
        inv = 1.0 / self.scale if self.scale else 1.0
        box = BBox(
            x0=self.offset_x + x0 * inv,
            y0=self.offset_y + y0 * inv,
            x1=self.offset_x + x1 * inv,
            y1=self.offset_y + y1 * inv,
        )
        if self.original_width and self.original_height:
            return box.clamp(self.original_width, self.original_height)
        return box

    def to_working_bbox(self, x0: float, y0: float, x1: float, y1: float) -> BBox:
        """Inverse of to_original_bbox: original pixels -> working canvas."""
        scale = self.scale if self.scale else 1.0
        return BBox(
            x0=(x0 - self.offset_x) * scale,
            y0=(y0 - self.offset_y) * scale,
            x1=(x1 - self.offset_x) * scale,
            y1=(y1 - self.offset_y) * scale,
        )

    def to_original_point(self, x: float, y: float) -> tuple[float, float]:
        inv = 1.0 / self.scale if self.scale else 1.0
        return (self.offset_x + x * inv, self.offset_y + y * inv)

    def scale_length(self, length: float) -> float:
        return length / self.scale if self.scale else length


@dataclass
class WorkingImage:
    bgr: np.ndarray
    mapper: CoordinateMapper
    region: BBox | None = None  # original-pixel region this canvas covers


def make_working_image(
    bgr: np.ndarray,
    original_width: int,
    original_height: int,
    max_dim: int,
    region: BBox | None = None,
    upscale: float | None = None,
) -> WorkingImage:
    """Downscale/upscale a canvas while keeping a mapping to original pixels.

    `bgr` is either the full image or a crop taken from `region` of the original.
    """
    height, width = bgr.shape[:2]
    scale = 1.0
    if upscale and upscale > 1.0:
        scale = min(float(upscale), 4.0)
    elif max(width, height) > max_dim:
        scale = max_dim / float(max(width, height))
    if abs(scale - 1.0) > 1e-6:
        interpolation = cv2_interp(scale)
        bgr = resize(bgr, scale, interpolation)
    if region is not None:
        mapper = CoordinateMapper(
            scale=scale,
            offset_x=region.x0,
            offset_y=region.y0,
            original_width=original_width,
            original_height=original_height,
        )
    else:
        mapper = CoordinateMapper(
            scale=scale,
            offset_x=0.0,
            offset_y=0.0,
            original_width=original_width,
            original_height=original_height,
        )
    return WorkingImage(bgr=bgr, mapper=mapper, region=region)


def resize(bgr: np.ndarray, scale: float, interpolation: int) -> np.ndarray:
    import cv2

    height, width = bgr.shape[:2]
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(bgr, new_size, interpolation=interpolation)


def cv2_interp(scale: float) -> int:
    import cv2

    return cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
