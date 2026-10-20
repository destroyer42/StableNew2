"""Bounded, read-only review previews of existing video outputs (PR-VID-QUALITY-211).

The comparison window needs real frames it can step through, not a player.  ``prepare_review_preview``
asks FFmpeg (through the repository's contained ``run_bounded`` process primitive) to decode the first
frames of one clip, scale them down inside FFmpeg and hand back raw RGB bytes over a byte-capped pipe.
Nothing is written to disk, the original is only ever opened for reading, only the ``file`` protocol is
allowed, and no GPU, model, network or Comfy process is involved.

The result is a *review preview*: a downscaled, frame-exact sample.  It never claims to preserve every
visual property of the original (colour handling, sample aspect ratio, full resolution); the window labels
it as such and offers the original file in the system viewer.

Bounds (named, tested):

* ``MAX_PREVIEW_EDGE`` pixels on the longer side, ``MAX_PREVIEW_FRAMES`` frames and ``MAX_PREVIEW_BYTES`` raw
  bytes per clip, so a clip can never become a large in-memory image sequence;
* a wall-clock timeout per process and cooperative cancellation (a stale request is cancelled and its
  result discarded by the caller);
* clips above ``MAX_PREVIEW_DECODE_PIXELS`` are not decoded.

Failures are values, never exceptions: missing FFmpeg, a missing or corrupt file, a timeout and a cancel
each yield a ``PreviewResult`` with ``status == STATUS_FAILED`` and an operator-readable message.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.pipeline.video import resolve_ffmpeg_executable
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import (
    ISSUE_CANCELLED,
    ISSUE_FFMPEG_UNAVAILABLE,
    ISSUE_FFPROBE_UNAVAILABLE,
    ISSUE_FILE_MISSING,
    ISSUE_FRAME_DECODE_FAILED,
    ISSUE_FRAME_TIMEOUT,
    ISSUE_FRAME_TOO_LARGE,
    ISSUE_PROBE_FAILED,
    ISSUE_PROBE_OUTPUT_TOO_LARGE,
    ISSUE_PROBE_TIMEOUT,
    MAX_PREVIEW_DECODE_PIXELS,
    MAX_PROBE_STDOUT_BYTES,
    PROBE_TIMEOUT_SECONDS,
    DrivingVideoFacts,
    ProbeParseError,
    ProcessRunner,
    build_probe_command,
    parse_probe_output,
    run_bounded_process,
)

MAX_PREVIEW_EDGE = 256
MAX_PREVIEW_FRAMES = 120
MAX_PREVIEW_BYTES = 24 * 1024 * 1024
DECODE_TIMEOUT_SECONDS = 60.0
DEFAULT_PLAYBACK_FPS = 24.0

STATUS_OK = "ok"
STATUS_FAILED = "failed"

ISSUE_DECODE_OUTPUT_TOO_LARGE = "decode_output_too_large"


@dataclass(frozen=True)
class PreviewClip:
    """Decoded review preview of one clip (frames are raw RGB, ``width * height * 3`` bytes each)."""

    path: str
    width: int
    height: int
    source_width: int
    source_height: int
    fps: float | None
    frame_count: int
    reported_frame_count: int | None
    duration_seconds: float | None
    raw: bytes
    note: str = ""

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 3

    @property
    def truncated(self) -> bool:
        """True when the preview holds fewer frames than the original reports."""

        return (
            self.reported_frame_count is not None and self.frame_count < self.reported_frame_count
        )

    @property
    def effective_fps(self) -> float:
        return self.fps if self.fps else DEFAULT_PLAYBACK_FPS

    @property
    def fps_is_assumed(self) -> bool:
        return not self.fps

    def frame_image(self, index: int) -> Image.Image:
        """One preview frame as a PIL image; ``index`` is clamped into the decoded range."""

        position = max(0, min(int(index), self.frame_count - 1))
        start = position * self.frame_bytes
        return Image.frombytes(
            "RGB", (self.width, self.height), self.raw[start : start + self.frame_bytes]
        )


@dataclass(frozen=True)
class PreviewResult:
    path: str
    status: str
    clip: PreviewClip | None = None
    issue_code: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.clip is not None


def _failure(path: str, code: str, message: str) -> PreviewResult:
    return PreviewResult(path=path, status=STATUS_FAILED, issue_code=code, message=message)


def preview_dimensions(
    display_width: int, display_height: int, max_edge: int = MAX_PREVIEW_EDGE
) -> tuple[int, int]:
    """Even, aspect-preserving output size no larger than ``max_edge`` on the longer side."""

    scale = min(1.0, max_edge / max(display_width, display_height))
    width = max(2, int(round(display_width * scale / 2.0)) * 2)
    height = max(2, int(round(display_height * scale / 2.0)) * 2)
    return min(width, max_edge), min(height, max_edge)


def frames_allowed(
    frame_bytes: int, reported_frames: int | None, max_frames: int, max_bytes: int
) -> int:
    """How many frames to request: the clip's own count, bounded by frame and byte limits."""

    wanted = max_frames if reported_frames is None else min(max_frames, reported_frames)
    return max(0, min(wanted, max_bytes // max(1, frame_bytes)))


def build_decode_command(
    ffmpeg: str | Path, video: str | Path, width: int, height: int, frames: int
) -> list[str]:
    return [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-i",
        str(video),
        "-an",
        "-sn",
        "-dn",
        "-fps_mode",
        "passthrough",
        "-frames:v",
        str(frames),
        "-vf",
        f"scale={width}:{height}:flags=area",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def _stderr_reason(stderr: bytes) -> str:
    for raw in stderr.decode("utf-8", errors="replace").splitlines():
        line = "".join(ch for ch in raw.strip() if ch.isprintable())
        if line:
            return line[:80]
    return ""


def _probe(
    path: str,
    video: Path,
    ffprobe: str | Path,
    runner: ProcessRunner,
    cancel: threading.Event | None,
) -> DrivingVideoFacts | PreviewResult:
    outcome = runner(
        build_probe_command(ffprobe, video),
        timeout_seconds=PROBE_TIMEOUT_SECONDS,
        max_stdout_bytes=MAX_PROBE_STDOUT_BYTES,
        cancel=cancel,
    )
    if outcome.cancelled:
        return _failure(path, ISSUE_CANCELLED, "Preview preparation was cancelled.")
    if outcome.launch_error:
        return _failure(
            path, ISSUE_FFPROBE_UNAVAILABLE, f"FFprobe could not be started: {outcome.launch_error}"
        )
    if outcome.timed_out:
        return _failure(
            path,
            ISSUE_PROBE_TIMEOUT,
            f"FFprobe did not answer within {PROBE_TIMEOUT_SECONDS:g} seconds.",
        )
    if outcome.output_truncated:
        return _failure(
            path, ISSUE_PROBE_OUTPUT_TOO_LARGE, "FFprobe produced more output than allowed."
        )
    if outcome.returncode != 0:
        reason = _stderr_reason(outcome.stderr)
        return _failure(
            path,
            ISSUE_PROBE_FAILED,
            "FFprobe could not read this file; it may be corrupt, truncated or an unsupported format"
            + (f" ({reason})." if reason else "."),
        )
    try:
        return parse_probe_output(outcome.stdout)
    except ProbeParseError as exc:
        return _failure(path, exc.code, exc.message)


def prepare_review_preview(
    path: str | Path,
    *,
    runner: ProcessRunner = run_bounded_process,
    ffprobe: str | Path | None = None,
    ffmpeg: str | Path | None = None,
    cancel: threading.Event | None = None,
    max_edge: int = MAX_PREVIEW_EDGE,
    max_frames: int = MAX_PREVIEW_FRAMES,
    max_bytes: int = MAX_PREVIEW_BYTES,
) -> PreviewResult:
    """Decode a bounded, downscaled, frame-exact preview of ``path``.  Never raises for a bad file."""

    text = str(path or "").strip()
    try:
        video = Path(text).expanduser()
        if not text or not video.is_file():
            return _failure(
                text, ISSUE_FILE_MISSING, f"The video file does not exist: {text or '(none)'}"
            )
        video = video.resolve()
    except (OSError, ValueError) as exc:
        return _failure(text, ISSUE_FILE_MISSING, f"The video file cannot be accessed: {exc}")

    probe_exe = ffprobe if ffprobe is not None else resolve_ffprobe_executable()
    decode_exe = ffmpeg if ffmpeg is not None else resolve_ffmpeg_executable()
    if probe_exe is None or decode_exe is None:
        missing = "FFprobe" if probe_exe is None else "FFmpeg"
        code = ISSUE_FFPROBE_UNAVAILABLE if probe_exe is None else ISSUE_FFMPEG_UNAVAILABLE
        return _failure(
            text,
            code,
            f"{missing} was not found, so no review preview can be shown. Install FFmpeg or set "
            "STABLENEW_FFMPEG_PATH; ratings and the original file stay available.",
        )

    probed = _probe(text, video, probe_exe, runner, cancel)
    if isinstance(probed, PreviewResult):
        return probed
    facts = probed
    if facts.coded_width * facts.coded_height > MAX_PREVIEW_DECODE_PIXELS:
        return _failure(
            text,
            ISSUE_FRAME_TOO_LARGE,
            f"Frames are {facts.coded_width}x{facts.coded_height}; review previews are not decoded "
            f"above {MAX_PREVIEW_DECODE_PIXELS / 1e6:.0f} megapixels. Open the original instead.",
        )
    width, height = preview_dimensions(facts.display_width, facts.display_height, max_edge)
    frame_bytes = width * height * 3
    wanted = frames_allowed(frame_bytes, facts.frame_count, max_frames, max_bytes)
    if wanted < 1:
        return _failure(
            text, ISSUE_FRAME_TOO_LARGE, "The preview bounds leave no room for even one frame."
        )

    outcome = runner(
        build_decode_command(decode_exe, video, width, height, wanted),
        timeout_seconds=DECODE_TIMEOUT_SECONDS,
        max_stdout_bytes=wanted * frame_bytes + 1,
        cancel=cancel,
    )
    if outcome.cancelled:
        return _failure(text, ISSUE_CANCELLED, "Preview preparation was cancelled.")
    if outcome.launch_error:
        return _failure(
            text, ISSUE_FFMPEG_UNAVAILABLE, f"FFmpeg could not be started: {outcome.launch_error}"
        )
    if outcome.timed_out:
        return _failure(
            text,
            ISSUE_FRAME_TIMEOUT,
            f"Decoding the preview did not finish within {DECODE_TIMEOUT_SECONDS:g} seconds.",
        )
    if outcome.output_truncated:
        return _failure(
            text,
            ISSUE_DECODE_OUTPUT_TOO_LARGE,
            "The decoder produced more output than the preview allows.",
        )
    decoded = len(outcome.stdout) // frame_bytes
    if decoded < 1:
        reason = _stderr_reason(outcome.stderr)
        return _failure(
            text,
            ISSUE_FRAME_DECODE_FAILED,
            "No frame of this video could be decoded; the file may be corrupt or use an unsupported codec"
            + (f" ({reason})." if reason else "."),
        )
    note = ""
    if outcome.returncode != 0:
        note = f"Decoding stopped early; only the first {decoded} frames are available."
    return PreviewResult(
        path=text,
        status=STATUS_OK,
        clip=PreviewClip(
            path=text,
            width=width,
            height=height,
            source_width=facts.display_width,
            source_height=facts.display_height,
            fps=facts.reported_fps,
            frame_count=decoded,
            reported_frame_count=facts.frame_count,
            duration_seconds=facts.duration_seconds,
            raw=bytes(outcome.stdout[: decoded * frame_bytes]),
            note=note,
        ),
    )


def describe_preview(clip: PreviewClip) -> str:
    """One honest line about what the preview is (never claims to be the original)."""

    parts = [
        f"Review preview {clip.width}x{clip.height} of the original {clip.source_width}x{clip.source_height}",
        f"{clip.frame_count} frame(s)",
    ]
    if clip.reported_frame_count is not None and clip.truncated:
        parts.append(f"first {clip.frame_count} of {clip.reported_frame_count}")
    parts.append(f"{clip.effective_fps:g} fps" + (" (assumed)" if clip.fps_is_assumed else ""))
    if clip.note:
        parts.append(clip.note)
    return "; ".join(parts)


__all__ = [
    "DECODE_TIMEOUT_SECONDS",
    "DEFAULT_PLAYBACK_FPS",
    "ISSUE_DECODE_OUTPUT_TOO_LARGE",
    "MAX_PREVIEW_BYTES",
    "MAX_PREVIEW_EDGE",
    "MAX_PREVIEW_FRAMES",
    "STATUS_FAILED",
    "STATUS_OK",
    "PreviewClip",
    "PreviewResult",
    "build_decode_command",
    "describe_preview",
    "frames_allowed",
    "prepare_review_preview",
    "preview_dimensions",
]
