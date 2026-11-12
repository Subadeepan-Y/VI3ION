"""Configuration for Vi3ion. All values can be overridden with VI3ION_* env vars."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VI3ION_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"

    # Storage. The default lives in the user's home so an installed package
    # never writes inside site-packages; override with VI3ION_DATA_DIR.
    data_dir: Path = Path.home() / ".vi3ion"

    # Safety limits
    max_image_bytes: int = 40 * 1024 * 1024
    max_image_pixels: int = 80_000_000
    thumbnail_max_dim: int = 480

    # Filesystem access for agent-supplied paths. Semicolon-separated directories.
    allowed_roots: Annotated[list[Path], NoDecode] = Field(
        default_factory=lambda: [Path.cwd(), Path.home() / ".vi3ion"]
    )

    # Code cross-check: roots scanned for string literals so the agent can
    # verify uncertain OCR against the project source. Empty disables it.
    code_roots: Annotated[list[Path], NoDecode] = Field(default_factory=list)

    # Image memory: when a newly analysed image is at least this similar to a
    # previously seen image, suggest it as the same screen/version.
    image_similarity_threshold: float = 0.85

    # Japanese rec model (bundled). Disable when you want the lighter
    # Chinese-only pipeline and rely on agent cross-checking instead.
    use_japan_model: bool = True

    # Low-resource mode: tuned for low-end machines (small RAM/CPU).
    # Enables skip-paths, smaller analysis caps, and less detail.
    # Auto-enables when the machine has < 8 GB RAM (unless explicitly set).
    low_resource: bool | None = None

    # Analysis image max dimension. Default 2048; auto-lowered to 1280
    # in low-resource mode.
    analysis_max_dim: int = 2048

    # Perception
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.35
    semantic_provider: str = "none"  # comma-separated: none|mock|remote|florence|owlvit|clip
    semantic_base_url: str = "https://api.openai.com/v1"
    semantic_model: str = ""
    semantic_api_key: str = ""
    semantic_timeout_s: float = 60.0
    semantic_florence_model: str = "microsoft/Florence-2-base"
    semantic_owlvit_model: str = "google/owlv2-base-patch16"
    semantic_clip_model: str = "openai/clip-vit-base-patch32"
    semantic_min_confidence: float = 0.35
    semantic_vocab_path: Path | None = None
    semantic_mock_path: Path | None = None

    # Response shaping
    max_evidence_returned: int = 40

    @field_validator("allowed_roots", "code_roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [p for p in re.split(r"[;\n]", value) if p.strip()]
            return [Path(p).expanduser() for p in parts]
        if isinstance(value, (list, tuple)):
            return [Path(str(p)).expanduser() for p in value]
        return value

    @field_validator("data_dir", mode="after")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        value = value.expanduser()
        if not value.is_absolute():
            value = (PROJECT_ROOT / value).resolve()
        return value

    @field_validator("allowed_roots", mode="after")
    @classmethod
    def _absolute_roots(cls, value: list[Path]) -> list[Path]:
        roots: list[Path] = []
        for root in value:
            root = root.expanduser()
            if not root.is_absolute():
                root = (PROJECT_ROOT / root).resolve()
            else:
                root = root.resolve()
            if root.exists() and root.is_dir():
                roots.append(root)
        return roots

    @field_validator("code_roots", mode="after")
    @classmethod
    def _absolute_code_roots(cls, value: list[Path]) -> list[Path]:
        roots: list[Path] = []
        for root in value:
            root = root.expanduser()
            if not root.is_absolute():
                root = (PROJECT_ROOT / root).resolve()
            else:
                root = root.resolve()
            if root.exists() and root.is_dir():
                roots.append(root)
        return roots

    @field_validator("low_resource", mode="before")
    @classmethod
    def _auto_low_resource(cls, value: object) -> object:
        if value is not None:
            return value
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            total_gb = status.ullTotalPhys / (1024 ** 3)
            return total_gb < 8.0
        except Exception:
            return False

    @field_validator("analysis_max_dim", mode="after")
    @classmethod
    def _low_resource_dim(cls, value: int, info) -> int:
        if getattr(info, "data", None) and info.data.get("low_resource"):
            return min(value, 1280)
        return value

    @model_validator(mode="after")
    def _low_resource_drops_japan_model(self):
        # The Japanese recognizer is an extra model in memory. On low-RAM
        # machines it is dropped unless it was requested explicitly.
        if self.low_resource and "use_japan_model" not in self.model_fields_set:
            object.__setattr__(self, "use_japan_model", False)
        return self

    @field_validator("semantic_provider")
    @classmethod
    def _valid_provider(cls, value: str) -> str:
        allowed = {"none", "mock", "remote", "florence", "owlvit", "clip"}
        parts = [part.strip().lower() for part in value.split(",") if part.strip()]
        if not parts:
            return "none"
        bad = set(parts) - allowed
        if bad:
            raise ValueError(f"semantic_provider must be comma-separated values from {sorted(allowed)}; got {sorted(bad)}")
        if "none" in parts and len(parts) > 1:
            raise ValueError("'none' cannot be combined with other semantic providers")
        return ",".join(dict.fromkeys(parts))

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "images" / "originals"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "images" / "thumbnails"

    @property
    def crops_dir(self) -> Path:
        return self.data_dir / "images" / "crops"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "database" / "vi3ion.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for path in (
            self.originals_dir,
            self.thumbnails_dir,
            self.crops_dir,
            self.db_path.parent,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def is_path_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
