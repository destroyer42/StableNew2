"""Data models for Movie Clip build requests, results, and manifests.

PR-CORE-VIDEO-002: Typed value objects for clip assembly flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Clip request + settings
# ---------------------------------------------------------------------------


@dataclass
class ClipSettings:
    """User-facing clip build configuration."""

    fps: int = 24
    codec: str = "libx264"
    quality: str = "medium"
    mode: str = "sequence"  # "sequence" | "slideshow"
    duration_per_image: float = 3.0  # used only when mode == "slideshow"
    transition_duration: float = 0.5  # used only when mode == "slideshow"

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty if valid)."""
        errors: list[str] = []
        if self.fps < 1 or self.fps > 240:
            errors.append(f"fps must be 1–240, got {self.fps}")
        if not self.codec.strip():
            errors.append("codec must not be empty")
        if self.mode not in ("sequence", "slideshow"):
            errors.append(f"mode must be 'sequence' or 'slideshow', got {self.mode!r}")
        if self.mode == "slideshow" and self.duration_per_image <= 0:
            errors.append("duration_per_image must be positive")
        return errors


@dataclass
class ClipRequest:
    """A fully-specified request to build one clip."""

    image_paths: list[Path]
    output_dir: Path
    settings: ClipSettings = field(default_factory=ClipSettings)
    clip_name: str = ""

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty if valid)."""
        errors: list[str] = []
        if not self.image_paths:
            errors.append("image_paths must not be empty")
        missing = [str(p) for p in self.image_paths if not p.exists()]
        if missing:
            errors.append(f"{len(missing)} image path(s) do not exist")
        if not self.output_dir:
            errors.append("output_dir must be set")
        errors.extend(self.settings.validate())
        return errors


# ---------------------------------------------------------------------------
# Clip result
# ---------------------------------------------------------------------------


@dataclass
class ClipResult:
    """Outcome of a single clip build attempt."""

    success: bool
    output_path: Path | None = None
    manifest_path: Path | None = None
    error: str = ""
    frame_count: int = 0
    duration_seconds: float = 0.0

    @classmethod
    def failure(cls, reason: str) -> ClipResult:
        return cls(success=False, error=reason)


# ---------------------------------------------------------------------------
# Clip manifest
# ---------------------------------------------------------------------------


@dataclass
class ClipManifest:
    """Durable record of a completed clip build, written alongside the artifact."""

    clip_name: str
    output_path: str
    source_images: list[str]
    settings: dict[str, Any]
    frame_count: int
    duration_seconds: float
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "clip_name": self.clip_name,
            "output_path": self.output_path,
            "source_images": self.source_images,
            "settings": self.settings,
            "frame_count": self.frame_count,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
        }

    def write(self, path: Path) -> None:
        """Write the manifest as JSON to the given path."""
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClipManifest:
        return cls(
            clip_name=data.get("clip_name", ""),
            output_path=data.get("output_path", ""),
            source_images=list(data.get("source_images", [])),
            settings=dict(data.get("settings", {})),
            frame_count=int(data.get("frame_count", 0)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", "1.0"),
        )

    @classmethod
    def read(cls, path: Path) -> ClipManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
