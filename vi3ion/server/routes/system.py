from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config import get_settings
from ...core.engine import Vi3ionEngine
from ..deps import get_engine

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    return engine.health()


@router.get("/config")
def config(engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    settings = get_settings()
    return {
        "version": "0.1.0",
        "host": settings.host,
        "port": settings.port,
        "data_dir": str(settings.data_dir),
        "limits": {
            "max_image_bytes": settings.max_image_bytes,
            "max_image_pixels": settings.max_image_pixels,
            "analysis_max_dim": settings.analysis_max_dim,
            "thumbnail_max_dim": settings.thumbnail_max_dim,
        },
        "allowed_roots": [str(path) for path in settings.allowed_roots],
        "ocr": {"enabled": settings.ocr_enabled, "min_confidence": settings.ocr_min_confidence},
        "semantic": {
            "provider": settings.semantic_provider,
            "model": settings.semantic_model or None,
            "remote_enabled": settings.semantic_provider == "remote",
        },
        "coordinate_space": "original_pixels",
    }


@router.get("/stats")
def stats(engine: Vi3ionEngine = Depends(get_engine)) -> dict:
    return {
        "images": engine.db.count_images(),
        "evidence": engine.db.total_evidence(),
    }
