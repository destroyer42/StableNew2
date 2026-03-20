"""Movie Clip service: post-video assembly/export orchestration.

PR-CORE-VIDEO-002 started Movie Clips as an image-sequence wrapper around
VideoCreator. PR-VIDEO-217 keeps the same app-facing entrypoints, but routes
the work through StableNew-owned assembly contracts so image clips, stitched
sequence exports, and future interpolated outputs share one provenance path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.pipeline.video import VideoCreator
from src.video.assembly_models import AssemblyRequest
from src.video.assembly_service import AssemblyService
from src.video.movie_clip_models import (
    ClipRequest,
    ClipResult,
    ClipSettings,
)
from src.video.video_export import export_image_sequence_video

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
    """App-facing service that orchestrates clip assembly via AssemblyService.

    Responsibilities:
    - Validate the clip request.
    - Normalise source ordering.
    - Create a managed output directory.
    - Route image or video-segment sources into canonical assembly contracts.
    - Return a typed ClipResult (no exceptions propagate to callers).
    """

    def __init__(
        self,
        video_creator: VideoCreator | None = None,
        assembly_service: AssemblyService | None = None,
    ) -> None:
        self._creator = video_creator or VideoCreator()
        self._assembly_service = assembly_service or AssemblyService(
            image_exporter=self._export_image_sequence,
        )

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
            return ClipResult.failure("FFmpeg is not available or could not be resolved")

        ordered_paths = _normalize_image_order(request.image_paths)

        output_dir = request.output_dir
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return ClipResult.failure(f"Cannot create output directory: {exc}")

        clip_name = request.clip_name.strip() or "clip"
        settings = request.settings

        try:
            if request.source_bundle:
                source = self._assembly_service.build_source_from_bundle(request.source_bundle)
            else:
                source = self._assembly_service.build_source_from_paths(ordered_paths)
        except Exception as exc:
            logger.exception("[MovieClipService] Failed to resolve assembly source")
            return ClipResult.failure(f"Assembly source error: {exc}")

        assembly_result = self._assembly_service.assemble(
            AssemblyRequest(
                source=source,
                output_dir=output_dir,
                clip_name=clip_name,
                fps=settings.fps,
                codec=settings.codec,
                quality=settings.quality,
                mode=settings.mode,
                duration_per_image=settings.duration_per_image,
                transition_duration=settings.transition_duration,
            )
        )
        if not assembly_result.success or not assembly_result.primary_path:
            return ClipResult.failure(assembly_result.error or "Assembly failed")

        frame_paths = source.resolved_frame_paths()
        source_paths = source.resolved_segment_output_paths()
        frame_count = len(frame_paths) or len(source_paths)
        duration_sec = self._estimate_duration_seconds(
            settings=settings,
            frame_count=frame_count,
            has_frame_source=bool(frame_paths),
        )
        output_path = Path(assembly_result.primary_path)
        manifest_path = Path(assembly_result.manifest_path) if assembly_result.manifest_path else None

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
            artifact_bundle=(
                dict(assembly_result.export_output.artifact_bundle)
                if assembly_result.export_output
                else {}
            ),
            source_bundle=request.source_bundle or source.to_dict(),
            assembly_result=assembly_result.to_dict(),
        )

    def build_clip_from_source_bundle(
        self,
        source_bundle: dict[str, Any],
        output_dir: Path,
        settings: ClipSettings | None = None,
        clip_name: str = "",
    ) -> ClipResult:
        """Build a clip directly from a canonical sequence or assembly bundle."""
        try:
            source = self._assembly_service.build_source_from_bundle(source_bundle)
        except Exception as exc:
            return ClipResult.failure(f"Invalid source bundle: {exc}")

        request = ClipRequest(
            image_paths=[Path(item) for item in (source.resolved_frame_paths() or source.resolved_segment_output_paths())],
            output_dir=output_dir,
            settings=settings or ClipSettings(),
            clip_name=clip_name or source.source_id or "clip",
            source_bundle=source_bundle,
        )
        return self.build_clip(request)

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

    def _export_image_sequence(
        self,
        *,
        image_paths: list[Path],
        output_path: str | Path,
        fps: int,
        codec: str,
        quality: str,
        mode: str,
        duration_per_image: float,
        transition_duration: float,
    ) -> Path:
        return export_image_sequence_video(
            image_paths=image_paths,
            output_path=output_path,
            fps=fps,
            codec=codec,
            quality=quality,
            mode=mode,
            duration_per_image=duration_per_image,
            transition_duration=transition_duration,
            creator=self._creator,
        )

    def _estimate_duration_seconds(
        self,
        *,
        settings: ClipSettings,
        frame_count: int,
        has_frame_source: bool,
    ) -> float:
        if not has_frame_source:
            return 0.0
        if settings.mode == "slideshow":
            return frame_count * settings.duration_per_image
        return frame_count / max(1, settings.fps)
