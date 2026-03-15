"""Orchestration layer for native SVD runs."""

from __future__ import annotations

from pathlib import Path

from src.video.svd_config import SVDConfig
from src.video.svd_errors import SVDModelLoadError
from src.video.svd_models import SVDResult
from src.video.svd_preprocess import prepare_svd_input, validate_svd_source_image
from src.video.svd_registry import write_svd_run_manifest
from src.video.svd_service import SVDService
from src.video.video_export import export_video_gif, export_video_mp4, save_video_frames


class SVDRunner:
    """Coordinates preprocess, frame generation, export, and manifest writeback."""

    def __init__(self, *, service: SVDService | None = None, output_root: str | Path) -> None:
        self._service = service or SVDService()
        self._output_root = Path(output_root)

    def dry_validate(self, *, source_image_path: str | Path, config: SVDConfig) -> None:
        validate_svd_source_image(source_image_path)
        available, reason = self._service.is_available()
        if not available:
            raise SVDModelLoadError(reason or "SVD runtime is unavailable")
        _ = config

    def run(
        self,
        *,
        source_image_path: str | Path,
        config: SVDConfig,
        job_id: str,
    ) -> SVDResult:
        self._output_root.mkdir(parents=True, exist_ok=True)
        temp_dir = self._output_root / "_svd_temp" / job_id
        preprocess = prepare_svd_input(
            source_path=source_image_path,
            config=config.preprocess,
            temp_dir=temp_dir,
        )
        frames = self._service.generate_frames(
            prepared_image_path=preprocess.prepared_path,
            config=config.inference,
        )

        source_path = Path(source_image_path)
        stem = f"svd_{source_path.stem}"
        video_path = None
        gif_path = None
        frame_paths: list[Path] = []
        thumbnail_path = None

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
        )
        manifest_path = write_svd_run_manifest(run_dir=self._output_root, config=config, result=result)
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
        )
