"""Filesystem layout for originals, thumbnails and derived crops."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import Settings


class ImageStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()

    def save_original(self, image_id: str, data: bytes, extension: str) -> Path:
        ext = extension.lower().lstrip(".")
        path = self.settings.originals_dir / f"{image_id}.{ext}"
        path.write_bytes(data)
        return path

    def save_thumbnail(self, image_id: str, data: bytes) -> Path:
        path = self.settings.thumbnails_dir / f"{image_id}.jpg"
        path.write_bytes(data)
        return path

    def save_crop(self, image_id: str, data: bytes, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        path = self.settings.crops_dir / f"{image_id}_{digest}.png"
        path.write_bytes(data)
        return path

    def read_image_bytes(self, record: dict) -> bytes:
        path = Path(record["original_path"])
        if not path.exists():
            raise FileNotFoundError(f"original image missing: {path}")
        return path.read_bytes()

    def delete(self, record: dict) -> None:
        for key in ("original_path", "thumbnail_path"):
            value = record.get(key)
            if value:
                Path(value).unlink(missing_ok=True)
        for crop in self.settings.crops_dir.glob(f"{record['image_id']}_*.png"):
            crop.unlink(missing_ok=True)
