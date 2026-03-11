"""Movie Clip service: wraps VideoCreator with app-facing semantics.

PR-CORE-VIDEO-002: Validates inputs, normalises ordering, manages output
folder, calls VideoCreator, and writes a durable manifest JSON.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from src.pipeline.video import VideoCreator
from src.video.movie_clip_models import (
    ClipManifest,
    ClipRequest,
    ClipResult,
    ClipSettings,
)

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def _normalize_image_order(paths: list[Path]) -> list[Path]:
    """Return a deterministically ordered copy sorted by filename."""
    return sorted(paths, key=lambda p: p.name)


def _ffmpeg_available() -> bool:
    """Return True if the VideoCreator reports FFmpeg is present."""
    try:
        return VideoCreator().ffmpeg_available
    except Exception:
        return False


class MovieClipService:
    """App-facing service that orchestrates clip assembly via VideoCreator.

    Responsibilities:
    - Validate the clip request.
    - Normalise image ordering.
    - Create a managed output directory.
    - Invoke VideoCreator in the correct mode.
    - Write a durable manifest JSON on success.
    - Return a typed ClipResult (no exceptions propagate to callers).
    """

    def __init__(self, video_creator: VideoCreator | None = None) -> None:
        self._creator = video_creator or VideoCreator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_ffmpeg_available(self) -> bool:
        """Return True if FFmpeg is available for clip assembly."""
        return self._creator.ffmpeg_available

    def build_clip(self, request: ClipRequest) -> ClipResult:
        """Build a clip from the given request.

        Returns a ClipResult whether or not the build succeeded.
        """
        # 1. Validate
        errors = request.validate()
        if errors:
            reason = "; ".join(errors)
            logger.warning(f"[MovieClipService] Invalid clip request: {reason}")
            return ClipResult.failure(reason)

        if not self._creator.ffmpeg_available:
            return ClipResult.failure("FFmpeg is not available on PATH")

        # 2. Normalise ordering
        ordered_images = _normalize_image_order(request.image_paths)

        # 3. Create managed output dir
        output_dir = request.output_dir
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return ClipResult.failure(f"Cannot create output directory: {exc}")

        # 4. Determine output filename
        clip_name = request.clip_name.strip() or "clip"
        output_path = output_dir / f"{clip_name}.mp4"

        # 5. Invoke VideoCreator
        settings = request.settings
        try:
            if settings.mode == "slideshow":
                ok = self._creator.create_slideshow_video(
                    image_paths=ordered_images,
                    output_path=output_path,
                    duration_per_image=settings.duration_per_image,
                    transition_duration=settings.transition_duration,
                    fps=settings.fps,
                    codec=settings.codec,
                    quality=settings.quality,
                )
            else:
                ok = self._creator.create_video_from_images(
                    image_paths=ordered_images,
                    output_path=output_path,
                    fps=settings.fps,
                    codec=settings.codec,
                    quality=settings.quality,
                )
        except Exception as exc:
            logger.exception("[MovieClipService] VideoCreator raised an exception")
            return ClipResult.failure(f"VideoCreator error: {exc}")

        if not ok:
            return ClipResult.failure("FFmpeg reported a failure; check application logs")

        # 6. Write manifest
        frame_count = len(ordered_images)
        duration_sec = (
            frame_count / max(1, settings.fps)
            if settings.mode == "sequence"
            else frame_count * settings.duration_per_image
        )

        manifest = ClipManifest(
            clip_name=clip_name,
            output_path=str(output_path),
            source_images=[str(p) for p in ordered_images],
            settings={
                "fps": settings.fps,
                "codec": settings.codec,
                "quality": settings.quality,
                "mode": settings.mode,
            },
            frame_count=frame_count,
            duration_seconds=round(duration_sec, 3),
        )

        manifest_path = output_dir / f"{clip_name}_manifest.json"
        try:
            manifest.write(manifest_path)
        except Exception as exc:
            logger.warning(f"[MovieClipService] Failed to write manifest: {exc}")
            # Non-fatal: clip was built; manifest failure is a warning
            return ClipResult(
                success=True,
                output_path=output_path,
                manifest_path=None,
                frame_count=frame_count,
                duration_seconds=duration_sec,
            )

        logger.info(
            f"[MovieClipService] Clip built: {output_path.name} "
            f"({frame_count} frames, {duration_sec:.1f}s)"
        )
        return ClipResult(
            success=True,
            output_path=output_path,
            manifest_path=manifest_path,
            frame_count=frame_count,
            duration_seconds=duration_sec,
        )

    def build_clip_from_source(
        self,
        source_dir: Path,
        output_dir: Path,
        settings: ClipSettings | None = None,
        clip_name: str = "",
    ) -> ClipResult:
        """Convenience wrapper: load all images from source_dir, then build."""
        images = sorted(
            [p for p in source_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTENSIONS],
            key=lambda p: p.name,
        )
        request = ClipRequest(
            image_paths=images,
            output_dir=output_dir,
            settings=settings or ClipSettings(),
            clip_name=clip_name or source_dir.name,
        )
        return self.build_clip(request)
