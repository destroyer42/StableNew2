"""CPU-only media inspection with a verified input handle and bounded output."""

from __future__ import annotations

import json
from collections.abc import Sequence
from fractions import Fraction
from math import isfinite
from typing import Any, BinaryIO

from src.app.site_video_playback import VIDEO_LIMIT as VIDEO_LIMIT
from src.pipeline.video import resolve_ffmpeg_executable
from src.utils.managed_process import CancelSignal, run_bounded
from src.video.container_metadata import VIDEO_CONTAINER_METADATA_SCHEMA, resolve_ffprobe_executable

MAX_PIXELS = 64_000_000
EDGE = 320
MAX_PREVIEW_BYTES = 256 * 1024

# Limit FFmpeg's demuxers to the supported formats. In particular it must not
# interpret an arbitrary output as a playlist or follow references to other files.
_INPUT = (
    "-hide_banner",
    "-v",
    "error",
    "-max_alloc",
    str(96 * 1024**2),
    "-protocol_whitelist",
    "fd",
    "-format_whitelist",
    "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi",
    "-probesize",
    str(1024**2),
    "-analyzeduration",
    "1000000",
)


#: The restricted input options, shared with the review gateway's mobile transcode (RG-120).
INPUT_OPTIONS = _INPUT


def _media_command(
    command: Sequence[str], stream: BinaryIO, cap: int, cancel: CancelSignal | None
) -> bytes:
    outcome = run_bounded(
        command,
        timeout_seconds=3,
        max_stdout_bytes=cap,
        max_stderr_bytes=4096,
        stdin_file=stream,
        below_normal=True,
        cancel=cancel,
        memory_limit_mb=384,
        allow_unenforced_memory_limit=True,
    )
    if outcome.returncode == 0 and not outcome.output_truncated:
        return outcome.stdout
    return b""


def _positive_number(value: Any) -> float | None:
    try:
        number = float(Fraction(str(value)))
        return number if isfinite(number) and number > 0 else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def probe(stream: BinaryIO, cancel: CancelSignal | None = None) -> dict[str, Any]:
    tool = resolve_ffprobe_executable()
    if tool is None:
        return {}
    command = [
        str(tool),
        *_INPUT,
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,duration:stream_side_data=rotation:"
        "format=duration:format_tags=creation_time,stablenew_schema,description",
        "-of",
        "json",
        "-i",
        "fd:",
    ]
    try:
        data = json.loads(_media_command(command, stream, 192 * 1024, cancel))
        video = data["streams"][0]
        container = data.get("format", {})
        tags = container.get("tags", {})
        width, height = int(video["width"]), int(video["height"])
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            return {}
        if any(
            int(side.get("rotation", 0)) % 180 == 90 for side in video.get("side_data_list", [])
        ):
            width, height = height, width
        embedded = {}
        if tags.get("stablenew_schema") == VIDEO_CONTAINER_METADATA_SCHEMA:
            description = tags.get("description", "")
            if isinstance(description, str) and description.startswith("{"):
                value = json.loads(description)
                if isinstance(value, dict):
                    embedded = value
            if tags.get("creation_time"):
                embedded.setdefault("created_utc", tags["creation_time"])
        return {
            "width": width,
            "height": height,
            "duration": _positive_number(video.get("duration"))
            or _positive_number(container.get("duration")),
            "fps": _positive_number(video.get("avg_frame_rate")),
            "payload": embedded,
        }
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return {}


def poster(stream: BinaryIO, duration: float | None, cancel: CancelSignal | None = None) -> bytes:
    tool = resolve_ffmpeg_executable()
    if tool is None:
        return b""
    scale = f"scale=w='min(iw,{EDGE})':h='min(ih,{EDGE})':force_original_aspect_ratio=decrease"
    seek = ["-ss", f"{min(duration / 2, 2):.4f}"] if duration and duration >= 0.2 else []
    for position in (seek, []) if seek else ([],):
        stream.seek(0)
        command = [
            str(tool),
            *_INPUT,
            "-nostdin",
            "-threads",
            "1",
            *position,
            "-i",
            "fd:",
            "-map",
            "0:V:0",
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            "-filter_threads",
            "1",
            "-vf",
            scale,
            "-c:v",
            "mjpeg",
            "-threads",
            "1",
            "-f",
            "image2pipe",
            "pipe:1",
        ]
        if frame := _media_command(command, stream, MAX_PREVIEW_BYTES, cancel):
            return frame
        if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
            break
    return b""
