"""Image ingestion: validation, canonical storage, thumbnails, hashing."""

from __future__ import annotations

import hashlib
import io
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ...config import Settings
from ...storage import Database, ImageStore

SUPPORTED_FORMATS = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
    "BMP": "bmp",
    "TIFF": "tiff",
    "GIF": "gif",
}

# Composite transparent images over white; screenshots with alpha otherwise read as black.
_WHITE = (255, 255, 255)


class IngestError(ValueError):
    """Raised when an image cannot be accepted. Message is safe to show to a caller."""


@dataclass
class ImageAsset:
    image_id: str
    sha256: str
    original_path: str
    thumbnail_path: str | None
    width: int
    height: int
    format: str
    size_bytes: int
    created_at: str
    source: str = "upload"
    meta: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        return {
            "image_id": self.image_id,
            "sha256": self.sha256,
            "original_path": self.original_path,
            "thumbnail_path": self.thumbnail_path,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "source": self.source,
            "meta": self.meta,
        }


@dataclass
class PreparedImage:
    """Decoded, orientation-corrected image data used by the perception pipeline."""

    rgb: np.ndarray
    bgr: np.ndarray
    width: int
    height: int


class ImageLoader:
    def __init__(self, settings: Settings, db: Database, store: ImageStore):
        self.settings = settings
        self.db = db
        self.store = store

    # ------------------------------------------------------------------ ingest
    def ingest_bytes(self, data: bytes, filename: str | None = None, source: str = "upload") -> tuple[dict, bool]:
        if not data:
            raise IngestError("empty image payload")
        if len(data) > self.settings.max_image_bytes:
            raise IngestError(
                f"image is {len(data)} bytes; limit is {self.settings.max_image_bytes} bytes"
            )
        digest = hashlib.sha256(data).hexdigest()
        existing = self.db.find_image_by_sha(digest)
        if existing:
            return existing, True

        try:
            with Image.open(io.BytesIO(data)) as probe:
                fmt = (probe.format or "").upper()
                width, height = probe.size
                if fmt not in SUPPORTED_FORMATS:
                    raise IngestError(
                        f"unsupported image format {fmt or 'unknown'}; supported: {sorted(SUPPORTED_FORMATS)}"
                    )
                if width <= 0 or height <= 0:
                    raise IngestError("image has invalid dimensions")
                if width * height > self.settings.max_image_pixels:
                    raise IngestError(
                        f"image is {width}x{height} ({width * height} px); limit is {self.settings.max_image_pixels} px"
                    )
                try:
                    probe.verify()
                except (UnidentifiedImageError, OSError, ValueError) as exc:
                    raise IngestError(f"invalid or corrupted image: {exc}") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise IngestError(f"not a valid image: {exc}") from exc

        image_id = "img_" + secrets.token_hex(8)
        extension = SUPPORTED_FORMATS[fmt]
        original_path = self.store.save_original(image_id, data, extension)

        try:
            with Image.open(io.BytesIO(data)) as img:
                oriented = ImageOps.exif_transpose(img)
                if getattr(oriented, "is_animated", False):
                    oriented.seek(0)
                rgba = oriented.convert("RGBA")
                canvas = Image.new("RGBA", rgba.size, _WHITE + (255,))
                canvas.alpha_composite(rgba)
                rgb = canvas.convert("RGB")
                width, height = rgb.size
                thumb = rgb.copy()
                thumb.thumbnail(
                    (self.settings.thumbnail_max_dim, self.settings.thumbnail_max_dim),
                    Image.Resampling.LANCZOS,
                )
                buffer = io.BytesIO()
                thumb.save(buffer, format="JPEG", quality=86, optimize=True)
                thumbnail_path = self.store.save_thumbnail(image_id, buffer.getvalue())
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            original_path.unlink(missing_ok=True)
            raise IngestError(f"could not decode image: {exc}") from exc

        created_at = datetime.now(timezone.utc).isoformat()
        asset = ImageAsset(
            image_id=image_id,
            sha256=digest,
            original_path=str(original_path),
            thumbnail_path=str(thumbnail_path),
            width=width,
            height=height,
            format=fmt,
            size_bytes=len(data),
            created_at=created_at,
            source=source,
            meta={"filename": filename} if filename else {},
        )
        self.db.add_image(asset.as_record())
        return asset.as_record(), False

    def ingest_clipboard(self) -> tuple[dict, bool]:
        """Ingest an image from the system clipboard."""
        try:
            from PIL import ImageGrab
            clip = ImageGrab.grabclipboard()
        except Exception as exc:
            raise IngestError(f"failed to access clipboard: {exc}") from exc

        if clip is None:
            raise IngestError("clipboard does not contain an image or screenshot")

        if isinstance(clip, list):
            for item in clip:
                p = Path(item)
                if p.is_file() and p.suffix.lower().lstrip(".") in {
                    fmt.lower() for fmt in SUPPORTED_FORMATS.values()
                }:
                    return self.ingest_path(p, source="clipboard")
            raise IngestError(f"clipboard file list contains no supported image: {clip}")

        if isinstance(clip, Image.Image):
            buf = io.BytesIO()
            clip.save(buf, format="PNG")
            return self.ingest_bytes(buf.getvalue(), filename="clipboard.png", source="clipboard")

        raise IngestError(f"unsupported clipboard content type: {type(clip).__name__}")

    def ingest_path(self, path: str | Path, source: str = "path") -> tuple[dict, bool]:
        path_str = str(path).strip()
        if path_str.lower() in ("clipboard", ":clipboard:", "@clipboard", "clip"):
            return self.ingest_clipboard()
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        candidate = candidate.resolve()
        if not candidate.exists():
            raise IngestError(f"file not found: {candidate}")
        if not candidate.is_file():
            raise IngestError(f"not a file: {candidate}")
        if not self.settings.is_path_allowed(candidate):
            roots = ", ".join(str(r) for r in self.settings.allowed_roots) or "(none configured)"
            raise IngestError(
                f"path is outside allowed roots. Allowed: {roots}. "
                "Set VI3ION_ALLOWED_ROOTS to permit this directory."
            )
        size = candidate.stat().st_size
        if size > self.settings.max_image_bytes:
            raise IngestError(f"image is {size} bytes; limit is {self.settings.max_image_bytes} bytes")
        return self.ingest_bytes(candidate.read_bytes(), filename=candidate.name, source=source)

    # -------------------------------------------------------------------- read
    def prepare(self, record: dict) -> PreparedImage:
        path = Path(record["original_path"])
        if not path.exists():
            raise IngestError(f"stored original is missing for {record['image_id']}")
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                if getattr(img, "is_animated", False):
                    img.seek(0)
                rgba = img.convert("RGBA")
                canvas = Image.new("RGBA", rgba.size, _WHITE + (255,))
                canvas.alpha_composite(rgba)
                rgb_img = canvas.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise IngestError(f"could not decode stored image: {exc}") from exc
        rgb = np.asarray(rgb_img, dtype=np.uint8)
        bgr = rgb[:, :, ::-1].copy()
        return PreparedImage(rgb=rgb, bgr=bgr, width=rgb.shape[1], height=rgb.shape[0])

    def load_bgr(self, record: dict) -> np.ndarray:
        return self.prepare(record).bgr

    def read_bytes(self, record: dict) -> bytes:
        return self.store.read_image_bytes(record)
