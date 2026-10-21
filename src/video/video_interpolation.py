"""Backend-neutral RIFE smoothing of a finished video file (PR-VID-SMOOTH-302).

Native SVD smooths its frames in process (``SVDPostprocessRunner``). A Comfy clip arrives as an encoded file, so
this module decodes it with FFmpeg, runs the *same* RIFE stage with the *same* model choice and factor rule, and
re-encodes with StableNew's one encoder (``export_video_mp4``), so the result gets the same quality settings,
colour tags and cancellation as every other clip. The original file is never touched.

The request is a small plain block (``{"enabled", "multiplier", "executable_path", "model_dir"}``) so any backend
can carry it in its stage config; ``normalize_interpolation_request`` validates it before anything dispatches.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video import (
    VideoEncodeCancelled,
    resolve_ffmpeg_executable,
    run_ffmpeg,
)
from src.video.rife_runtime import (
    default_rife_multiplier,
    find_rife_executable,
    get_rife_multiplier_validation_error,
)
from src.video.svd_config import SVDConfig
from src.video.svd_errors import SVDExportError, SVDPostprocessError
from src.video.svd_postprocess import SVDPostprocessRunner, validate_svd_postprocess_config
from src.video.video_export import export_video_mp4

DECODE_TIMEOUT_SECONDS = 600.0
# Bound the decoded clip held in memory: the smoothed clip is up to 4x this many frames.
MAX_SOURCE_FRAMES = 400


@dataclass(frozen=True)
class VideoInterpolationRequest:
    """What the operator asked for, already validated."""

    multiplier: int | None = None
    executable_path: str | None = None
    model_dir: str | None = None


@dataclass(frozen=True)
class VideoInterpolationResult:
    """What ran, for the manifest."""

    source_video_path: str
    video_path: str
    input_frame_count: int
    output_frame_count: int
    input_fps: int
    output_fps: int
    multiplier: int
    model: str | None = None
    commands: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_interpolation_request(value: Any) -> VideoInterpolationRequest | None:
    """Validate a stage-config ``interpolation`` block; ``None`` when absent or not enabled.

    Raises ``ValueError`` (a readable message, before any dispatch) for an unsupported factor or when no RIFE
    runtime resolves, so a clip is never generated only to fail at the smoothing step.
    """

    if not isinstance(value, Mapping) or not bool(value.get("enabled")):
        return None
    raw_multiplier = value.get("multiplier")
    multiplier: int | None = None
    if raw_multiplier not in (None, ""):
        try:
            multiplier = int(raw_multiplier)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RIFE interpolation multiplier {raw_multiplier!r} is not a number"
            ) from exc
        error = get_rife_multiplier_validation_error(multiplier)
        if error:
            raise ValueError(error)
    executable_path = str(value.get("executable_path") or "").strip() or None
    model_dir = str(value.get("model_dir") or "").strip() or None
    if find_rife_executable(executable_path) is None:
        raise ValueError(
            "RIFE interpolation is enabled but no rife-ncnn-vulkan executable was found. "
            "Set the RIFE executable in Engine Settings or the SVD tab, set STABLENEW_RIFE_EXE, "
            "or unpack a release into tools/rife. Nothing was generated."
        )
    return VideoInterpolationRequest(
        multiplier=multiplier, executable_path=executable_path, model_dir=model_dir
    )


def _decode_frames(
    *, video_path: Path, work_dir: Path, cancel_token: CancelToken | None
) -> list[Image.Image]:
    ffmpeg = resolve_ffmpeg_executable()
    if ffmpeg is None:
        raise SVDExportError("FFmpeg is not available to decode the clip for interpolation")
    frame_dir = work_dir / "decoded_frames"
    if frame_dir.exists():
        shutil.rmtree(frame_dir, ignore_errors=True)
    frame_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg),
        "-v",
        "error",
        "-i",
        str(video_path),
        "-vsync",
        "0",
        "-y",
        str(frame_dir / "frame_%06d.png"),
    ]
    try:
        completed = run_ffmpeg(
            command,
            timeout_seconds=DECODE_TIMEOUT_SECONDS,
            cancel=None if cancel_token is None else cancel_token.is_cancelled,
        )
    except VideoEncodeCancelled as exc:
        raise CancellationError("video interpolation cancelled") from exc
    if completed.returncode != 0:
        raise SVDExportError(f"FFmpeg could not decode the clip: {completed.stderr.strip()}")
    paths = sorted(frame_dir.glob("frame_*.png"))
    if not paths:
        raise SVDExportError("FFmpeg decoded no frames from the clip")
    if len(paths) > MAX_SOURCE_FRAMES:
        raise SVDExportError(
            f"The clip has {len(paths)} frames; interpolation handles at most {MAX_SOURCE_FRAMES}."
        )
    frames: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as image:
            frames.append(image.convert("RGB"))
    return frames


def interpolate_video_file(
    *,
    video_path: str | Path,
    output_dir: str | Path,
    source_fps: int,
    request: VideoInterpolationRequest,
    cancel_token: CancelToken | None = None,
    status_callback: Callable[[dict[str, Any]], None] | None = None,
) -> VideoInterpolationResult:
    """Smooth ``video_path`` into a new ``<stem>_smooth.mp4`` beside the other outputs."""

    source = Path(video_path)
    root = Path(output_dir)
    if source_fps < 1:
        raise ValueError("source_fps must be a positive integer")
    multiplier = request.multiplier or default_rife_multiplier(source_fps)
    config = SVDConfig.from_dict(
        {
            "inference": {"fps": int(source_fps)},
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "multiplier": multiplier,
                    "executable_path": request.executable_path,
                    "model_dir": request.model_dir,
                }
            },
        }
    )
    valid, reason = validate_svd_postprocess_config(config)
    if not valid:
        raise SVDPostprocessError(reason or "RIFE interpolation is not available")

    work_dir = root / f"{source.stem}_smooth_work"
    output_path = root / f"{source.stem}_smooth.mp4"
    frames: list[Image.Image] = []
    input_count = 0
    try:
        frames = _decode_frames(video_path=source, work_dir=work_dir, cancel_token=cancel_token)
        input_count = len(frames)
        smoothed, metadata = SVDPostprocessRunner(
            status_callback=status_callback, cancel_token=cancel_token
        ).process_frames(frames=frames, config=config, work_dir=work_dir / "rife")
        frames = smoothed
        interpolation = dict((metadata or {}).get("interpolation") or {})
        output_fps = int(source_fps) * multiplier
        export_video_mp4(
            frames=frames, output_path=output_path, fps=output_fps, cancel_token=cancel_token
        )
    finally:
        for image in frames:
            image.close()
        shutil.rmtree(work_dir, ignore_errors=True)
    return VideoInterpolationResult(
        source_video_path=str(source),
        video_path=str(output_path),
        input_frame_count=input_count,
        output_frame_count=len(frames),
        input_fps=int(source_fps),
        output_fps=output_fps,
        multiplier=multiplier,
        model=interpolation.get("model"),
        commands=[list(command) for command in interpolation.get("commands") or []],
    )


__all__ = [
    "VideoInterpolationRequest",
    "VideoInterpolationResult",
    "interpolate_video_file",
    "normalize_interpolation_request",
]
