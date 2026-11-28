"""Optional finishing of a finished clip: trim, then loop (VID-FINISH).

Applied after RIFE smoothing, by StableNew's own FFmpeg and encoder; the clip it reads is never modified. Trim cuts on
frame numbers (start and end are positions on the clip's timeline, in seconds); a loop then makes the trimmed clip
repeat cleanly, either forward-then-backward without doubling the two turning frames (``ping_pong``) or by blending its
last frames into its first ones (``crossfade``). Both are plain frame arithmetic, so the same job makes the same clip.

The optional SeedVR2 upscale is requested in the same ``finishing`` block (``upscale``) but runs before smoothing; its
own contract is ``src/video/seedvr2_upscale.py``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.video import (
    VideoEncodeCancelled,
    VideoEncodeSettings,
    build_video_encode_args,
    build_video_encode_filter,
    resolve_ffmpeg_executable,
    run_ffmpeg,
)

#: The stage-config and form key that carries the whole request.
FINISHING_KEY = "finishing"
LOOP_OFF = "off"
LOOP_PING_PONG = "ping_pong"
LOOP_CROSSFADE = "crossfade"
FINISH_LOOP_MODES: tuple[str, ...] = (LOOP_OFF, LOOP_PING_PONG, LOOP_CROSSFADE)
DEFAULT_CROSSFADE_SECONDS = 0.5
MAX_CROSSFADE_SECONDS = 2.0
_FRAME_TOTAL = re.compile(r"^frame=\s*(\d+)\s*$", re.MULTILINE)


class ClipFinishError(ValueError):
    """The finishing request is invalid or the clip could not be finished; the message says why."""


@dataclass(frozen=True)
class ClipFinishRequest:
    """What the operator asked for, already validated."""

    trim_start_seconds: float = 0.0
    trim_end_seconds: float | None = None
    loop_mode: str = LOOP_OFF
    crossfade_seconds: float = DEFAULT_CROSSFADE_SECONDS
    upscale: bool = False

    @property
    def trims(self) -> bool:
        return self.trim_start_seconds > 0 or self.trim_end_seconds is not None

    @property
    def edits(self) -> bool:
        """Whether the finished video file is cut or looped."""

        return self.trims or self.loop_mode != LOOP_OFF


@dataclass(frozen=True)
class FramePlan:
    """The exact frames of the input clip a request uses, and how many it makes."""

    start_frame: int
    end_frame: int
    crossfade_frames: int
    output_frame_count: int


@dataclass(frozen=True)
class ClipFinishResult:
    """What ran, for the manifest."""

    source_video_path: str
    video_path: str
    fps: int
    input_frame_count: int
    output_frame_count: int
    start_frame: int
    end_frame: int
    loop_mode: str
    crossfade_frames: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _seconds(value: Any, label: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ClipFinishError(f"{label} {value!r} is not a number of seconds") from exc
    if not math.isfinite(seconds):
        raise ClipFinishError(f"{label} {value!r} is not a number of seconds")
    if seconds < 0:
        raise ClipFinishError(f"{label} cannot be negative")
    return seconds


def normalize_finishing(value: Any) -> ClipFinishRequest | None:
    """Validate a form or frozen ``finishing`` block; ``None`` when it asks for nothing (the default)."""

    if not isinstance(value, Mapping):
        return None
    mode = str(value.get("loop_mode") or LOOP_OFF).strip().lower()
    if mode not in FINISH_LOOP_MODES:
        raise ClipFinishError(
            f"Unknown loop mode {mode!r} (expected one of {', '.join(FINISH_LOOP_MODES)})"
        )
    start = _seconds(value.get("trim_start_seconds"), "Trim start") or 0.0
    end = _seconds(value.get("trim_end_seconds"), "Trim end")
    if end is not None and end <= start:
        raise ClipFinishError("Trim end must be after trim start (leave it blank to keep the end)")
    crossfade = DEFAULT_CROSSFADE_SECONDS
    if mode == LOOP_CROSSFADE and value.get("crossfade_seconds") not in (None, ""):
        crossfade = _seconds(value.get("crossfade_seconds"), "The crossfade length") or 0.0
        if not 0 < crossfade <= MAX_CROSSFADE_SECONDS:
            raise ClipFinishError(
                f"The crossfade must be above 0 and at most {MAX_CROSSFADE_SECONDS:g} seconds"
            )
    request = ClipFinishRequest(
        trim_start_seconds=start,
        trim_end_seconds=end,
        loop_mode=mode,
        crossfade_seconds=crossfade,
        upscale=bool(value.get("upscale")),
    )
    return request if request.edits or request.upscale else None


def frozen_finishing(request: ClipFinishRequest) -> dict[str, Any]:
    """The loop and trim keys a job records: only what was chosen (the upscale block is added by its own module)."""

    data: dict[str, Any] = {}
    if request.loop_mode != LOOP_OFF:
        data["loop_mode"] = request.loop_mode
        if request.loop_mode == LOOP_CROSSFADE:
            data["crossfade_seconds"] = request.crossfade_seconds
    if request.trim_start_seconds > 0:
        data["trim_start_seconds"] = request.trim_start_seconds
    if request.trim_end_seconds is not None:
        data["trim_end_seconds"] = request.trim_end_seconds
    return data


def frame_plan(request: ClipFinishRequest, *, fps: int, frame_count: int) -> FramePlan:
    """Which frames of a ``frame_count`` clip at ``fps`` the request keeps; raises when it cannot be satisfied."""

    if fps < 1 or frame_count < 1:
        raise ClipFinishError("The clip's frame rate and length must be known to trim or loop it")
    length = f"the clip is {frame_count / fps:.2f} s long"
    start = round(request.trim_start_seconds * fps)
    end = frame_count if request.trim_end_seconds is None else round(request.trim_end_seconds * fps)
    if start >= frame_count:
        raise ClipFinishError(f"Trim start is past the end: {length}")
    if end > frame_count:
        raise ClipFinishError(f"Trim end is past the end: {length}")
    kept = end - start
    if kept < 1:
        raise ClipFinishError("Trim leaves no frames; move trim start and end further apart")
    crossfade = 0
    output = kept
    if request.loop_mode == LOOP_PING_PONG:
        if kept < 3:
            raise ClipFinishError("A ping-pong loop needs at least 3 frames after trimming")
        output = 2 * kept - 2
    elif request.loop_mode == LOOP_CROSSFADE:
        crossfade = max(1, round(request.crossfade_seconds * fps))
        if kept < 2 * crossfade + 1:
            raise ClipFinishError(
                f"The clip is too short for a {request.crossfade_seconds:g} s crossfade: it needs more than "
                f"{2 * crossfade / fps:.2f} s after trimming"
            )
        output = kept - crossfade
    return FramePlan(start, end, crossfade, output)


def check_against_clip(request: ClipFinishRequest, *, fps: int, frame_count: int) -> None:
    """Admission check: refuse at Queue what the finishing step would refuse after generation."""

    if request.edits:
        frame_plan(request, fps=fps, frame_count=frame_count)


def build_finish_filter(plan: FramePlan, loop_mode: str, *, fps: int) -> str:
    """The ``-filter_complex`` graph: trim, loop, restamp at a constant rate, then StableNew's colour filter."""

    def cut(start: int, end: int) -> str:
        return f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS"

    kept = plan.end_frame - plan.start_frame
    base = f"[0:v]{cut(plan.start_frame, plan.end_frame)}"
    tail = f"setpts=N/({fps}*TB),{build_video_encode_filter()}[out]"
    if loop_mode == LOOP_PING_PONG:
        return (
            f"{base},split[fwd][back];"
            f"[back]{cut(1, kept - 1)},reverse,setpts=PTS-STARTPTS[rev];"
            f"[fwd][rev]concat=n=2:v=1:a=0,{tail}"
        )
    if loop_mode == LOOP_CROSSFADE:
        fade = plan.crossfade_frames
        # The frame's index from its timestamp: ``blend``'s own ``N`` does not start at 0 in every FFmpeg.
        weight = f"(T*{fps}+1)/{fade + 1}"
        return (
            f"{base},split=3[a][b][c];"
            f"[a]{cut(0, fade)}[head];"
            f"[b]{cut(fade, kept - fade)}[body];"
            f"[c]{cut(kept - fade, kept)}[end];"
            f"[end][head]blend=all_expr='A*(1-{weight})+B*({weight})'[mix];"
            f"[body][mix]concat=n=2:v=1:a=0,{tail}"
        )
    return f"{base},{tail}"


def build_finish_command(
    ffmpeg: str | Path,
    source: str | Path,
    target: str | Path,
    fps: int,
    plan: FramePlan,
    loop_mode: str,
    settings: VideoEncodeSettings,
) -> list[str]:
    return [
        str(ffmpeg),
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        build_finish_filter(plan, loop_mode, fps=fps),
        "-map",
        "[out]",
        "-an",
        "-r",
        str(fps),
        *build_video_encode_args(
            codec="libx264", settings=settings, output_path=Path(target), include_filter=False
        ),
        str(target),
    ]


def _run(command: list[str], cancel_token: CancelToken | None, what: str) -> str:
    try:
        completed = run_ffmpeg(
            command, cancel=None if cancel_token is None else cancel_token.is_cancelled
        )
    except VideoEncodeCancelled as exc:
        raise CancellationError("video finishing cancelled") from exc
    if completed.returncode != 0:
        raise ClipFinishError(f"FFmpeg could not {what}: {completed.stderr.strip()}")
    return str(completed.stdout or "")


def count_video_frames(
    ffmpeg: str | Path, video_path: str | Path, cancel_token: CancelToken | None = None
) -> int:
    """The number of frames the clip decodes to."""

    output = _run(
        [
            str(ffmpeg),
            "-v",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-f",
            "null",
            "-progress",
            "pipe:1",
            "-",
        ],
        cancel_token,
        "read the clip",
    )
    totals = _FRAME_TOTAL.findall(output)
    if not totals or int(totals[-1]) < 1:
        raise ClipFinishError(f"FFmpeg found no frames in {Path(video_path).name}")
    return int(totals[-1])


def finish_video_file(
    *,
    video_path: str | Path,
    output_path: str | Path,
    fps: int,
    request: ClipFinishRequest,
    cancel_token: CancelToken | None = None,
) -> ClipFinishResult:
    """Trim and loop ``video_path`` into ``output_path``; the source file is left as it is."""

    source, target = Path(video_path), Path(output_path)
    ffmpeg = resolve_ffmpeg_executable()
    if ffmpeg is None:
        raise ClipFinishError("FFmpeg is not available to trim or loop the clip")
    if source == target:
        raise ClipFinishError("The finished clip must be a new file")
    frame_count = count_video_frames(ffmpeg, source, cancel_token)
    plan = frame_plan(request, fps=fps, frame_count=frame_count)
    command = build_finish_command(
        ffmpeg, source, target, fps, plan, request.loop_mode, VideoEncodeSettings()
    )
    try:
        _run(command, cancel_token, "trim or loop the clip")
        written = count_video_frames(ffmpeg, target, cancel_token)
        if written != plan.output_frame_count:
            raise ClipFinishError(
                f"The finished clip has {written} frames, not the planned {plan.output_frame_count}"
            )
    except BaseException:
        target.unlink(missing_ok=True)  # a partial or wrong clip must not look like a result
        raise
    return ClipFinishResult(
        source_video_path=str(source),
        video_path=str(target),
        fps=int(fps),
        input_frame_count=frame_count,
        output_frame_count=plan.output_frame_count,
        start_frame=plan.start_frame,
        end_frame=plan.end_frame,
        loop_mode=request.loop_mode,
        crossfade_frames=plan.crossfade_frames,
    )


__all__ = [
    "DEFAULT_CROSSFADE_SECONDS",
    "FINISHING_KEY",
    "FINISH_LOOP_MODES",
    "LOOP_CROSSFADE",
    "LOOP_OFF",
    "LOOP_PING_PONG",
    "MAX_CROSSFADE_SECONDS",
    "ClipFinishError",
    "ClipFinishRequest",
    "ClipFinishResult",
    "FramePlan",
    "build_finish_command",
    "build_finish_filter",
    "check_against_clip",
    "count_video_frames",
    "finish_video_file",
    "frame_plan",
    "frozen_finishing",
    "normalize_finishing",
]
