"""Admission for Movie Clips assembly (PR-VID-ASM-332): intent -> frozen spec -> NJR.

``freeze_movie_assembly`` reads every source once (the oriented size of an image, a bounded FFprobe of each video and
of the audio track) and hashes it, resolves "match the first clip" to concrete numbers and the encode profile to a
concrete CRF and preset, and checks the frame plan, so nothing is derived at run time. ``build_movie_assembly_njr``
compiles the frozen spec into the one-stage VIDEO NJR that ``JobService.submit_njrs`` admits. Nothing here encodes,
queues or runs a job.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_input_verification import sha256_of
from src.pipeline.reprocess_builder import ReprocessJobBuilder
from src.pipeline.video import resolve_encode_settings
from src.state.output_routing import OUTPUT_ROUTE_MOVIE_CLIPS
from src.utils.managed_process import run_bounded
from src.video.container_metadata import resolve_ffprobe_executable
from src.video.driving_video_inspection import inspect_driving_video
from src.video.movie_assembly_models import (
    ASSEMBLY_MODES,
    AUDIO_EXTENSIONS,
    CLIP_KIND_VIDEO,
    CODEC_ALIASES,
    MAX_DIMENSION,
    MAX_FPS,
    MAX_SEQUENCE_FRAMES,
    MAX_SLIDESHOW_CLIPS,
    MIN_DIMENSION,
    MIN_FPS,
    MODE_SEQUENCE,
    MODE_SLIDESHOW,
    MOVIE_ASSEMBLY_STAGE,
    AssemblyAudio,
    AssemblyClip,
    AssemblyEncode,
    MovieAssemblySpec,
    MovieAssemblySpecError,
    kind_for_suffix,
    plan_timeline,
)

RESOLUTION_MATCH_FIRST = "match_first"
DEFAULT_STILL_SECONDS = 3.0
DEFAULT_TRANSITION_SECONDS = 0.5
DEFAULT_FADE_OUT_SECONDS = 1.0
DEFAULT_CLIP_NAME = "movie"
AUDIO_PROBE_TIMEOUT_SECONDS = 10.0
_AUDIO_PROBE_MAX_STDOUT_BYTES = 64 * 1024
_EXIF_ORIENTATION = 0x0112
#: EXIF orientations that rotate the image by 90 degrees (width and height swap for display).
_SWAPPED_ORIENTATIONS = frozenset({5, 6, 7, 8})
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_RESOLUTION_PATTERN = re.compile(r"(\d+)\s*[xX]\s*(\d+)")


class MovieAssemblyAdmissionError(ValueError):
    """The request cannot be admitted; the message is written for the operator."""


@dataclass(frozen=True, slots=True)
class AssemblyIntentClip:
    path: str
    #: A still's hold time in slideshow mode; ``None`` uses the request's default.
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class MovieAssemblyIntent:
    """What the operator asked for, before anything is read or frozen."""

    clips: tuple[AssemblyIntentClip, ...]
    mode: str = MODE_SLIDESHOW
    fps: int = 24
    #: ``match_first`` or ``WIDTHxHEIGHT``.
    resolution: str = RESOLUTION_MATCH_FIRST
    still_seconds: float = DEFAULT_STILL_SECONDS
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS
    codec: str = "libx264"
    #: An encode profile (draft / balanced / archival) or an x264 speed preset.
    quality: str = "balanced"
    audio_path: str | None = None
    audio_fade_out_seconds: float = DEFAULT_FADE_OUT_SECONDS
    clip_name: str = DEFAULT_CLIP_NAME


@dataclass(frozen=True, slots=True)
class VideoFacts:
    width: int
    height: int
    duration_seconds: float
    fps: float | None


VideoProbe = Callable[[Path], VideoFacts]
AudioProbe = Callable[[Path], float | None]
FileHasher = Callable[[str | Path], str]


def probe_video(path: Path) -> VideoFacts:
    """Display size, duration and reported rate of a video, through the bounded FFprobe inspection."""

    inspection = inspect_driving_video(path, frame_count=0)
    facts = inspection.facts
    if facts is None:
        reason = inspection.issues[0].message if inspection.issues else "it could not be read."
        raise MovieAssemblyAdmissionError(f"{path.name}: {reason}")
    if not facts.duration_seconds or facts.duration_seconds <= 0:
        raise MovieAssemblyAdmissionError(
            f"{path.name} does not report a duration, so it cannot be placed."
        )
    return VideoFacts(
        width=facts.display_width,
        height=facts.display_height,
        duration_seconds=float(facts.duration_seconds),
        fps=facts.reported_fps,
    )


def probe_audio_duration(path: Path, *, ffprobe: str | Path | None = None) -> float | None:
    """The duration of the first audio stream (``None`` when it reports none); refuses a file without audio."""

    executable = ffprobe if ffprobe is not None else resolve_ffprobe_executable()
    if executable is None:
        raise MovieAssemblyAdmissionError(
            "FFprobe was not found, so the audio track cannot be checked. Install FFmpeg or set STABLENEW_FFMPEG_PATH."
        )
    command = [
        str(executable),
        "-v",
        "error",
        "-hide_banner",
        "-protocol_whitelist",
        "file",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type,duration:format=duration",
        "-of",
        "json",
        "-i",
        str(path),
    ]
    outcome = run_bounded(
        command,
        timeout_seconds=AUDIO_PROBE_TIMEOUT_SECONDS,
        max_stdout_bytes=_AUDIO_PROBE_MAX_STDOUT_BYTES,
    )
    if (
        outcome.launch_error
        or outcome.timed_out
        or outcome.output_truncated
        or outcome.returncode != 0
    ):
        raise MovieAssemblyAdmissionError(f"The audio track {path.name} could not be read.")
    try:
        payload = json.loads(outcome.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as exc:
        raise MovieAssemblyAdmissionError(
            f"The audio track {path.name} could not be read."
        ) from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not streams:
        raise MovieAssemblyAdmissionError(f"{path.name} has no audio track.")
    for candidate in (streams[0].get("duration"), (payload.get("format") or {}).get("duration")):
        if candidate is None:
            continue
        try:
            seconds = float(candidate)
        except ValueError:
            continue
        if seconds > 0:
            return seconds
    return None


def oriented_image_size(path: Path) -> tuple[int, int]:
    """The size an image is displayed at (EXIF rotation applied), read from its header."""

    try:
        with Image.open(path) as image:
            width, height = image.size
            orientation = image.getexif().get(_EXIF_ORIENTATION)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise MovieAssemblyAdmissionError(f"{path.name} is not a readable image ({exc}).") from exc
    if orientation in _SWAPPED_ORIENTATIONS:
        return height, width
    return width, height


def resolve_target_size(resolution: str, first_clip_size: tuple[int, int]) -> tuple[int, int]:
    """Concrete even output dimensions for ``match_first`` or ``WIDTHxHEIGHT``."""

    text = str(resolution or RESOLUTION_MATCH_FIRST).strip()
    if text.lower() == RESOLUTION_MATCH_FIRST:
        width, height = first_clip_size
        longest = max(width, height)
        if longest > MAX_DIMENSION:  # keep the first clip's shape, within the supported frame
            width = round(width * MAX_DIMENSION / longest)
            height = round(height * MAX_DIMENSION / longest)
    else:
        match = _RESOLUTION_PATTERN.fullmatch(text)
        if match is None:
            raise MovieAssemblyAdmissionError(
                f"Resolution must be {RESOLUTION_MATCH_FIRST!r} or WIDTHxHEIGHT, got {resolution!r}."
            )
        width, height = int(match.group(1)), int(match.group(2))
    width, height = width - width % 2, height - height % 2
    if not (MIN_DIMENSION <= width <= MAX_DIMENSION and MIN_DIMENSION <= height <= MAX_DIMENSION):
        raise MovieAssemblyAdmissionError(
            f"The output size {width}x{height} is outside {MIN_DIMENSION}-{MAX_DIMENSION} pixels per side."
        )
    return width, height


def sanitize_clip_name(name: str) -> str:
    """A file-name-safe clip name (letters, digits, ``.``, ``_``, ``-``)."""

    cleaned = _UNSAFE_NAME_CHARS.sub("_", str(name or "").strip()).strip("._-")
    return cleaned[:64] or DEFAULT_CLIP_NAME


def _hash(hash_file: FileHasher, path: Path) -> str:
    try:
        return hash_file(path)
    except OSError as exc:
        raise MovieAssemblyAdmissionError(f"{path.name} could not be read ({exc}).") from exc


def _freeze_clip(
    index: int,
    item: AssemblyIntentClip,
    intent: MovieAssemblyIntent,
    *,
    probe: VideoProbe,
    hash_file: FileHasher,
) -> AssemblyClip:
    path = Path(item.path).expanduser()
    if not path.is_file():
        raise MovieAssemblyAdmissionError(f"Item {index} does not exist or was moved: {path}")
    path = path.resolve()
    kind = kind_for_suffix(path.suffix)
    if kind is None:
        raise MovieAssemblyAdmissionError(
            f"Item {index} ({path.name}) is not a supported image or video file."
        )
    if kind == CLIP_KIND_VIDEO:
        if intent.mode == MODE_SEQUENCE:
            raise MovieAssemblyAdmissionError(
                f"Item {index} ({path.name}) is a video; a frame sequence takes images only. "
                "Switch Mode to slideshow to mix videos and stills."
            )
        facts = probe(path)
        width, height, duration, source_fps = (
            facts.width,
            facts.height,
            facts.duration_seconds,
            facts.fps,
        )
    else:
        width, height = oriented_image_size(path)
        source_fps = None
        if intent.mode == MODE_SEQUENCE:
            duration = 0.0
        else:
            chosen = (
                intent.still_seconds if item.duration_seconds is None else item.duration_seconds
            )
            duration = float(chosen)
    return AssemblyClip(
        path=str(path),
        sha256=_hash(hash_file, path),
        kind=kind,
        width=int(width),
        height=int(height),
        duration_seconds=duration,
        source_fps=source_fps,
    )


def _freeze_audio(
    intent: MovieAssemblyIntent, *, probe: AudioProbe, hash_file: FileHasher
) -> AssemblyAudio | None:
    if not str(intent.audio_path or "").strip():
        return None
    path = Path(str(intent.audio_path)).expanduser()
    if not path.is_file():
        raise MovieAssemblyAdmissionError(f"The audio track does not exist or was moved: {path}")
    path = path.resolve()
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise MovieAssemblyAdmissionError(
            f"{path.name} is not a supported audio file ({', '.join(sorted(AUDIO_EXTENSIONS))})."
        )
    duration = probe(path)
    return AssemblyAudio(
        path=str(path),
        sha256=_hash(hash_file, path),
        fade_out_seconds=float(intent.audio_fade_out_seconds or 0.0),
        duration_seconds=duration,
    )


def freeze_movie_assembly(
    intent: MovieAssemblyIntent,
    *,
    video_probe: VideoProbe = probe_video,
    audio_probe: AudioProbe = probe_audio_duration,
    hash_file: FileHasher = sha256_of,
) -> MovieAssemblySpec:
    """Read, hash and measure every input once and return the spec the NJR freezes.

    Raises ``MovieAssemblyAdmissionError`` with an operator-facing message for anything that cannot run.
    """

    if not intent.clips:
        raise MovieAssemblyAdmissionError("Add at least one image or video to assemble.")
    if intent.mode not in ASSEMBLY_MODES:
        raise MovieAssemblyAdmissionError(
            f"Mode must be one of {', '.join(ASSEMBLY_MODES)}, got {intent.mode!r}."
        )
    fps = int(intent.fps)
    if not MIN_FPS <= fps <= MAX_FPS:
        raise MovieAssemblyAdmissionError(f"FPS must be {MIN_FPS}-{MAX_FPS}, got {fps}.")
    limit = MAX_SEQUENCE_FRAMES if intent.mode == MODE_SEQUENCE else MAX_SLIDESHOW_CLIPS
    if len(intent.clips) > limit:
        raise MovieAssemblyAdmissionError(
            f"{len(intent.clips)} items is more than the {limit} the {intent.mode} mode allows."
        )
    clips = tuple(
        _freeze_clip(index, item, intent, probe=video_probe, hash_file=hash_file)
        for index, item in enumerate(intent.clips, start=1)
    )
    width, height = resolve_target_size(intent.resolution, (clips[0].width, clips[0].height))
    encode = resolve_encode_settings(intent.quality)
    spec = MovieAssemblySpec(
        mode=intent.mode,
        clips=clips,
        width=width,
        height=height,
        fps=fps,
        transition_seconds=float(intent.transition_seconds or 0.0)
        if intent.mode == MODE_SLIDESHOW
        else 0.0,
        encode=AssemblyEncode(
            codec=CODEC_ALIASES.get(
                str(intent.codec or "").strip(), str(intent.codec or "").strip()
            ),
            crf=encode.crf,
            preset=encode.preset,
            pix_fmt=encode.pix_fmt,
        ),
        clip_name=sanitize_clip_name(intent.clip_name),
        audio=_freeze_audio(intent, probe=audio_probe, hash_file=hash_file),
    )
    errors = spec.validate()
    if errors:
        raise MovieAssemblyAdmissionError("; ".join(errors))
    try:
        timeline = plan_timeline(spec)
    except MovieAssemblySpecError as exc:
        raise MovieAssemblyAdmissionError(str(exc)) from exc
    if spec.audio is not None and spec.audio.fade_out_seconds > timeline.duration_seconds:
        raise MovieAssemblyAdmissionError(
            f"The {spec.audio.fade_out_seconds:g} s audio fade-out is longer than the "
            f"{timeline.duration_seconds:.2f} s movie."
        )
    return spec


def build_movie_assembly_njr(
    spec: MovieAssemblySpec,
    *,
    output_dir: str | Path = "output",
    output_route: str = OUTPUT_ROUTE_MOVIE_CLIPS,
    builder: ReprocessJobBuilder | None = None,
) -> NormalizedJobRecord:
    """The immutable one-stage VIDEO NJR for a frozen spec; its inputs are the clips in the operator's order."""

    timeline = plan_timeline(spec)
    builder = builder or ReprocessJobBuilder()  # type: ignore[no-untyped-call]  # unannotated constructor
    return builder.build_reprocess_job(
        input_image_paths=[clip.path for clip in spec.clips],
        stages=[MOVIE_ASSEMBLY_STAGE],
        config={MOVIE_ASSEMBLY_STAGE: spec.to_dict(), "pipeline": {"output_route": output_route}},
        output_dir=str(output_dir),
        prompt=f"Movie assembly: {spec.clip_name}",
        negative_prompt="",
        pack_name="Movie Clips",
        source="video",
        extra_metadata={
            MOVIE_ASSEMBLY_STAGE: {
                "schema": spec.schema,
                "mode": spec.mode,
                "clip_count": len(spec.clips),
                "total_frames": timeline.total_frames,
                "duration_seconds": round(timeline.duration_seconds, 3),
                "has_audio": spec.audio is not None,
            }
        },
    )


__all__ = [
    "AssemblyIntentClip",
    "DEFAULT_CLIP_NAME",
    "DEFAULT_FADE_OUT_SECONDS",
    "DEFAULT_STILL_SECONDS",
    "DEFAULT_TRANSITION_SECONDS",
    "MovieAssemblyAdmissionError",
    "MovieAssemblyIntent",
    "RESOLUTION_MATCH_FIRST",
    "VideoFacts",
    "build_movie_assembly_njr",
    "freeze_movie_assembly",
    "oriented_image_size",
    "probe_audio_duration",
    "probe_video",
    "resolve_target_size",
    "sanitize_clip_name",
]
