"""Vi3ion engine: the only place that orchestrates perception modules.

The engine is agent-independent. HTTP routes and MCP tools are thin adapters
over this class.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import Settings, get_settings
from ..errors import NotFoundError, ValidationError
from ..image_memory import (
    SIGNATURE_VERSION,
    diff_images as diff_signatures,
    perceptual_hash_from_path,
    similarity,
    signature_from_evidence,
    text_similarity,
)
from ..schemas import (    BBox,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    Provenance,
    SCHEMA_VERSION,
    TASK_CHOICES,
    ToolResponse,
    VerificationResult,
    make_evidence_id,
)
from ..storage import Database, ImageStore
from ..visual_diff import describe_visual, visual_diff
from .coordinates import WorkingImage, make_working_image
from .geometry import analyze_geometry
from .geometry.measurements import relative_position
from .ingestion import ImageLoader
from .ocr import analyze_ocr, get_ocr_provider
from .pixels import analyze_pixels, dominant_colors, image_statistics
from .semantics import create_providers
from .semantics.merge import merge
from .semantics.pipeline import analyze_semantics
from .spatial import build_scene
from .summary import summarize, summarize_region
from .verification import ClaimVerifier

DEFAULT_TASKS = ["describe", "extract_text", "detect_layout", "identify_elements", "analyze_colors"]
ANALYSIS_MODULES = ["pixels", "geometry", "ocr", "spatial", "semantics"]

DETAIL_LIMITS = {"compact": 10, "standard": 0, "full": 250}


import logging

logger = logging.getLogger("vi3ion.engine")


class Vi3ionEngine:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.db = Database(self.settings.db_path)
        self.db.init()
        self.store = ImageStore(self.settings)
        self.loader = ImageLoader(self.settings, self.db, self.store)
        self._ocr_available: bool | None = None

    # --------------------------------------------------------------- ingestion
    def ingest_bytes(self, data: bytes, filename: str | None = None) -> tuple[dict, bool]:
        return self.loader.ingest_bytes(data, filename=filename)

    def ingest_path(self, path: str) -> tuple[dict, bool]:
        return self.loader.ingest_path(path)

    def get_record(self, image_id: str) -> dict:
        record = self.db.get_image(image_id)
        if not record:
            raise NotFoundError(f"image {image_id!r} not found")
        return record

    def prune_missing(self, limit: int = 1000) -> list[str]:
        """Remove images whose stored file no longer exists.

        Returns the ids that were pruned.
        """
        pruned: list[str] = []
        for record in self.db.list_images(limit=limit):
            original = record.get("original_path")
            if not original or Path(original).exists():
                continue
            try:
                self.delete_image(record["image_id"])
            except Exception:  # noqa: BLE001 - pruning must never crash
                continue
            pruned.append(record["image_id"])
        return pruned

    def list_images(self, limit: int = 100, offset: int = 0) -> list[dict]:
        records = self.db.list_images(limit=limit, offset=offset)
        for record in records:
            record["evidence_count"] = self.db.evidence_count(record["image_id"])
        return records

    def delete_image(self, image_id: str) -> None:
        record = self.get_record(image_id)
        self.store.delete(record)
        self.db.delete_image(image_id)

    # ----------------------------------------------------------- image memory
    def _register_signature(self, record: dict, evidence: list) -> dict:
        signature = signature_from_evidence(
            evidence, record["width"], record["height"]
        )
        # Perceptual hash: recognises the same screen even when the wording
        # changed, which an OCR fingerprint cannot.
        original = record.get("original_path")
        if original:
            phash = perceptual_hash_from_path(original)
            if phash:
                signature["phash"] = phash
        self.db.upsert_image_registry(record["image_id"], signature)
        return signature

    def _similar_images(
        self, image_id: str, signature: dict, limit: int = 5
    ) -> list[dict[str, Any]]:
        threshold = float(self.settings.image_similarity_threshold)
        candidates: list[dict[str, Any]] = []
        for row in self.db.list_image_registry(limit=250):
            if row["image_id"] == image_id:
                continue
            other = row.get("signature") or {}
            if not other:
                continue
            score = similarity(signature, other)
            if score < threshold:
                continue
            record = self.db.get_image(row["image_id"]) or {}
            candidates.append(
                {
                    "image_id": row["image_id"],
                    "label": row.get("label") or "",
                    "path": record.get("original_path"),
                    "width": record.get("width"),
                    "height": record.get("height"),
                    "similarity": round(score, 3),
                    "text_similarity": round(
                        text_similarity(signature, other), 3
                    ),
                    "created_at": row.get("created_at"),
                }
            )
        candidates.sort(key=lambda c: c["similarity"], reverse=True)
        return candidates[:limit]

    def list_known_images(self, limit: int = 100) -> list[dict[str, Any]]:
        """Registry view: labelled images plus their identity metadata."""
        known: list[dict[str, Any]] = []
        for row in self.db.list_image_registry(limit=limit):
            record = self.db.get_image(row["image_id"]) or {}
            signature = row.get("signature") or {}
            known.append(
                {
                    "image_id": row["image_id"],
                    "label": row.get("label") or "",
                    "path": record.get("original_path"),
                    "width": record.get("width"),
                    "height": record.get("height"),
                    "text_count": row.get("text_count", 0),
                    "signature": signature.get("signature", ""),
                    "phash": signature.get("phash", ""),
                    "created_at": row.get("created_at"),
                }
            )
        return known

    def remember_image(self, image_id: str, label: str) -> ToolResponse:
        """Attach a human/agent label to an image in the registry."""
        label = (label or "").strip()
        if not label:
            raise ValidationError("label must not be empty")
        record = self.get_record(image_id)
        if not self.db.get_image_registry(image_id):
            self.inspect_image(image_id=image_id, detail="compact", agent="mcp")
        if not self.db.set_image_label(image_id, label):
            self.db.upsert_image_registry(image_id, {}, label=label)
        registry = self.db.get_image_registry(image_id) or {}
        signature = registry.get("signature") or {}
        return ToolResponse(
            tool="remember_image",
            image_id=image_id,
            summary=f'Image labelled "{label}".',
            data={
                "image_id": image_id,
                "label": label,
                "path": record.get("original_path"),
                "text_count": registry.get("text_count", 0),
                "signature": signature.get("signature", ""),
            },
        )

    def diff_images(self, older_id: str, newer_id: str) -> ToolResponse:
        """Compare two stored images and report observed differences."""
        older_record = self.get_record(older_id)
        newer_record = self.get_record(newer_id)
        for image_id in (older_id, newer_id):
            registry = self.db.get_image_registry(image_id)
            version = (registry.get("signature") or {}).get("version", 0) if registry else 0
            if registry is None or version < SIGNATURE_VERSION:
                self.inspect_image(image_id=image_id, detail="compact", agent="mcp")
        older_reg = self.db.get_image_registry(older_id) or {}
        newer_reg = self.db.get_image_registry(newer_id) or {}
        older_sig = older_reg.get("signature") or {}
        newer_sig = newer_reg.get("signature") or {}
        if not older_sig or not newer_sig:
            raise ValidationError(
                "could not build image signatures; analyse both images first"
            )

        result = diff_signatures(older_sig, newer_sig)

        # Pixel-level comparison: text diffs miss colour and layout changes.
        visual: dict[str, Any] = {"available": False, "reason": "not attempted"}
        older_path = older_record.get("original_path")
        newer_path = newer_record.get("original_path")
        if older_path and newer_path and Path(older_path).exists() and Path(newer_path).exists():
            visual = visual_diff(older_path, newer_path)

        return ToolResponse(
            tool="diff_images",
            image_id=newer_id,
            summary=(
                f"{result['change_count']} change(s) between versions; "
                f"overall similarity {result['overall_similarity'] * 100:.1f}% "
                f"(layout {result['layout_similarity'] * 100:.0f}%, "
                f"text {result['text_similarity'] * 100:.0f}%)."
            ),
            data={
                "older": {
                    "image_id": older_id,
                    "label": older_reg.get("label") or "",
                    "path": older_record.get("original_path"),
                    "width": older_record.get("width"),
                    "height": older_record.get("height"),
                },
                "newer": {
                    "image_id": newer_id,
                    "label": newer_reg.get("label") or "",
                    "path": newer_record.get("original_path"),
                    "width": newer_record.get("width"),
                    "height": newer_record.get("height"),
                },
                "diff": result,
                "visual": visual,
                "visual_summary": describe_visual(visual),
            },
            next_actions=[
                "Confirm each reported change against the codebase or commit diff before telling the user it changed.",
                "If the two images may be different screens, say so: identity is a similarity suggestion, not a measurement.",
                "Use cross_check_text() for any changed label that looks misread by OCR.",
            ],
        )

    def image_bytes(self, image_id: str) -> bytes:
        return self.loader.read_bytes(self.get_record(image_id))

    def thumbnail_bytes(self, image_id: str) -> bytes:
        record = self.get_record(image_id)
        path = record.get("thumbnail_path")
        if not path or not Path(path).exists():
            prepared = self.loader.prepare(record)
            return _encode_png(prepared.bgr)
        return Path(path).read_bytes()

    def crop_png(
        self,
        image_id: str,
        region: list[float],
        pad: float = 0.0,
        scale: float = 1.0,
        max_dim: int = 1600,
    ) -> tuple[bytes, list[float]]:
        record = self.get_record(image_id)
        prepared = self.loader.prepare(record)
        bbox = self._bbox(region, record).expand(pad).clamp(record["width"], record["height"])
        x0, y0, x1, y1 = (int(round(v)) for v in bbox.as_list())
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise ValidationError("crop region is empty")
        crop = prepared.bgr[y0:y1, x0:x1].copy()
        crop = _resize_to(crop, scale=scale, max_dim=max_dim)
        path = self.store.save_crop(image_id, _encode_png(crop), f"{bbox.as_rounded()}:{scale}:{max_dim}")
        return Path(path).read_bytes(), bbox.as_rounded(1)

    # ------------------------------------------------------------------- tools
    def inspect_image(
        self,
        image_id: str | None = None,
        path: str | None = None,
        tasks: list[str] | None = None,
        detail: str = "standard",
        force: bool = False,
        session_id: str | None = None,
        agent: str = "unknown",
        context: str | None = None,
    ) -> ToolResponse:
        started = time.perf_counter()
        if path and not image_id:
            record, deduplicated = self.loader.ingest_path(path)
        elif image_id:
            record = self.get_record(image_id)
            deduplicated = False
        else:
            raise ValidationError("provide either image_id or a filesystem path to inspect")

        tasks = self._validate_tasks(tasks)
        session_id = session_id or self.ensure_session(record["image_id"], agent=agent)
        cache_key = self._cache_key(
            "inspect_image",
            {
                "image_id": record["image_id"],
                "tasks": "default" if not tasks else sorted(tasks),
                "ocr": self.settings.ocr_enabled,
                "semantic": self.settings.semantic_provider,
                "semantic_model": self.settings.semantic_model,
                "max_dim": self.settings.analysis_max_dim,
                "schema": SCHEMA_VERSION,
                "context": (context or "").strip(),
                "code_roots": sorted(str(r) for r in self.settings.code_roots),
            },
        )

        if not force:
            cached = self.db.get_cache(cache_key)
            if cached:
                response = ToolResponse.model_validate(cached)
                response.cached = True
                response.timings_ms = {"total_ms": (time.perf_counter() - started) * 1000.0, "cache_hit": 1.0}
                self.db.touch_session(session_id, record["image_id"])
                # Older analyses may predate the image registry; backfill the
                # identity signature from cached evidence. Upgrade old signature
                # versions so labels and layout data are current.
                registry = self.db.get_image_registry(record["image_id"])
                if registry is None or (
                    registry.get("signature") or {}
                ).get("version", 0) < SIGNATURE_VERSION:
                    signature = self._register_signature(record, response.evidence)
                else:
                    signature = registry.get("signature") or {}
                if signature:
                    context = response.data.setdefault("analysis", {}).setdefault(
                        "context", {}
                    )
                    context["similar_images"] = self._similar_images(
                        record["image_id"], signature
                    )
                return self._apply_detail(response, detail)

        job_id = self.db.create_job(record["image_id"], "inspect_image", tasks)
        job_started = time.perf_counter()
        try:
            prepared = self.loader.prepare(record)
            timings: dict[str, float] = {}
            stage = time.perf_counter()
            working = make_working_image(
                prepared.bgr,
                record["width"],
                record["height"],
                self.settings.analysis_max_dim,
            )
            timings["prepare_ms"] = (time.perf_counter() - stage) * 1000.0

            stage = time.perf_counter()
            pixels = analyze_pixels(working, record["image_id"])
            timings["pixels_ms"] = (time.perf_counter() - stage) * 1000.0

            stage = time.perf_counter()
            geometry = analyze_geometry(working, record["image_id"])
            timings["geometry_ms"] = (time.perf_counter() - stage) * 1000.0

            run_ocr = self.settings.ocr_enabled and (
                not tasks or "extract_text" in tasks or "describe" in tasks or "identify_elements" in tasks
            )
            stage = time.perf_counter()
            if run_ocr:
                ocr = analyze_ocr(
                    working,
                    record["image_id"],
                    enabled=True,
                    min_confidence=self.settings.ocr_min_confidence,
                )
            else:
                from .ocr.pipeline import OCRResult

                ocr = OCRResult(warning="OCR skipped: task list did not request text")
            timings["ocr_ms"] = (time.perf_counter() - stage) * 1000.0

            if run_ocr and context and context.strip() and not self.settings.low_resource:
                from vi3ion.attention import attention_relook
                from vi3ion.code_verify import hint_terms

                context_terms = hint_terms(context)
                if context_terms:
                    stage = time.perf_counter()
                    _updated, attention_ms = attention_relook(
                        working.bgr, ocr.lines, context_terms
                    )
                    timings["attention_ms"] = attention_ms
                    if _updated:
                        logger.info("attention relook updated %d line(s)", _updated)

            providers = create_providers(self.settings)
            run_semantics = bool(providers) and (
                not tasks or "identify_elements" in tasks or "describe" in tasks
            )
            stage = time.perf_counter()
            if run_semantics:
                region_boxes = [e.bbox for e in geometry.evidence if e.bbox is not None]
                semantics = analyze_semantics(
                    working, record["image_id"], providers, regions=region_boxes
                )
            else:
                from .semantics.pipeline import SemanticResult

                warning = None
                if not providers:
                    warning = "semantic provider disabled (deterministic evidence only)"
                else:
                    warning = "semantic pass skipped: task list did not request identification"
                semantics = SemanticResult(warning=warning)
            timings["semantics_ms"] = (time.perf_counter() - stage) * 1000.0

            stage = time.perf_counter()
            combined = [*pixels.evidence, *geometry.evidence, *ocr.evidence, *semantics.evidence]
            combined = _drop_text_glyphs(combined)
            _attach_element_colors(combined, working)
            spatial = build_scene(
                record["image_id"], combined, record["width"], record["height"]
            )
            timings["spatial_ms"] = (time.perf_counter() - stage) * 1000.0
            all_evidence = [*combined, *spatial.evidence]

            context_info: dict[str, Any] = {
                "echo": (context or "").strip(),
                "terms": [],
                "code_matches": [],
                "path_candidates": [],
                "similar_images": [],
            }
            if context and context.strip() and self.settings.code_roots:
                from vi3ion.code_verify import (
                    context_code_matches,
                    get_code_index,
                    hint_terms,
                )

                ctx_index = get_code_index(self.settings.code_roots)
                context_info["terms"] = hint_terms(context)[:20]
                matches = context_code_matches(context, ctx_index)
                context_info["code_matches"] = [
                    {
                        "file": m.file,
                        "line": m.line,
                        "snippet": m.snippet[:160],
                        "score": round(m.score, 2),
                    }
                    for m in matches
                ]
            # Navigation hints: file-path-like strings visible in the image,
            # extracted from OCR lines. These let a vision-less agent open the
            # right file directly.
            from vi3ion.path_hints import path_candidates

            context_info["path_candidates"] = path_candidates(
                [line.text for line in ocr.lines], limit=10
            )
            signature = self._register_signature(record, all_evidence)
            context_info["similar_images"] = self._similar_images(
                record["image_id"], signature
            )
            context_match_count = len(context_info["code_matches"])
            path_hint_count = len(context_info["path_candidates"])

            self.db.delete_evidence(record["image_id"], modules=ANALYSIS_MODULES, scope="image")
            self.db.upsert_evidence(all_evidence, job_id)

            warnings = [w for w in (ocr.warning, semantics.warning) if w]
            if deduplicated:
                warnings.append("identical image content already stored; reusing existing image id")
            similar_images = context_info["similar_images"]
            if similar_images:
                best = similar_images[0]
                label = f' ("{best["label"]}")' if best.get("label") else ""
                warnings.append(
                    "image looks like a previously seen image%s (similarity %.0f%%); "
                    "use diff_images to compare versions"
                    % (label, best["similarity"] * 100)
                )
            if context_match_count:
                warnings.append(
                    "context cross-check found %d code reference(s); verify OCR "
                    "readings against them before reporting" % context_match_count
                )
            if path_hint_count:
                warnings.append(
                    "image contains %d file-path candidate(s); consider opening "
                    "them to verify" % path_hint_count
                )

            response = ToolResponse(
                tool="inspect_image",
                image_id=record["image_id"],
                session_id=session_id,
                summary=summarize(
                    record, all_evidence, pixels.palette, spatial.graph, warnings,
                    ocr.filtered, merge(all_evidence),
                ),
                data={
                    "image": self._image_meta(record),
                    "analysis": {
                        "tasks": tasks or list(DEFAULT_TASKS),
                        "pixel_stats": pixels.stats,
                        "palette": pixels.palette,
                        "color_regions": pixels.regions,
                        "geometry": geometry.diagnostics,
                        "ocr": {
                            "provider": ocr.provider,
                            "available": ocr.available,
                            "line_count": len(ocr.lines),
                            "warning": ocr.warning,
                        },
                        "semantic": {
                            "provider": semantics.provider,
                            "model": semantics.model,
                            "object_count": sum(
                                1 for e in semantics.evidence if e.kind == EvidenceKind.OBJECT
                            ),
                            "warning": semantics.warning,
                        },
                        "scene_graph": spatial.graph if detail != "compact" else {
                            "node_count": spatial.graph.get("node_count", 0),
                            "edge_count": spatial.graph.get("edge_count", 0),
                        },
                        "context": context_info,
                    },
                    "capabilities": {
                        "coordinate_space": "original_pixels",
                        "observed": ["pixels", "geometry", "ocr", "spatial measurements"],
                        "inferred": ["semantic objects"] if providers else [],
                    },
                },
                evidence=all_evidence,
                evidence_total=len(all_evidence),
                warnings=warnings,
                next_actions=self._next_actions(record["image_id"]),
                timings_ms=timings,
            )
            cache_payload = response.model_dump(mode="json")
            self._apply_detail(response, detail)
            self.db.put_cache(cache_key, record["image_id"], "inspect_image", cache_payload)
            self.db.finish_job(
                job_id, "ok", (time.perf_counter() - job_started) * 1000.0
            )
            response.timings_ms["total_ms"] = (time.perf_counter() - started) * 1000.0
            return response
        except Exception as exc:
            self.db.finish_job(
                job_id, "error", (time.perf_counter() - job_started) * 1000.0, str(exc)
            )
            raise

    def inspect_region(
        self,
        image_id: str,
        region: list[float],
        tasks: list[str] | None = None,
        detail: str = "standard",
        padding: float = 0.0,
        upscale: float | None = None,
        force: bool = False,
        session_id: str | None = None,
        agent: str = "unknown",
    ) -> ToolResponse:
        started = time.perf_counter()
        record = self.get_record(image_id)
        tasks = self._validate_tasks(tasks)
        bbox = self._bbox(region, record).expand(padding).clamp(record["width"], record["height"])
        if bbox.area < 16:
            raise ValidationError("region is too small; provide a box of at least 4x4 pixels")
        session_id = session_id or self.ensure_session(image_id, agent=agent)
        cache_key = self._cache_key(
            "inspect_region",
            {
                "image_id": image_id,
                "bbox": bbox.as_rounded(),
                "tasks": "default" if not tasks else sorted(tasks),
                "upscale": upscale,
                "schema": SCHEMA_VERSION,
            },
        )
        if not force:
            cached = self.db.get_cache(cache_key)
            if cached:
                response = ToolResponse.model_validate(cached)
                response.cached = True
                response.timings_ms = {"total_ms": (time.perf_counter() - started) * 1000.0, "cache_hit": 1.0}
                self.db.touch_session(session_id, image_id)
                return self._apply_detail(response, detail)

        job_id = self.db.create_job(image_id, "inspect_region", tasks)
        job_started = time.perf_counter()
        try:
            prepared = self.loader.prepare(record)
            x0, y0, x1, y1 = (int(round(v)) for v in bbox.as_list())
            crop = prepared.bgr[y0:y1, x0:x1].copy()
            if crop.size == 0:
                raise ValidationError("region crop is empty")
            if upscale is None:
                longest = max(crop.shape[:2])
                upscale = min(2.0, max(1.0, 900.0 / max(1, longest))) if longest < 900 else 1.0
            working = make_working_image(
                crop,
                record["width"],
                record["height"],
                self.settings.analysis_max_dim,
                region=bbox,
                upscale=upscale,
            )

            timings: dict[str, float] = {}
            stage = time.perf_counter()
            pixels = analyze_pixels(working, image_id, scope="region", segment=False)
            geometry = analyze_geometry(working, image_id, scope="region")
            timings["pixels_geometry_ms"] = (time.perf_counter() - stage) * 1000.0

            run_ocr = self.settings.ocr_enabled and (
                not tasks or "extract_text" in tasks or "describe" in tasks or "identify_elements" in tasks
            )
            stage = time.perf_counter()
            if run_ocr:
                ocr = analyze_ocr(
                    working,
                    image_id,
                    scope="region",
                    enabled=True,
                    min_confidence=self.settings.ocr_min_confidence,
                )
            else:
                from .ocr.pipeline import OCRResult

                ocr = OCRResult(warning="OCR skipped: task list did not request text")
            timings["ocr_ms"] = (time.perf_counter() - stage) * 1000.0

            providers = create_providers(self.settings)
            run_semantics = bool(providers) and (
                not tasks or "identify_elements" in tasks or "describe" in tasks
            )
            stage = time.perf_counter()
            if run_semantics:
                semantics = analyze_semantics(
                    working,
                    image_id,
                    providers,
                    regions=None,
                    scope="region",
                )
            else:
                from .semantics.pipeline import SemanticResult

                semantics = SemanticResult(
                    warning=None if not providers else "semantic pass skipped"
                )
            timings["semantics_ms"] = (time.perf_counter() - stage) * 1000.0

            stage = time.perf_counter()
            combined = [*pixels.evidence, *geometry.evidence, *ocr.evidence, *semantics.evidence]
            combined = _drop_text_glyphs(combined)
            spatial = build_scene(image_id, combined, record["width"], record["height"], scope="region")
            timings["spatial_ms"] = (time.perf_counter() - stage) * 1000.0
            all_evidence = [*combined, *spatial.evidence]

            prior_rows, _ = self.db.query_evidence(image_id, region=bbox.as_list(), limit=25)
            new_ids = {e.evidence_id for e in all_evidence}
            prior = [
                self._row_to_evidence(row).compact()
                for row in prior_rows
                if row["evidence_id"] not in new_ids and row["scope"] == "image"
            ][:8]

            self.db.upsert_evidence(all_evidence, job_id)
            warnings = [w for w in (ocr.warning, semantics.warning) if w]
            response = ToolResponse(
                tool="inspect_region",
                image_id=image_id,
                session_id=session_id,
                summary=summarize_region(
                    record, bbox.as_rounded(), all_evidence, warnings, merge(all_evidence)
                ),
                data={
                    "region": bbox.as_rounded(),
                    "region_size_px": [round(bbox.width, 1), round(bbox.height, 1)],
                    "working_scale": round(working.mapper.scale, 3),
                    "prior_image_evidence": prior,
                    "pixel_stats": pixels.stats,
                    "palette": pixels.palette,
                    "geometry": geometry.diagnostics,
                    "ocr": {
                        "provider": ocr.provider,
                        "available": ocr.available,
                        "line_count": len(ocr.lines),
                    },
                    "scene_graph": spatial.graph if detail != "compact" else {
                        "node_count": spatial.graph.get("node_count", 0),
                        "edge_count": spatial.graph.get("edge_count", 0),
                    },
                },
                evidence=all_evidence,
                evidence_total=len(all_evidence),
                warnings=warnings,
                next_actions=self._next_actions(image_id, region=bbox.as_rounded()),
                timings_ms=timings,
            )
            cache_payload = response.model_dump(mode="json")
            self._apply_detail(response, detail)
            self.db.record_inspection(
                image_id,
                "inspect_region",
                {"region": bbox.as_rounded(), "tasks": tasks},
                response.summary[:400],
                len(all_evidence),
                session_id,
            )
            self.db.put_cache(cache_key, image_id, "inspect_region", cache_payload)
            self.db.finish_job(job_id, "ok", (time.perf_counter() - job_started) * 1000.0)
            response.timings_ms["total_ms"] = (time.perf_counter() - started) * 1000.0
            return response
        except Exception as exc:
            self.db.finish_job(job_id, "error", (time.perf_counter() - job_started) * 1000.0, str(exc))
            raise

    def query_evidence(
        self,
        image_id: str,
        kind: str | None = None,
        text_contains: str | None = None,
        region: list[float] | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
        detail: str = "standard",
    ) -> ToolResponse:
        record = self.get_record(image_id)
        if kind:
            try:
                EvidenceKind(kind)
            except ValueError:
                raise ValidationError(
                    f"unknown evidence kind {kind!r}; allowed: {[k.value for k in EvidenceKind]}"
                )
        bbox = self._bbox(region, record).as_rounded() if region else None
        rows, total = self.db.query_evidence(
            image_id,
            kind=kind,
            text_contains=text_contains,
            region=bbox,
            min_confidence=min_confidence,
            limit=max(1, min(limit, 500)),
            offset=max(0, offset),
        )
        evidence = [self._row_to_evidence(row) for row in rows]
        kind_counts: dict[str, int] = {}
        for row in rows:
            kind_counts[row["kind"]] = kind_counts.get(row["kind"], 0) + 1
        count_text = ", ".join(f"{k} {v}" for k, v in sorted(kind_counts.items())) or "none"
        response = ToolResponse(
            tool="query_evidence",
            image_id=image_id,
            summary=(
                f"{total} evidence item(s) match the filters; this page has {len(evidence)} "
                f"({count_text})."
            ),
            data={
                "filters": {
                    "kind": kind,
                    "text_contains": text_contains,
                    "region": bbox,
                    "min_confidence": min_confidence,
                },
                "total": total,
                "offset": offset,
                "limit": limit,
                "kind_counts": kind_counts,
            },
            evidence=evidence,
            evidence_total=total,
            next_actions=[
                "Narrow with kind='text' or a region to reduce noise.",
                "Use verify_claim when a spatial or textual claim needs a verdict.",
            ],
        )
        return self._apply_detail(response, detail)

    def verify_claim(
        self,
        image_id: str,
        claim: str | dict[str, Any],
        detail: str = "standard",
        session_id: str | None = None,
        agent: str = "unknown",
    ) -> ToolResponse:
        record = self.get_record(image_id)
        session_id = session_id or self.ensure_session(image_id, agent=agent)
        rows = self.db.all_evidence(image_id)
        if not any(row["kind"] != EvidenceKind.VERIFICATION.value for row in rows):
            self.inspect_image(image_id=image_id, detail="full", session_id=session_id)

        rows = self.db.all_evidence(image_id)
        evidence = [
            self._row_to_evidence(row)
            for row in rows
            if row["kind"] != EvidenceKind.VERIFICATION.value
        ]
        prepared = self.loader.prepare(record)
        ocr_available = any(e.kind == EvidenceKind.TEXT for e in evidence)
        if not ocr_available and self.settings.ocr_enabled:
            ocr_available = self._ocr_provider_available()

        verifier = ClaimVerifier(
            image_id=image_id,
            evidence=evidence,
            width=record["width"],
            height=record["height"],
            bgr=prepared.bgr,
            ocr_available=ocr_available,
        )
        result = verifier.verify(claim)
        self._persist_verification(image_id, result)

        claim_text = result.claim
        next_actions = ["Call inspect_region on the referenced elements for raw coordinates."]
        if result.status == ClaimStatus.INCONCLUSIVE:
            next_actions.insert(
                0,
                "Rewrite as a measurable claim (alignment, pixel distance, colour, text, size) "
                "or inspect the region first.",
            )
        elif result.status == ClaimStatus.CONTRADICTED:
            next_actions.insert(0, "Use the measurements above as the corrected values.")

        response = ToolResponse(
            tool="verify_claim",
            image_id=image_id,
            session_id=session_id,
            summary=result.summary(),
            data={
                "claim": claim_text,
                "status": result.status.value,
                "confidence": result.confidence,
                "measurements": [m.model_dump(mode="json") for m in result.measurements],
                "evidence_ids": result.evidence_ids,
                "method": result.method,
            },
            evidence=[],
            verification=result,
            next_actions=next_actions,
        )
        self.db.record_inspection(
            image_id,
            "verify_claim",
            {"claim": claim_text},
            response.summary[:400],
            1,
            session_id,
        )
        return self._apply_detail(response, detail)

    def compare_regions(
        self,
        image_id: str,
        region_a: list[float],
        region_b: list[float],
        aspects: list[str] | None = None,
        detail: str = "standard",
    ) -> ToolResponse:
        record = self.get_record(image_id)
        prepared = self.loader.prepare(record)
        bbox_a = self._bbox(region_a, record)
        bbox_b = self._bbox(region_b, record)
        aspects = aspects or ["position", "size", "color", "text"]
        allowed = {"position", "size", "color", "text", "structure"}
        unknown = [a for a in aspects if a not in allowed]
        if unknown:
            raise ValidationError(f"unknown aspect(s) {unknown}; allowed: {sorted(allowed)}")

        crop_a = _crop(prepared.bgr, bbox_a)
        crop_b = _crop(prepared.bgr, bbox_b)
        comparisons: list[dict] = []

        if "position" in aspects:
            relation = relative_position(bbox_a, bbox_b)
            comparisons.append(
                {
                    "aspect": "position",
                    "result": relation,
                    "measurements": {
                        "center_dx_px": round(bbox_b.center_x - bbox_a.center_x, 1),
                        "center_dy_px": round(bbox_b.center_y - bbox_a.center_y, 1),
                        "gap_x_px": round(bbox_a.gap(bbox_b)[0], 1),
                        "gap_y_px": round(bbox_a.gap(bbox_b)[1], 1),
                    },
                    "summary": f"Region B is {relation.replace('_', ' ')} region A.",
                }
            )
        if "size" in aspects:
            comparisons.append(
                {
                    "aspect": "size",
                    "result": {
                        "a": [round(bbox_a.width, 1), round(bbox_a.height, 1)],
                        "b": [round(bbox_b.width, 1), round(bbox_b.height, 1)],
                    },
                    "measurements": {
                        "width_delta_px": round(bbox_b.width - bbox_a.width, 1),
                        "height_delta_px": round(bbox_b.height - bbox_a.height, 1),
                        "area_ratio": round(bbox_b.area / bbox_a.area, 3) if bbox_a.area else None,
                    },
                    "summary": (
                        f"B is {bbox_b.width - bbox_a.width:+.1f} px wider and "
                        f"{bbox_b.height - bbox_a.height:+.1f} px taller than A."
                    ),
                }
            )
        if "color" in aspects:
            palette_a = dominant_colors(crop_a, k=3)
            palette_b = dominant_colors(crop_b, k=3)
            color_a = palette_a[0] if palette_a else None
            color_b = palette_b[0] if palette_b else None
            delta = None
            if color_a and color_b:
                from .pixels.colors import delta_e

                delta = round(delta_e(tuple(color_a["lab"]), tuple(color_b["lab"])), 1)
            comparisons.append(
                {
                    "aspect": "color",
                    "result": {
                        "a": {"hex": color_a["hex"], "name": color_a["name"]} if color_a else None,
                        "b": {"hex": color_b["hex"], "name": color_b["name"]} if color_b else None,
                    },
                    "measurements": {"delta_e": delta},
                    "summary": (
                        f"Dominant colours: A {color_a['hex']} ({color_a['name']}), "
                        f"B {color_b['hex']} ({color_b['name']}), ΔE {delta}."
                        if color_a and color_b
                        else "Colour could not be sampled for both regions."
                    ),
                }
            )
        if "text" in aspects:
            ocr_a = analyze_ocr(
                _working_for_crop(crop_a, bbox_a, record, self.settings.analysis_max_dim),
                image_id,
                scope="region",
                enabled=self.settings.ocr_enabled,
                min_confidence=self.settings.ocr_min_confidence,
            )
            ocr_b = analyze_ocr(
                _working_for_crop(crop_b, bbox_b, record, self.settings.analysis_max_dim),
                image_id,
                scope="region",
                enabled=self.settings.ocr_enabled,
                min_confidence=self.settings.ocr_min_confidence,
            )
            texts_a = {line.text.strip() for line in ocr_a.lines}
            texts_b = {line.text.strip() for line in ocr_b.lines}
            comparisons.append(
                {
                    "aspect": "text",
                    "result": {
                        "a": sorted(texts_a),
                        "b": sorted(texts_b),
                        "common": sorted(texts_a & texts_b),
                        "only_a": sorted(texts_a - texts_b),
                        "only_b": sorted(texts_b - texts_a),
                    },
                    "measurements": {"lines_a": len(ocr_a.lines), "lines_b": len(ocr_b.lines)},
                    "summary": (
                        f"A has {len(texts_a)} text line(s), B has {len(texts_b)}; "
                        f"{len(texts_a & texts_b)} shared."
                    ),
                    "warnings": [w for w in (ocr_a.warning, ocr_b.warning) if w],
                }
            )
        if "structure" in aspects:
            shapes_a = _shape_summary(crop_a)
            shapes_b = _shape_summary(crop_b)
            comparisons.append(
                {
                    "aspect": "structure",
                    "result": {"a": shapes_a, "b": shapes_b},
                    "measurements": {},
                    "summary": (
                        f"Detected shapes: A {shapes_a['total']} ({shapes_a['counts']}), "
                        f"B {shapes_b['total']} ({shapes_b['counts']})."
                    ),
                }
            )

        summary = " ".join(item["summary"] for item in comparisons)
        response = ToolResponse(
            tool="compare_regions",
            image_id=image_id,
            summary=summary,
            data={
                "region_a": bbox_a.as_rounded(),
                "region_b": bbox_b.as_rounded(),
                "aspects": aspects,
                "comparisons": comparisons,
            },
            next_actions=[
                "Use verify_claim for a yes/no verdict on a specific relation.",
                "Use inspect_region for full OCR/geometry evidence inside either region.",
            ],
        )
        return self._apply_detail(response, detail)

    # --------------------------------------------------------------- sessions
    def ensure_session(self, image_id: str, agent: str = "unknown") -> str:
        existing = self.db.find_session_for_image(image_id)
        if existing:
            self.db.touch_session(existing, image_id)
            return existing
        return self.db.create_session(image_id, agent=agent)

    def get_session(self, session_id: str) -> dict:
        session = self.db.get_session(session_id)
        if not session:
            raise NotFoundError(f"session {session_id!r} not found")
        return session

    def list_sessions(self, image_id: str | None = None) -> list[dict]:
        return self.db.list_sessions(image_id)

    def list_inspections(self, image_id: str) -> list[dict]:
        return self.db.list_inspections(image_id)

    def list_jobs(self, image_id: str | None = None) -> list[dict]:
        return self.db.list_jobs(image_id)

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": __import__("vi3ion").__version__,
            "images": self.db.count_images(),
            "data_dir": str(self.settings.data_dir),
            "ocr": {
                "enabled": self.settings.ocr_enabled,
                "available": self._ocr_provider_available(),
            },
            "semantic_provider": self.settings.semantic_provider,
            "coordinate_space": "original_pixels",
        }

    # ---------------------------------------------------------------- internal
    def _apply_detail(self, response: ToolResponse, detail: str) -> ToolResponse:
        limit = DETAIL_LIMITS.get(detail)
        if limit is None:
            limit = DETAIL_LIMITS["standard"]
        if limit == 0:
            limit = max(1, self.settings.max_evidence_returned)
        available = len(response.evidence)
        total = response.evidence_total or available
        response.evidence_total = total
        response.evidence_returned = min(available, limit)
        response.truncated = total > response.evidence_returned
        response.evidence = response.evidence[:limit]
        return response

    def _bbox(self, region: list[float] | None, record: dict) -> BBox:
        if region is None:
            raise ValidationError("a region [x0, y0, x1, y1] is required")
        try:
            bbox = BBox.from_any(region)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if record["width"] <= 0 or record["height"] <= 0:
            raise ValidationError("image has invalid dimensions")
        clamped = bbox.clamp(record["width"], record["height"])
        if clamped.area <= 0:
            raise ValidationError("region does not intersect the image")
        return clamped

    def _validate_tasks(self, tasks: list[str] | None) -> list[str]:
        tasks = tasks or []
        unknown = [task for task in tasks if task not in TASK_CHOICES]
        if unknown:
            raise ValidationError(f"unknown task(s) {unknown}; allowed: {list(TASK_CHOICES)}")
        return tasks

    def _cache_key(self, tool: str, payload: dict[str, Any]) -> str:
        raw = json.dumps({"tool": tool, **payload}, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _ocr_provider_available(self) -> bool:
        if self._ocr_available is None:
            self._ocr_available = get_ocr_provider().available
        return self._ocr_available

    def _image_meta(self, record: dict) -> dict:
        return {
            "image_id": record["image_id"],
            "width": record["width"],
            "height": record["height"],
            "format": record["format"],
            "size_bytes": record["size_bytes"],
            "created_at": record["created_at"],
            "sha256": record["sha256"],
            "source": record.get("source"),
        }

    def _row_to_evidence(self, row: dict[str, Any]) -> Evidence:
        bbox = BBox.from_any(row["bbox"]) if row.get("bbox") else None
        produced_at = datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.utcnow()
        return Evidence(
            evidence_id=row["evidence_id"],
            image_id=row["image_id"],
            kind=EvidenceKind(row["kind"]),
            label=row["label"],
            bbox=bbox,
            confidence=row.get("confidence"),
            attributes=row.get("attributes") or {},
            provenance=Provenance(
                module=row["module"],
                method=row["method"],
                version=row["version"],
                produced_at=produced_at,
            ),
            observed=bool(row.get("observed", True)),
            scope=row.get("scope", "image"),
        )

    def _persist_verification(self, image_id: str, result: VerificationResult) -> None:
        evidence = Evidence(
            evidence_id=make_evidence_id(
                image_id,
                EvidenceKind.VERIFICATION,
                "verification",
                "claim_check",
                result.claim,
                None,
                result.status.value,
            ),
            image_id=image_id,
            kind=EvidenceKind.VERIFICATION,
            label=f"claim {result.status.value}",
            bbox=None,
            confidence=result.confidence,
            attributes=result.model_dump(mode="json"),
            provenance=Provenance(module="verification", method="claim_check", version="1.0.0"),
            observed=True,
            scope="image",
        )
        self.db.upsert_evidence([evidence])

    def _next_actions(self, image_id: str, region: list[float] | None = None) -> list[str]:
        actions = [
            f"inspect_region(image_id={image_id!r}, region=[x0,y0,x1,y1]) to zoom into an element.",
            f"query_evidence(image_id={image_id!r}, kind='text') for all OCR with coordinates.",
            f"verify_claim(image_id={image_id!r}, claim='...') before asserting alignment or distance.",
        ]
        if region:
            actions.append(f"Previous region: {region}. Coordinates are original-image pixels.")
        return actions


def _encode_png(bgr: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", bgr)
    if not ok:
        raise ValidationError("could not encode image as PNG")
    return buffer.tobytes()


def _attach_element_colors(evidence: list[Evidence], working) -> None:
    """Measure the colour of every text and shape element.

    The measurement lands in the item's attributes, so an agent can answer
    "the Save button is #2B66E6" instead of guessing from the palette.
    """
    from .pixels.element_color import measure_element

    bgr = getattr(working, "bgr", None)
    if bgr is None:
        return
    mapper = getattr(working, "mapper", None)
    for item in evidence:
        if item.kind not in (EvidenceKind.TEXT, EvidenceKind.SHAPE):
            continue
        if item.bbox is None:
            continue
        try:
            box = item.bbox.as_list()
            if mapper is not None:
                working_box = mapper.to_working_bbox(*box)
                box = working_box.as_list()
            measured = measure_element(bgr, tuple(box))
        except Exception:  # noqa: BLE001 - colour must never break the analysis
            continue
        if not measured:
            continue
        item.attributes = {**(item.attributes or {}), **measured}


def _drop_text_glyphs(evidence: list[Evidence]) -> list[Evidence]:
    """Remove contours that are just letter shapes inside recognised text lines.

    Geometry is OCR-independent upstream; this is a response-hygiene step, not
    part of the geometry module's contract.
    """
    text_boxes = [
        item.bbox for item in evidence
        if item.kind == EvidenceKind.TEXT and item.bbox is not None
    ]
    if not text_boxes:
        return evidence
    kept: list[Evidence] = []
    for item in evidence:
        if item.kind == EvidenceKind.SHAPE and item.bbox is not None:
            if any(box.contains(item.bbox, tolerance=4.0) for box in text_boxes):
                continue
        kept.append(item)
    return kept


def _resize_to(bgr: np.ndarray, scale: float, max_dim: int) -> np.ndarray:
    height, width = bgr.shape[:2]
    factor = scale
    if max_dim and max(width, height) * factor > max_dim:
        factor = max_dim / float(max(width, height))
    if abs(factor - 1.0) < 1e-6:
        return bgr
    return cv2.resize(
        bgr,
        (max(1, int(round(width * factor))), max(1, int(round(height * factor)))),
        interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC,
    )


def _crop(bgr: np.ndarray, bbox: BBox) -> np.ndarray:
    height, width = bgr.shape[:2]
    x0 = int(max(0, min(width - 1, round(bbox.x0))))
    y0 = int(max(0, min(height - 1, round(bbox.y0))))
    x1 = int(max(x0 + 1, min(width, round(bbox.x1))))
    y1 = int(max(y0 + 1, min(height, round(bbox.y1))))
    return bgr[y0:y1, x0:x1].copy()


def _working_for_crop(crop: np.ndarray, bbox: BBox, record: dict, max_dim: int) -> WorkingImage:
    return make_working_image(crop, record["width"], record["height"], max_dim, region=bbox)


def _shape_summary(crop: np.ndarray) -> dict:
    from .geometry import detect_shapes

    result = detect_shapes(crop)
    counts: dict[str, int] = {}
    for shape in result.shapes:
        counts[shape.shape] = counts.get(shape.shape, 0) + 1
    return {"total": len(result.shapes), "counts": counts}
