"""Export helpers for native video generation outputs."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from src.pipeline.video import VideoCreator
from src.video.svd_errors import SVDExportError


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
        ok = creator.create_video_from_images(frame_paths, output, fps=fps)
        if not ok:
            raise SVDExportError("VideoCreator failed to export MP4")
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
