"""Generic tool endpoints. The dashboard simulator and external clients use these.

They expose the same five operations as the MCP server, nothing more.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.engine import Vi3ionEngine
from ...schemas import (
    AnalyzeRequest,
    CompareRegionsRequest,
    InspectRegionRequest,
    QueryEvidenceRequest,
    VerifyClaimRequest,
    ToolResponse,
)
from ..deps import get_engine

router = APIRouter(prefix="/api/tools", tags=["tools"])

TOOL_CATALOG = [
    {
        "name": "inspect_image",
        "description": "Initial analysis of an image, by image_id or filesystem path. Returns OCR, geometry, colours, layout and (optionally) semantic objects.",
        "arguments": {
            "image_id": "string (optional if path given)",
            "path": "string (optional if image_id given)",
            "tasks": ["describe", "extract_text", "detect_layout", "identify_elements", "analyze_colors", "inspect_alignment"],
            "detail": ["compact", "standard", "full"],
            "force": "boolean",
        },
    },
    {
        "name": "inspect_region",
        "description": "Re-run perception on a crop, with coordinates mapped back to the original image.",
        "arguments": {
            "image_id": "string",
            "region": "[x0, y0, x1, y1] in original pixels",
            "tasks": "array",
            "padding": "pixels",
            "upscale": "float 1-4",
            "detail": ["compact", "standard", "full"],
        },
    },
    {
        "name": "query_evidence",
        "description": "Retrieve stored evidence with filters. Use this instead of re-analysing.",
        "arguments": {
            "image_id": "string",
            "kind": ["image", "text", "shape", "color", "object", "relationship", "verification", "note"],
            "text_contains": "string",
            "region": "[x0, y0, x1, y1]",
            "min_confidence": "0-1",
            "limit": "1-500",
            "offset": "integer",
        },
    },
    {
        "name": "verify_claim",
        "description": "Check a claim against measurements. Returns verified, contradicted or inconclusive.",
        "arguments": {
            "image_id": "string",
            "claim": "string or structured claim object",
        },
    },
    {
        "name": "compare_regions",
        "description": "Compare two regions on position, size, colour, text and structure.",
        "arguments": {
            "image_id": "string",
            "region_a": "[x0, y0, x1, y1]",
            "region_b": "[x0, y0, x1, y1]",
            "aspects": ["position", "size", "color", "text", "structure"],
        },
    },
]


@router.get("")
def catalog() -> dict:
    return {"tools": TOOL_CATALOG, "protocol": "mcp", "coordinate_space": "original_pixels"}


@router.post("/inspect_image")
def inspect_image(body: AnalyzeRequest, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    response = engine.inspect_image(
        image_id=body.image_id,
        path=body.path,
        tasks=body.tasks,
        detail=body.detail,
        force=body.force,
    )
    return _payload(response, body.detail)


@router.post("/inspect_region")
def inspect_region(body: InspectRegionRequest, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    response = engine.inspect_region(
        image_id=body.image_id,
        region=body.region,
        tasks=body.tasks,
        detail=body.detail,
        padding=body.padding,
        upscale=body.upscale,
    )
    return _payload(response, body.detail)


@router.post("/query_evidence")
def query_evidence(body: QueryEvidenceRequest, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    response = engine.query_evidence(
        image_id=body.image_id,
        kind=body.kind,
        text_contains=body.text_contains,
        region=body.region,
        min_confidence=body.min_confidence,
        limit=body.limit,
        offset=body.offset,
        detail=body.detail,
    )
    return _payload(response, body.detail)


@router.post("/verify_claim")
def verify_claim(body: VerifyClaimRequest, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    response = engine.verify_claim(image_id=body.image_id, claim=body.claim)
    return _payload(response, "standard")


@router.post("/compare_regions")
def compare_regions(body: CompareRegionsRequest, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    response = engine.compare_regions(
        image_id=body.image_id,
        region_a=body.region_a,
        region_b=body.region_b,
        aspects=body.aspects,
    )
    return _payload(response, "standard")


def _payload(response: ToolResponse, detail: str) -> dict:
    payload = response.to_payload(detail)
    payload["_meta"] = {
        "coordinate_space": "original_pixels",
        "cached": response.cached,
        "evidence_total": response.evidence_total,
        "evidence_returned": response.evidence_returned,
        "truncated": response.truncated,
    }
    return payload
