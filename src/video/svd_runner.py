"""Orchestration layer for native SVD runs."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

from src.video.svd_config import SVDConfig
from src.video.svd_errors import SVDModelLoadError, SVDPostprocessError
from src.video.svd_models import SVDResult
from src.video.svd_postprocess import SVDPostprocessRunner, validate_svd_postprocess_config
from src.video.svd_preprocess import prepare_svd_input, validate_svd_source_image
from src.video.svd_registry import write_svd_run_manifest
from src.video.svd_service import SVDService
from src.video.container_metadata import write_video_container_metadata
from src.video.video_export import export_video_gif, export_video_mp4, save_video_frames

logger = logging.getLogger(__name__)


class SVDRunner:
    """Coordinates preprocess, frame generation, export, and manifest writeback."""

    def __init__(
        self,
        *,
        service: SVDService | None = None,
        output_root: str | Path,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._service = service or SVDService()
        self._output_root = Path(output_root)
        self._status_callback = status_callback

    def dry_validate(self, *, source_image_path: str | Path, config: SVDConfig) -> None:
        validate_svd_source_image(source_image_path)
        available, reason = self._service.is_available()
        if not available:
            raise SVDModelLoadError(reason or "SVD runtime is unavailable")
        valid, reason = validate_svd_postprocess_config(config)
        if not valid:
            raise SVDPostprocessError(reason or "SVD postprocess configuration is invalid")

    def run(
        self,
        *,
        source_image_path: str | Path,
        config: SVDConfig,
        job_id: str,
    ) -> SVDResult:
        self._output_root.mkdir(parents=True, exist_ok=True)
        temp_dir = self._output_root / "_svd_temp" / job_id
        frames: list = []
        try:
            logger.info(
                "[SVD] start job=%s source=%s model=%s frames=%s fps=%s decode_chunk=%s format=%s",
                job_id,
                Path(source_image_path).name,
                config.inference.model_id,
                config.inference.num_frames,
                config.inference.fps,
                config.inference.decode_chunk_size,
                config.output.output_format,
            )
            self._emit_status(stage_detail="preprocess", progress=0.05)
            preprocess = prepare_svd_input(
                source_path=source_image_path,
                config=config.preprocess,
                temp_dir=temp_dir,
            )
            logger.info(
                "[SVD] preprocess prepared=%s original=%sx%s target=%sx%s resize=%s resized=%s padded=%s cropped=%s",
                preprocess.prepared_path.name,
                preprocess.original_width,
                preprocess.original_height,
                preprocess.target_width,
                preprocess.target_height,
                preprocess.resize_mode,
                preprocess.was_resized,
                preprocess.was_padded,
                preprocess.was_cropped,
            )
            self._emit_status(
                stage_detail="inference",
                progress=0.3,
                current_step=0,
                total_steps=config.inference.num_frames,
            )
            frames = self._service.generate_frames(
                prepared_image_path=preprocess.prepared_path,
                config=config.inference,
            )
            logger.info("[SVD] inference completed frame_count=%s", len(frames))
            postprocess_enabled = any(
                (
                    config.postprocess.face_restore.enabled,
                    config.postprocess.interpolation.enabled,
                    config.postprocess.upscale.enabled,
                )
            )
            if postprocess_enabled:
                self._emit_status(
                    stage_detail="postprocess",
                    progress=0.6,
                    current_step=0,
                    total_steps=sum(
                        1
                        for enabled in (
                            config.postprocess.face_restore.enabled,
                            config.postprocess.interpolation.enabled,
                            config.postprocess.upscale.enabled,
                        )
                        if enabled
                    ),
                )
            frames, postprocess_metadata = SVDPostprocessRunner(
                status_callback=self._map_postprocess_status,
            ).process_frames(
                frames=frames,
                config=config,
                work_dir=temp_dir / "postprocess",
            )
            logger.info(
                "[SVD] postprocess completed frame_count=%s applied=%s",
                len(frames),
                list((postprocess_metadata or {}).get("applied") or []),
            )

            source_path = Path(source_image_path)
            stem = f"svd_{source_path.stem}"
            video_path = None
            gif_path = None
            frame_paths: list[Path] = []
            thumbnail_path = None

            self._emit_status(stage_detail="export", progress=0.9)

            if config.output.save_frames:
                frame_dir = self._output_root / f"{stem}_frames"
                frame_paths = save_video_frames(frames=frames, output_dir=frame_dir, prefix="frame")

            if config.output.output_format == "mp4":
                video_path = export_video_mp4(
                    frames=frames,
                    output_path=self._output_root / f"{stem}.mp4",
                    fps=config.inference.fps,
                )
            elif config.output.output_format == "gif":
                gif_path = export_video_gif(
                    frames=frames,
                    output_path=self._output_root / f"{stem}.gif",
                    fps=config.inference.fps,
                )
            elif not frame_paths:
                frame_dir = self._output_root / f"{stem}_frames"
                frame_paths = save_video_frames(frames=frames, output_dir=frame_dir, prefix="frame")

            if config.output.save_preview_image and frames:
                thumbnail_path = self._output_root / f"{stem}_preview.png"
                frames[0].save(thumbnail_path, format="PNG")

            result = SVDResult(
                source_image_path=source_path,
                video_path=video_path,
                gif_path=gif_path,
                frame_paths=frame_paths,
                thumbnail_path=thumbnail_path,
                metadata_path=None,
                frame_count=len(frames),
                fps=config.inference.fps,
                seed=config.inference.seed,
                model_id=config.inference.model_id,
                preprocess=preprocess,
                postprocess=postprocess_metadata,
            )
            manifest_path = write_svd_run_manifest(run_dir=self._output_root, config=config, result=result)
            metadata_payload = {
                "stage": "svd_native",
                "backend_id": "svd_native",
                "job_id": job_id,
                "run_id": self._output_root.name,
                "title": stem,
                "source_image_path": str(source_path),
                "video_path": str(video_path) if video_path else None,
                "video_paths": [str(video_path)] if video_path else [],
                "gif_path": str(gif_path) if gif_path else None,
                "gif_paths": [str(gif_path)] if gif_path else [],
                "frame_path_count": len(frame_paths),
                "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
                "fps": config.inference.fps,
                "frame_count": len(frames),
                "seed": config.inference.seed,
                "model_id": config.inference.model_id,
                "manifest_path": str(manifest_path),
                "config": config.to_dict(),
            }
            if video_path is not None:
                write_video_container_metadata(video_path, metadata_payload)
            if gif_path is not None:
                write_video_container_metadata(gif_path, metadata_payload)
            logger.info(
                "[SVD] complete video=%s gif=%s frame_files=%s preview=%s manifest=%s",
                result.video_path.name if result.video_path else None,
                result.gif_path.name if result.gif_path else None,
                len(result.frame_paths),
                result.thumbnail_path.name if result.thumbnail_path else None,
                manifest_path.name,
            )
            self._emit_status(stage_detail="complete", progress=1.0)
            return SVDResult(
                source_image_path=result.source_image_path,
                video_path=result.video_path,
                gif_path=result.gif_path,
                frame_paths=result.frame_paths,
                thumbnail_path=result.thumbnail_path,
                metadata_path=manifest_path,
                frame_count=result.frame_count,
                fps=result.fps,
                seed=result.seed,
                model_id=result.model_id,
                preprocess=result.preprocess,
                postprocess=result.postprocess,
            )
        finally:
            self._close_frames(frames)
            self._service._release_runtime_memory()

    @staticmethod
    def _close_frames(frames: list) -> None:
        for frame in frames:
            close = getattr(frame, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _map_postprocess_status(self, status: dict[str, Any]) -> None:
        local_progress = max(0.0, min(1.0, float(status.get("progress", 0.0) or 0.0)))
        self._emit_status(
            stage_detail=str(status.get("stage_detail") or "").strip() or "postprocess",
            progress=0.6 + (local_progress * 0.25),
            current_step=int(status.get("current_step", 0) or 0),
            total_steps=int(status.get("total_steps", 0) or 0),
            eta_seconds=status.get("eta_seconds"),
        )

    def _emit_status(
        self,
        *,
        stage_detail: str,
        progress: float,
        current_step: int = 0,
        total_steps: int = 0,
        eta_seconds: float | None = None,
    ) -> None:
        if self._status_callback is None:
            return
        try:
            self._status_callback(
                {
                    "stage_detail": stage_detail,
                    "progress": max(0.0, min(1.0, float(progress))),
                    "current_step": int(current_step),
                    "total_steps": int(total_steps),
                    "eta_seconds": eta_seconds,
                }
            )
        except Exception as exc:
            logger.warning("[SVD] status callback failed: %s", exc)
