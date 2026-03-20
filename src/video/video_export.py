"""Export helpers for native video generation outputs and assembled-video flows."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from src.pipeline.video import VideoCreator, resolve_ffmpeg_executable
from src.video.svd_errors import SVDExportError


def export_image_sequence_video(
    *,
    image_paths: list[Path],
    output_path: str | Path,
    fps: int,
    codec: str = "libx264",
    quality: str = "medium",
    mode: str = "sequence",
    duration_per_image: float = 3.0,
    transition_duration: float = 0.5,
    creator: VideoCreator | None = None,
) -> Path:
    if not image_paths:
        raise SVDExportError("No image paths provided for export")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    resolved_creator = creator or VideoCreator()
    if not resolved_creator.ffmpeg_available:
        raise SVDExportError("FFmpeg is not available for image-sequence export")

    if mode == "slideshow":
        ok = resolved_creator.create_slideshow_video(
            image_paths=image_paths,
            output_path=output,
            duration_per_image=duration_per_image,
            transition_duration=transition_duration,
            fps=fps,
            codec=codec,
            quality=quality,
        )
    else:
        ok = resolved_creator.create_video_from_images(
            image_paths=image_paths,
            output_path=output,
            fps=fps,
            codec=codec,
            quality=quality,
        )

    if not ok:
        raise SVDExportError("VideoCreator failed to export image-sequence video")
    return output


def export_video_mp4(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
) -> Path:
    if not frames:
        raise SVDExportError("No frames provided for MP4 export")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    creator = VideoCreator()
    if not creator.ffmpeg_available:
        raise SVDExportError("FFmpeg is not available for MP4 export")

    with tempfile.TemporaryDirectory(prefix="svd_export_", dir=str(output.parent)) as temp_dir:
        frame_paths = save_video_frames(
            frames=frames,
            output_dir=temp_dir,
            prefix="frame",
        )
        export_image_sequence_video(
            image_paths=frame_paths,
            output_path=output,
            fps=fps,
            creator=creator,
        )
    return output


def export_video_gif(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
) -> Path:
    if not frames:
        raise SVDExportError("No frames provided for GIF export")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = max(1, int(round(1000 / max(1, fps))))
    first_frame, *rest = [frame.convert("RGB") for frame in frames]
    try:
        first_frame.save(
            output,
            format="GIF",
            save_all=True,
            append_images=rest,
            duration=duration_ms,
            loop=0,
        )
    except Exception as exc:
        raise SVDExportError(f"Failed to export GIF: {exc}") from exc
    return output


def save_video_frames(
    *,
    frames: list[Image.Image],
    output_dir: str | Path,
    prefix: str = "frame",
) -> list[Path]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for index, frame in enumerate(frames):
        frame_path = output_root / f"{prefix}_{index:06d}.png"
        frame.convert("RGB").save(frame_path, format="PNG")
        frame_paths.append(frame_path)
    return frame_paths


def stitch_video_segments(
    *,
    segment_paths: list[Path],
    output_path: str | Path,
) -> Path:
    if not segment_paths:
        raise SVDExportError("No segment paths provided for stitched export")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(segment_paths) == 1:
        source = Path(segment_paths[0])
        if source.resolve() != output.resolve():
            shutil.copy2(source, output)
        return output

    ffmpeg_executable = resolve_ffmpeg_executable()
    if ffmpeg_executable is None:
        raise SVDExportError("FFmpeg is not available for stitched export")

    list_file = output.parent / f"{output.stem}_concat.txt"
    try:
        with list_file.open("w", encoding="utf-8") as handle:
            for segment_path in segment_paths:
                escaped = str(Path(segment_path).absolute()).replace("'", r"'\''")
                handle.write(f"file '{escaped}'\n")

        cmd = [
            str(ffmpeg_executable),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-y",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise SVDExportError(f"FFmpeg failed to stitch video segments: {result.stderr}")
        return output
    except subprocess.TimeoutExpired as exc:
        raise SVDExportError("FFmpeg timed out while stitching video segments") from exc
    finally:
        list_file.unlink(missing_ok=True)
