"""Export helpers for native video generation outputs and assembled-video flows."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video import (
    VideoCreator,
    VideoEncodeCancelled,
    VideoEncodeSettings,
    resolve_ffmpeg_executable,
    run_ffmpeg,
)
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
    settings: VideoEncodeSettings | None = None,
    cancel_token: CancelToken | None = None,
    require_all_frames: bool = False,
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
        # Passed only when set, so a creator without the strict mode keeps working unchanged.
        strict = {"require_all_frames": True} if require_all_frames else {}
        try:
            ok = resolved_creator.create_video_from_images(
                image_paths=image_paths,
                output_path=output,
                fps=fps,
                codec=codec,
                quality=quality,
                settings=settings,
                cancel=None if cancel_token is None else cancel_token.is_cancelled,
                **strict,
            )
        except VideoEncodeCancelled as exc:
            raise CancellationError("video export cancelled") from exc

    if not ok:
        if require_all_frames:
            raise SVDExportError(
                f"VideoCreator failed to export all {len(image_paths)} frames of the image sequence"
            )
        raise SVDExportError("VideoCreator failed to export image-sequence video")
    return output


def export_video_mp4(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
    settings: VideoEncodeSettings | None = None,
    cancel_token: CancelToken | None = None,
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
            settings=settings,
            cancel_token=cancel_token,
        )
    return output


def export_video_gif(
    *,
    frames: list[Image.Image],
    output_path: str | Path,
    fps: int,
    cancel_token: CancelToken | None = None,
) -> Path:
    """Export a looping GIF.

    With FFmpeg, one palette is built from the whole clip and applied with error diffusion,
    so colours do not shift from frame to frame. Without FFmpeg, Pillow's per-frame palette is
    the fallback.
    """

    if not frames:
        raise SVDExportError("No frames provided for GIF export")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_executable = resolve_ffmpeg_executable()
    if ffmpeg_executable is not None:
        _export_gif_with_ffmpeg(
            frames=frames,
            output=output,
            fps=fps,
            ffmpeg_executable=ffmpeg_executable,
            cancel_token=cancel_token,
        )
        return output
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


def _export_gif_with_ffmpeg(
    *,
    frames: list[Image.Image],
    output: Path,
    fps: int,
    ffmpeg_executable: Path,
    cancel_token: CancelToken | None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="gif_export_", dir=str(output.parent)) as temp_dir:
        save_video_frames(frames=frames, output_dir=temp_dir, prefix="frame")
        cmd = [
            str(ffmpeg_executable),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-framerate",
            str(int(fps)),
            "-start_number",
            "0",
            "-i",
            str(Path(temp_dir) / "frame_%06d.png"),
            "-filter_complex",
            "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a",
            "-loop",
            "0",
            str(output),
        ]
        try:
            result = run_ffmpeg(
                cmd, cancel=None if cancel_token is None else cancel_token.is_cancelled
            )
        except VideoEncodeCancelled as exc:
            output.unlink(missing_ok=True)
            raise CancellationError("GIF export cancelled") from exc
        if result.returncode != 0:
            output.unlink(missing_ok=True)
            raise SVDExportError(f"Failed to export GIF: {result.stderr}")


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
