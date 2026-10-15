"""Bounded, read-only inspection of a driving video (PR-VID-196).

Answers three operator questions without queueing anything: what does the file *report* about
itself (dimensions, frame rate, frame count, duration), can it actually be *decoded* (a few small
preview frames), and what could not be determined.  Metadata-derived values and measured facts are
kept apart: everything in ``DrivingVideoFacts`` is what FFprobe reports (or arithmetic on those
reports) and is labelled with its basis; only ``PreviewFrame`` entries are measured, because FFmpeg
really decoded them.

Bounds (all named, all tested):

* every subprocess has a wall-clock timeout, the whole inspection has a deadline and can be
  cancelled between and during processes;
* a process's stdout is read through a byte cap and the process is killed when it is exceeded, its
  stderr is drained but only a short prefix is kept;
* at most ``PREVIEW_FRAME_COUNT`` frames are decoded, each scaled down inside FFmpeg to at most
  ``PREVIEW_MAX_EDGE`` pixels, so a huge source can never produce a huge image in this process;
* nothing is written to disk, the driving file is only ever opened for reading, and only
  ``file`` protocols are allowed for the input.

Executables resolve through the repository's existing convention
(``resolve_ffmpeg_executable`` / ``resolve_ffprobe_executable``).  This module imports nothing from
the GUI, queue, controller or NJR layers.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable

# --- bounds -------------------------------------------------------------------------------------
PROBE_TIMEOUT_SECONDS = 10.0
FRAME_TIMEOUT_SECONDS = 10.0
INSPECTION_DEADLINE_SECONDS = 30.0
MAX_PROBE_STDOUT_BYTES = 64 * 1024
MAX_FRAME_STDOUT_BYTES = 512 * 1024
MAX_STDERR_BYTES = 2 * 1024
PREVIEW_FRAME_COUNT = 3
PREVIEW_MAX_EDGE = 160
MAX_REASONABLE_DIMENSION = 65535
MAX_REASONABLE_FPS = 1000.0
_CANCEL_POLL_SECONDS = 0.05
_KILL_WAIT_SECONDS = 5.0
_REPORTED_TEXT_LIMIT = 40
_STDERR_REASON_LIMIT = 80

# --- statuses and issue codes -------------------------------------------------------------------
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

ISSUE_FILE_MISSING = "file_missing"
ISSUE_FFPROBE_UNAVAILABLE = "ffprobe_unavailable"
ISSUE_FFMPEG_UNAVAILABLE = "ffmpeg_unavailable"
ISSUE_PROBE_FAILED = "probe_failed"
ISSUE_PROBE_TIMEOUT = "probe_timeout"
ISSUE_PROBE_OUTPUT_TOO_LARGE = "probe_output_too_large"
ISSUE_PROBE_UNREADABLE = "probe_unreadable"
ISSUE_NO_VIDEO_STREAM = "no_video_stream"
ISSUE_INVALID_DIMENSIONS = "invalid_dimensions"
ISSUE_FRAME_RATE_UNKNOWN = "frame_rate_unknown"
ISSUE_FRAME_COUNT_UNKNOWN = "frame_count_unknown"
ISSUE_DURATION_UNKNOWN = "duration_unknown"
ISSUE_FRAME_DECODE_FAILED = "frame_decode_failed"
ISSUE_FRAME_TIMEOUT = "frame_timeout"
ISSUE_DEADLINE_EXCEEDED = "deadline_exceeded"
ISSUE_CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class InspectionIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """What one bounded child process did.  ``stdout`` never exceeds the requested cap."""

    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    output_truncated: bool = False
    cancelled: bool = False
    launch_error: str = ""


class ProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        max_stdout_bytes: int,
        cancel: threading.Event | None = None,
    ) -> ProcessOutcome: ...


@dataclass(frozen=True, slots=True)
class DrivingVideoFacts:
    """What the file *reports*.  Nothing here was measured by decoding the whole clip."""

    container_format: str
    codec_name: str
    pixel_format: str
    coded_width: int
    coded_height: int
    rotation_quadrants: int  # 0..3; odd means width and height are swapped for display
    display_width: int
    display_height: int
    sample_aspect_ratio: str  # "" when square or unreported
    reported_fps: float | None
    fps_basis: str  # "average" | "base" | "unknown"
    fps_is_variable_suspected: bool
    reported_frame_count: int | None  # container/stream ``nb_frames`` when present
    estimated_frame_count: int | None  # round(duration * fps), only when nothing was reported
    frame_count_basis: str  # "reported" | "estimated" | "unknown"
    duration_seconds: float | None
    duration_basis: str  # "stream" | "container" | "unknown"

    @property
    def frame_count(self) -> int | None:
        if self.reported_frame_count is not None:
            return self.reported_frame_count
        return self.estimated_frame_count

    @property
    def orientation(self) -> str:
        if self.display_width == self.display_height:
            return "square"
        return "landscape" if self.display_width > self.display_height else "portrait"

    @property
    def aspect_ratio(self) -> float:
        return self.display_width / self.display_height


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    """One frame FFmpeg really decoded (measured), already scaled to a small PNG."""

    position_seconds: float
    width: int
    height: int
    png_bytes: bytes


@dataclass(frozen=True, slots=True)
class DrivingVideoInspection:
    path: str
    status: str
    facts: DrivingVideoFacts | None = None
    frames: tuple[PreviewFrame, ...] = ()
    issues: tuple[InspectionIssue, ...] = ()
    elapsed_seconds: float = 0.0
    requested_frames: int = 0

    @property
    def decoded(self) -> bool:
        return bool(self.frames)


# --- bounded process execution ------------------------------------------------------------------


def _read_capped(stream: Any, limit: int, sink: dict[str, Any], *, stop_on_overflow: bool) -> None:
    """Read ``stream`` to EOF keeping at most ``limit`` bytes.

    With ``stop_on_overflow`` the read stops as soon as more than ``limit`` bytes arrived (the
    caller then kills the process); otherwise the excess is drained and discarded so the child can
    never block on a full pipe."""

    kept = bytearray()
    overflow = False
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            room = limit - len(kept)
            if room > 0:
                kept.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                overflow = True
                if stop_on_overflow:
                    break
    except (OSError, ValueError):
        pass  # the pipe closed under us (process killed); what was read is what we have
    sink["data"] = bytes(kept)
    sink["overflow"] = overflow


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=_KILL_WAIT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def run_bounded_process(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int,
    cancel: threading.Event | None = None,
) -> ProcessOutcome:
    """Run one child with a wall-clock timeout, a stdout byte cap and cooperative cancellation."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(  # noqa: S603 - argv list, no shell, resolved executables
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        return ProcessOutcome(returncode=None, launch_error=str(exc) or type(exc).__name__)

    out_sink: dict[str, Any] = {}
    err_sink: dict[str, Any] = {}
    readers = [
        threading.Thread(
            target=_read_capped,
            args=(process.stdout, max_stdout_bytes, out_sink),
            kwargs={"stop_on_overflow": True},
            name="driving-video-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_read_capped,
            args=(process.stderr, MAX_STDERR_BYTES, err_sink),
            kwargs={"stop_on_overflow": False},
            name="driving-video-stderr",
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    timed_out = False
    cancelled = False
    stdout_reader = readers[0]
    while stdout_reader.is_alive():
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        stdout_reader.join(min(_CANCEL_POLL_SECONDS, remaining))

    truncated = bool(out_sink.get("overflow"))
    if timed_out or cancelled or truncated:
        _terminate(process)
    else:
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process)
    for reader in readers:
        reader.join(_KILL_WAIT_SECONDS)
    for stream in (process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    return ProcessOutcome(
        returncode=process.returncode,
        stdout=out_sink.get("data", b""),
        stderr=err_sink.get("data", b""),
        timed_out=timed_out,
        output_truncated=truncated,
        cancelled=cancelled,
    )


# --- probe parsing (pure) -----------------------------------------------------------------------


class ProbeParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clean_text(value: Any) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    return text.strip()[:_REPORTED_TEXT_LIMIT]


def _stderr_reason(stderr: bytes, video: Path) -> str:
    """First informative stderr line with the decoder prefix and the file path removed."""

    for raw in stderr.decode("utf-8", errors="replace").splitlines():
        line = re.sub(r"^\[[^\]]*\]\s*", "", raw.strip())
        line = line.replace(str(video), "").strip(" :")
        if line:
            return "".join(ch for ch in line if ch.isprintable())[:_STDERR_REASON_LIMIT]
    return ""


def _positive_int(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _rate(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        rate = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(rate) or rate <= 0 or rate > MAX_REASONABLE_FPS:
        return None
    return rate


def _rotation_quadrants(stream: Mapping[str, Any]) -> int:
    degrees: float | None = None
    for item in stream.get("side_data_list") or ():
        if isinstance(item, Mapping) and "rotation" in item:
            try:
                degrees = float(item["rotation"])
            except (TypeError, ValueError):
                degrees = None
            break
    if degrees is None:
        tags = stream.get("tags")
        if isinstance(tags, Mapping) and "rotate" in tags:
            try:
                degrees = float(tags["rotate"])
            except (TypeError, ValueError):
                degrees = None
    if degrees is None or not math.isfinite(degrees):
        return 0
    return int(round(degrees / 90.0)) % 4


def parse_probe_output(stdout: bytes) -> DrivingVideoFacts:
    """Facts from FFprobe's JSON.  Raises ``ProbeParseError`` with an operator-facing reason."""

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
    except ValueError as exc:
        raise ProbeParseError(
            ISSUE_PROBE_UNREADABLE, "FFprobe returned unreadable output."
        ) from exc
    if not isinstance(payload, Mapping):
        raise ProbeParseError(ISSUE_PROBE_UNREADABLE, "FFprobe returned unreadable output.")
    streams = payload.get("streams")
    video = next(
        (
            item
            for item in (streams if isinstance(streams, list) else ())
            if isinstance(item, Mapping)
        ),
        None,
    )
    if video is None:
        raise ProbeParseError(ISSUE_NO_VIDEO_STREAM, "The file has no readable video stream.")
    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    if (
        width is None
        or height is None
        or width > MAX_REASONABLE_DIMENSION
        or height > MAX_REASONABLE_DIMENSION
    ):
        raise ProbeParseError(
            ISSUE_INVALID_DIMENSIONS, "The video stream reports unusable dimensions."
        )

    quadrants = _rotation_quadrants(video)
    display_width, display_height = (height, width) if quadrants % 2 else (width, height)

    average = _rate(video.get("avg_frame_rate"))
    base = _rate(video.get("r_frame_rate"))
    if average is not None:
        fps, fps_basis = average, "average"
    elif base is not None:
        fps, fps_basis = base, "base"
    else:
        fps, fps_basis = None, "unknown"
    variable = (
        average is not None and base is not None and abs(average - base) / max(base, 1e-9) > 0.01
    )

    container = payload.get("format")
    container = container if isinstance(container, Mapping) else {}
    duration = _positive_float(video.get("duration"))
    duration_basis = "stream"
    if duration is None:
        duration = _positive_float(container.get("duration"))
        duration_basis = "container"
    if duration is None:
        duration_basis = "unknown"

    reported_frames = _positive_int(video.get("nb_frames"))
    estimated: int | None = None
    if reported_frames is None and duration is not None and fps is not None:
        estimated = max(1, int(round(duration * fps)))
    frame_basis = (
        "reported" if reported_frames is not None else "estimated" if estimated else "unknown"
    )

    sample_ratio = _clean_text(video.get("sample_aspect_ratio"))
    if sample_ratio in {"1:1", "0:1", "N/A"}:
        sample_ratio = ""

    return DrivingVideoFacts(
        container_format=_clean_text(container.get("format_name")),
        codec_name=_clean_text(video.get("codec_name")),
        pixel_format=_clean_text(video.get("pix_fmt")),
        coded_width=width,
        coded_height=height,
        rotation_quadrants=quadrants,
        display_width=display_width,
        display_height=display_height,
        sample_aspect_ratio=sample_ratio,
        reported_fps=fps,
        fps_basis=fps_basis,
        fps_is_variable_suspected=variable,
        reported_frame_count=reported_frames,
        estimated_frame_count=estimated,
        frame_count_basis=frame_basis,
        duration_seconds=duration,
        duration_basis=duration_basis,
    )


def preview_positions(
    duration_seconds: float | None, count: int = PREVIEW_FRAME_COUNT
) -> list[float]:
    """Representative seek times: the start, the middle and near the end of a known duration."""

    if count <= 1 or duration_seconds is None or duration_seconds <= 0:
        return [0.0]
    if count == 2:
        return [0.0, round(duration_seconds * 0.9, 3)]
    middle = round(duration_seconds * 0.5, 3)
    late = round(duration_seconds * 0.9, 3)
    return [0.0, middle, late][:count]


# --- commands -----------------------------------------------------------------------------------

_PROBE_ENTRIES = (
    "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,pix_fmt,"
    "sample_aspect_ratio:stream_tags=rotate:stream_side_data=rotation:format=format_name,duration"
)


def build_probe_command(ffprobe: str | Path, video: str | Path) -> list[str]:
    return [
        str(ffprobe),
        "-v",
        "error",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-select_streams",
        "v:0",
        "-show_entries",
        _PROBE_ENTRIES,
        "-of",
        "json",
        "-i",
        str(video),
    ]


def build_frame_command(
    ffmpeg: str | Path, video: str | Path, position_seconds: float, max_edge: int = PREVIEW_MAX_EDGE
) -> list[str]:
    scale = (
        f"scale=w='min(iw,{max_edge})':h='min(ih,{max_edge})':force_original_aspect_ratio=decrease"
    )
    return [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-ss",
        f"{max(0.0, position_seconds):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        scale,
        "-fs",
        str(MAX_FRAME_STDOUT_BYTES),
        "-f",
        "image2pipe",
        "-c:v",
        "png",
        "pipe:1",
    ]


def _decode_preview(png_bytes: bytes, max_edge: int) -> tuple[int, int] | None:
    """Dimensions of a complete, small PNG, or None when it is truncated/corrupt/oversized."""

    try:
        with Image.open(io.BytesIO(png_bytes)) as image:
            image.load()
            width, height = image.size
    except Exception:
        return None
    if width <= 0 or height <= 0 or width > max_edge or height > max_edge:
        return None
    return width, height


# --- inspection ---------------------------------------------------------------------------------


def inspect_driving_video(
    path: str | Path,
    *,
    runner: ProcessRunner = run_bounded_process,
    ffprobe: str | Path | None = None,
    ffmpeg: str | Path | None = None,
    frame_count: int = PREVIEW_FRAME_COUNT,
    cancel: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> DrivingVideoInspection:
    """Inspect ``path`` within the module's bounds.  Never raises for a bad or missing file."""

    started = clock()
    text = str(path or "").strip()
    wanted = max(0, min(int(frame_count), PREVIEW_FRAME_COUNT))

    def done(
        status: str,
        *,
        facts: DrivingVideoFacts | None = None,
        frames: Sequence[PreviewFrame] = (),
        issues: Sequence[InspectionIssue] = (),
    ) -> DrivingVideoInspection:
        return DrivingVideoInspection(
            path=text,
            status=status,
            facts=facts,
            frames=tuple(frames),
            issues=tuple(issues),
            elapsed_seconds=max(0.0, clock() - started),
            requested_frames=wanted,
        )

    def failure(code: str, message: str) -> DrivingVideoInspection:
        return done(STATUS_FAILED, issues=(InspectionIssue(code, message),))

    if not text:
        return failure(ISSUE_FILE_MISSING, "No driving video is selected.")
    try:
        video = Path(text).expanduser()
        if not video.is_file():
            return failure(ISSUE_FILE_MISSING, f"Driving video does not exist: {video}")
        video = video.resolve()
    except OSError as exc:
        return failure(ISSUE_FILE_MISSING, f"Driving video cannot be accessed: {exc}")

    probe_executable = ffprobe if ffprobe is not None else resolve_ffprobe_executable()
    if probe_executable is None:
        return failure(
            ISSUE_FFPROBE_UNAVAILABLE,
            "FFprobe was not found, so the driving video cannot be inspected. Install FFmpeg or "
            "set STABLENEW_FFMPEG_PATH.",
        )

    def remaining() -> float:
        return INSPECTION_DEADLINE_SECONDS - (clock() - started)

    outcome = runner(
        build_probe_command(probe_executable, video),
        timeout_seconds=min(PROBE_TIMEOUT_SECONDS, max(0.0, remaining())),
        max_stdout_bytes=MAX_PROBE_STDOUT_BYTES,
        cancel=cancel,
    )
    if outcome.cancelled:
        return failure(ISSUE_CANCELLED, "Inspection was cancelled.")
    if outcome.launch_error:
        return failure(
            ISSUE_FFPROBE_UNAVAILABLE, f"FFprobe could not be started: {outcome.launch_error}"
        )
    if outcome.timed_out:
        return failure(
            ISSUE_PROBE_TIMEOUT,
            f"FFprobe did not answer within {PROBE_TIMEOUT_SECONDS:g} seconds.",
        )
    if outcome.output_truncated:
        return failure(
            ISSUE_PROBE_OUTPUT_TOO_LARGE, "FFprobe produced more output than inspection allows."
        )
    if outcome.returncode != 0:
        reason = _stderr_reason(outcome.stderr, video)
        suffix = f" ({reason})" if reason else ""
        return failure(
            ISSUE_PROBE_FAILED,
            "FFprobe could not read this file; it may be corrupt, truncated or an unsupported "
            f"format{suffix}.",
        )
    try:
        facts = parse_probe_output(outcome.stdout)
    except ProbeParseError as exc:
        return failure(exc.code, exc.message)

    issues: list[InspectionIssue] = []
    if facts.reported_fps is None:
        issues.append(
            InspectionIssue(
                ISSUE_FRAME_RATE_UNKNOWN, "The file does not report a usable frame rate."
            )
        )
    if facts.frame_count is None:
        issues.append(
            InspectionIssue(ISSUE_FRAME_COUNT_UNKNOWN, "The file does not report a frame count.")
        )
    if facts.duration_seconds is None:
        issues.append(
            InspectionIssue(ISSUE_DURATION_UNKNOWN, "The file does not report a duration.")
        )

    frames: list[PreviewFrame] = []
    ffmpeg_executable = ffmpeg if ffmpeg is not None else resolve_ffmpeg_executable()
    if wanted == 0:
        pass
    elif ffmpeg_executable is None:
        issues.append(
            InspectionIssue(
                ISSUE_FFMPEG_UNAVAILABLE,
                "FFmpeg was not found, so preview frames cannot be decoded.",
            )
        )
    else:
        for position in preview_positions(facts.duration_seconds, wanted):
            if cancel is not None and cancel.is_set():
                issues.append(InspectionIssue(ISSUE_CANCELLED, "Inspection was cancelled."))
                break
            budget = remaining()
            if budget <= 0:
                issues.append(
                    InspectionIssue(
                        ISSUE_DEADLINE_EXCEEDED,
                        f"Inspection stopped after {INSPECTION_DEADLINE_SECONDS:g} seconds.",
                    )
                )
                break
            frame_outcome = runner(
                build_frame_command(ffmpeg_executable, video, position),
                timeout_seconds=min(FRAME_TIMEOUT_SECONDS, budget),
                max_stdout_bytes=MAX_FRAME_STDOUT_BYTES,
                cancel=cancel,
            )
            if frame_outcome.cancelled:
                issues.append(InspectionIssue(ISSUE_CANCELLED, "Inspection was cancelled."))
                break
            if frame_outcome.timed_out:
                issues.append(
                    InspectionIssue(
                        ISSUE_FRAME_TIMEOUT,
                        f"Decoding the frame at {position:g}s timed out.",
                    )
                )
                break  # a stalled decoder will stall the next seek too
            size = (
                None
                if frame_outcome.returncode != 0
                or frame_outcome.output_truncated
                or not frame_outcome.stdout
                else _decode_preview(frame_outcome.stdout, PREVIEW_MAX_EDGE)
            )
            if size is None:
                issues.append(
                    InspectionIssue(
                        ISSUE_FRAME_DECODE_FAILED,
                        f"The frame at {position:g}s could not be decoded.",
                    )
                )
                continue
            frames.append(
                PreviewFrame(
                    position_seconds=position,
                    width=size[0],
                    height=size[1],
                    png_bytes=frame_outcome.stdout,
                )
            )

    cancelled_issue = any(issue.code == ISSUE_CANCELLED for issue in issues)
    if cancelled_issue:
        status = STATUS_PARTIAL
    elif wanted and not frames:
        status = STATUS_PARTIAL
    elif wanted and len(frames) < len(preview_positions(facts.duration_seconds, wanted)):
        status = STATUS_PARTIAL
    else:
        status = STATUS_OK
    return done(status, facts=facts, frames=frames, issues=issues)


__all__ = [
    "FRAME_TIMEOUT_SECONDS",
    "INSPECTION_DEADLINE_SECONDS",
    "MAX_FRAME_STDOUT_BYTES",
    "MAX_PROBE_STDOUT_BYTES",
    "MAX_STDERR_BYTES",
    "PREVIEW_FRAME_COUNT",
    "PREVIEW_MAX_EDGE",
    "PROBE_TIMEOUT_SECONDS",
    "STATUS_FAILED",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "DrivingVideoFacts",
    "DrivingVideoInspection",
    "InspectionIssue",
    "PreviewFrame",
    "ProbeParseError",
    "ProcessOutcome",
    "ProcessRunner",
    "build_frame_command",
    "build_probe_command",
    "inspect_driving_video",
    "parse_probe_output",
    "preview_positions",
    "run_bounded_process",
]
