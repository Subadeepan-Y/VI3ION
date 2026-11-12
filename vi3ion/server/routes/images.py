from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ...config import get_settings
from ...core.engine import Vi3ionEngine
from ...errors import ValidationError
from ...schemas import AnalyzeRequest, CompareRegionsRequest, InspectRegionRequest, ToolResponse
from ..deps import get_engine

router = APIRouter(prefix="/api/images", tags=["images"])


def public_image(record: dict) -> dict:
    image_id = record["image_id"]
    return {
        "image_id": image_id,
        "width": record["width"],
        "height": record["height"],
        "format": record["format"],
        "size_bytes": record["size_bytes"],
        "created_at": record["created_at"],
        "source": record.get("source"),
        "meta": record.get("meta", {}),
        "evidence_count": record.get("evidence_count"),
        "file_url": f"/api/images/{image_id}/file",
        "thumbnail_url": f"/api/images/{image_id}/thumbnail",
    }


@router.post("")
async def upload(
    file: UploadFile = File(...),
    analyze: bool = Query(default=True),
    detail: str = Query(default="standard"),
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    settings = get_settings()
    data = await file.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise ValidationError(
            f"image exceeds {settings.max_image_bytes} bytes; increase VI3ION_MAX_IMAGE_BYTES to allow it"
        )
    record, deduplicated = engine.ingest_bytes(data, filename=file.filename)
    payload: dict = {"image": public_image(record), "deduplicated": deduplicated}
    if analyze:
        response = engine.inspect_image(image_id=record["image_id"], detail=detail)
        payload["analysis"] = response.to_payload(detail)
    return payload


@router.get("")
def list_images(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    records = engine.list_images(limit=limit, offset=offset)
    return {
        "images": [public_image(record) for record in records],
        "total": engine.db.count_images(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{image_id}")
def get_image(image_id: str, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    record = engine.get_record(image_id)
    record["evidence_count"] = engine.db.evidence_count(image_id)
    sessions = engine.db.list_sessions(image_id, limit=5)
    jobs = engine.db.list_jobs(image_id, limit=5)
    return {"image": public_image(record), "sessions": sessions, "jobs": jobs}


@router.delete("/{image_id}")
def delete_image(image_id: str, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    engine.delete_image(image_id)
    return {"ok": True, "deleted": image_id}


@router.get("/{image_id}/file")
def original_file(image_id: str, engine: Vi3ionEngine = Depends(get_engine)):
    from fastapi.responses import Response

    record = engine.get_record(image_id)
    media = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
        "BMP": "image/bmp",
        "TIFF": "image/tiff",
        "GIF": "image/gif",
    }.get(record["format"], "application/octet-stream")
    return Response(
        content=engine.image_bytes(image_id),
        media_type=media,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{image_id}/thumbnail")
def thumbnail(image_id: str, engine: Vi3ionEngine = Depends(get_engine)):
    from fastapi.responses import Response

    return Response(
        content=engine.thumbnail_bytes(image_id),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{image_id}/crop")
def crop(
    image_id: str,
    x0: float = Query(...),
    y0: float = Query(...),
    x1: float = Query(...),
    y1: float = Query(...),
    pad: float = Query(default=0),
    scale: float = Query(default=1.0, ge=0.1, le=4.0),
    max_dim: int = Query(default=1600, ge=64, le=4096),
    engine: Vi3ionEngine = Depends(get_engine),
):
    from fastapi.responses import Response

    content, _bbox = engine.crop_png(
        image_id, [x0, y0, x1, y1], pad=pad, scale=scale, max_dim=max_dim
    )
    return Response(content=content, media_type="image/png")


@router.get("/{image_id}/evidence")
def evidence(
    image_id: str,
    kind: str | None = Query(default=None),
    text_contains: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    rows, total = engine.db.query_evidence(
        image_id,
        kind=kind,
        text_contains=text_contains,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    kind_counts: dict[str, int] = {}
    for row in rows:
        kind_counts[row["kind"]] = kind_counts.get(row["kind"], 0) + 1
    return {
        "image_id": image_id,
        "evidence": [
            engine._row_to_evidence(row).model_dump_jsonable() for row in rows
        ],
        "total": total,
        "kind_counts": kind_counts,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{image_id}/analyze")
def analyze(
    image_id: str,
    body: AnalyzeRequest,
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    if body.image_id and body.image_id != image_id:
        raise ValidationError("image_id in path and body differ")
    response = engine.inspect_image(
        image_id=image_id, tasks=body.tasks, detail=body.detail, force=body.force
    )
    return _tool_payload(response, body.detail)


@router.post("/{image_id}/regions/inspect")
def inspect_region(
    image_id: str,
    body: InspectRegionRequest,
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    if body.image_id != image_id:
        raise ValidationError("image_id in path and body differ")
    response = engine.inspect_region(
        image_id=image_id,
        region=body.region,
        tasks=body.tasks,
        detail=body.detail,
        padding=body.padding,
        upscale=body.upscale,
    )
    return _tool_payload(response, body.detail)


@router.post("/{image_id}/verify")
def verify(
    image_id: str,
    body: dict,
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    claim = body.get("claim", body)
    if not claim:
        raise ValidationError("claim is required")
    response = engine.verify_claim(image_id=image_id, claim=claim, detail=body.get("detail", "standard"))
    return _tool_payload(response, body.get("detail", "standard"))


@router.post("/{image_id}/compare")
def compare(
    image_id: str,
    body: CompareRegionsRequest,
    engine: Vi3ionEngine = Depends(get_engine),
) -> dict:
    response = engine.compare_regions(
        image_id=image_id,
        region_a=body.region_a,
        region_b=body.region_b,
        aspects=body.aspects,
    )
    return _tool_payload(response, "standard")


@router.get("/{image_id}/jobs")
def jobs(image_id: str, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    engine.get_record(image_id)
    return {"jobs": engine.list_jobs(image_id)}


@router.get("/{image_id}/inspections")
def inspections(image_id: str, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    engine.get_record(image_id)
    return {"inspections": engine.list_inspections(image_id)}


@router.get("/{image_id}/graph")
def graph(image_id: str, engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    """Return the latest scene graph stored in the cached full analysis."""
    engine.get_record(image_id)
    rows, _ = engine.db.query_evidence(image_id, kind="note", limit=20)
    for row in rows:
        if row["label"] == "scene summary":
            return {"image_id": image_id, "summary": row["attributes"]}
    return {"image_id": image_id, "summary": None}


def _tool_payload(response: ToolResponse, detail: str) -> dict:
    return response.to_payload(detail)
