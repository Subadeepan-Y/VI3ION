"""Request models shared by the HTTP API and the MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DetailLevel = Literal["compact", "standard", "full"]

TASK_CHOICES = (
    "describe",
    "extract_text",
    "detect_layout",
    "identify_elements",
    "inspect_alignment",
    "analyze_colors",
)


class AnalyzeRequest(BaseModel):
    image_id: str | None = None
    path: str | None = None
    tasks: list[str] = Field(default_factory=list)
    detail: DetailLevel = "standard"
    force: bool = False

    @field_validator("tasks")
    @classmethod
    def _known_tasks(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in TASK_CHOICES]
        if unknown:
            raise ValueError(f"unknown task(s) {unknown}; allowed: {list(TASK_CHOICES)}")
        return value


class InspectRegionRequest(BaseModel):
    image_id: str
    region: list[float] = Field(description="[x0, y0, x1, y1] in original pixels")
    tasks: list[str] = Field(default_factory=list)
    detail: DetailLevel = "standard"
    padding: float = 0.0
    upscale: float | None = Field(default=None, ge=1.0, le=4.0)

    @field_validator("region")
    @classmethod
    def _four_numbers(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("region must be [x0, y0, x1, y1]")
        return value


class QueryEvidenceRequest(BaseModel):
    image_id: str
    kind: str | None = None
    text_contains: str | None = None
    region: list[float] | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    detail: DetailLevel = "standard"


class VerifyClaimRequest(BaseModel):
    image_id: str
    claim: str | dict[str, Any]


class CompareRegionsRequest(BaseModel):
    image_id: str
    region_a: list[float]
    region_b: list[float]
    aspects: list[str] = Field(default_factory=lambda: ["position", "size", "color", "text"])

    @field_validator("region_a", "region_b")
    @classmethod
    def _four_numbers(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("region must be [x0, y0, x1, y1]")
        return value


class CropRequest(BaseModel):
    image_id: str
    region: list[float]
    pad: float = 0.0
    scale: float = Field(default=1.0, ge=0.1, le=4.0)
    max_dim: int = Field(default=1600, ge=64, le=4096)


class IngestPathRequest(BaseModel):
    path: str
    analyze: bool = False
    detail: DetailLevel = "standard"
