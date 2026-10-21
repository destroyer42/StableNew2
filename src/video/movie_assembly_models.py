"""The frozen Movie Clips assembly contract (PR-VID-ASM-332).

An assembly job's NJR freezes one ``MovieAssemblySpec`` under ``config["movie_assembly"]`` at admission: the clips in
the user's order with their SHA-256 and measured facts, the target frame size and rate, the transition, the optional
audio track and the resolved encoder settings. ``plan_timeline`` turns a spec into exact frame counts, so admission and
execution agree on every cut. This module is pure data and arithmetic: no file access, FFmpeg, queue or GUI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

MOVIE_ASSEMBLY_STAGE: Final = "movie_assembly"
MOVIE_ASSEMBLY_SCHEMA = "stablenew.movie_assembly.v1"

#: Every image is one frame, in list order (an image sequence).
MODE_SEQUENCE = "sequence"
#: Every item is a clip: a still holds for its duration, a video plays in full, clips may crossfade.
MODE_SLIDESHOW = "slideshow"
ASSEMBLY_MODES = (MODE_SEQUENCE, MODE_SLIDESHOW)

CLIP_KIND_IMAGE = "image"
CLIP_KIND_VIDEO = "video"

STILL_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".gif"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"})
#: Software encoders only: the queue treats an assembly job as GPU-free, so a hardware encoder is never accepted.
SOFTWARE_VIDEO_CODECS = frozenset({"libx264", "libx265", "libvpx-vp9"})
#: Names the Movie Clips tab offers for an encoder (FFmpeg resolves a bare codec name to an arbitrary encoder).
CODEC_ALIASES = {"vp9": "libvpx-vp9"}

MIN_FPS = 1
MAX_FPS = 120
MIN_DIMENSION = 16
MAX_DIMENSION = 4096
MIN_STILL_SECONDS = 0.1
MAX_STILL_SECONDS = 300.0
MAX_TRANSITION_SECONDS = 5.0
MAX_FADE_OUT_SECONDS = 10.0
#: Each slideshow clip is one FFmpeg input; a frame sequence is one image2 input of numbered frames.
MAX_SLIDESHOW_CLIPS = 200
MAX_SEQUENCE_FRAMES = 10_000


class MovieAssemblySpecError(ValueError):
    """A spec (frozen or about to be frozen) is malformed or cannot be planned."""


def kind_for_suffix(suffix: str) -> str | None:
    """``image`` or ``video`` for a supported source file suffix, otherwise ``None``."""

    lowered = str(suffix or "").lower()
    if lowered in STILL_EXTENSIONS:
        return CLIP_KIND_IMAGE
    if lowered in VIDEO_EXTENSIONS:
        return CLIP_KIND_VIDEO
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require(data: Mapping[str, Any], key: str) -> Any:
    if key not in data or data[key] is None:
        raise MovieAssemblySpecError(f"movie assembly spec is missing {key!r}")
    return data[key]


@dataclass(frozen=True, slots=True)
class AssemblyClip:
    path: str
    sha256: str
    kind: str
    #: Oriented (display) size as measured at admission.
    width: int
    height: int
    #: A still's hold time in slideshow mode (0 in sequence mode, where every image is one frame); a video's duration.
    duration_seconds: float
    #: The frame rate a video reported (informational; the target rate is ``MovieAssemblySpec.fps``).
    source_fps: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "kind": self.kind,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
            "source_fps": self.source_fps,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AssemblyClip:
        fps = data.get("source_fps")
        return cls(
            path=str(_require(data, "path")),
            sha256=str(_require(data, "sha256")),
            kind=str(_require(data, "kind")),
            width=int(_require(data, "width")),
            height=int(_require(data, "height")),
            duration_seconds=float(_require(data, "duration_seconds")),
            source_fps=None if fps is None else float(fps),
        )


@dataclass(frozen=True, slots=True)
class AssemblyAudio:
    path: str
    sha256: str
    #: Seconds of fade-out at the end of the movie (0 = none).
    fade_out_seconds: float
    #: The track's own duration as measured at admission (informational: the movie length decides).
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "fade_out_seconds": self.fade_out_seconds,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AssemblyAudio:
        duration = data.get("duration_seconds")
        return cls(
            path=str(_require(data, "path")),
            sha256=str(_require(data, "sha256")),
            fade_out_seconds=float(data.get("fade_out_seconds") or 0.0),
            duration_seconds=None if duration is None else float(duration),
        )


@dataclass(frozen=True, slots=True)
class AssemblyEncode:
    """Resolved encoder settings (not a profile name), so a replay encodes exactly the same way."""

    codec: str
    crf: int
    preset: str
    pix_fmt: str = "yuv420p"

    def to_dict(self) -> dict[str, Any]:
        return {
            "codec": self.codec,
            "crf": self.crf,
            "preset": self.preset,
            "pix_fmt": self.pix_fmt,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AssemblyEncode:
        return cls(
            codec=str(_require(data, "codec")),
            crf=int(_require(data, "crf")),
            preset=str(_require(data, "preset")),
            pix_fmt=str(data.get("pix_fmt") or "yuv420p"),
        )


@dataclass(frozen=True, slots=True)
class MovieAssemblySpec:
    mode: str
    clips: tuple[AssemblyClip, ...]
    width: int
    height: int
    fps: int
    transition_seconds: float
    encode: AssemblyEncode
    clip_name: str
    audio: AssemblyAudio | None = None
    schema: str = MOVIE_ASSEMBLY_SCHEMA

    def validate(self) -> list[str]:
        """Every reason this spec cannot be executed (empty when it can)."""

        errors: list[str] = []
        if self.schema != MOVIE_ASSEMBLY_SCHEMA:
            errors.append(f"unsupported movie assembly schema {self.schema!r}")
        if self.mode not in ASSEMBLY_MODES:
            errors.append(f"mode must be one of {', '.join(ASSEMBLY_MODES)}, got {self.mode!r}")
        if not self.clips:
            errors.append("at least one clip is required")
        limit = MAX_SEQUENCE_FRAMES if self.mode == MODE_SEQUENCE else MAX_SLIDESHOW_CLIPS
        if len(self.clips) > limit:
            errors.append(f"{len(self.clips)} items is more than the {limit} this mode allows")
        if not MIN_FPS <= self.fps <= MAX_FPS:
            errors.append(f"fps must be {MIN_FPS}-{MAX_FPS}, got {self.fps}")
        for name, value in (("width", self.width), ("height", self.height)):
            if not MIN_DIMENSION <= value <= MAX_DIMENSION or value % 2:
                errors.append(
                    f"{name} must be an even number of pixels in {MIN_DIMENSION}-{MAX_DIMENSION}, got {value}"
                )
        if not 0.0 <= self.transition_seconds <= MAX_TRANSITION_SECONDS:
            errors.append(f"transition must be 0-{MAX_TRANSITION_SECONDS:g} seconds")
        if self.mode == MODE_SEQUENCE and self.transition_seconds > 0:
            errors.append("a frame sequence has no transitions (use slideshow mode)")
        if self.encode.codec not in SOFTWARE_VIDEO_CODECS:
            errors.append(
                f"codec must be one of {', '.join(sorted(SOFTWARE_VIDEO_CODECS))}, got {self.encode.codec!r}"
            )
        if not self.clip_name.strip():
            errors.append("clip name must not be empty")
        for index, clip in enumerate(self.clips, start=1):
            label = f"item {index} ({clip.path})"
            if clip.kind not in (CLIP_KIND_IMAGE, CLIP_KIND_VIDEO):
                errors.append(f"{label} has an unknown kind {clip.kind!r}")
            elif clip.kind == CLIP_KIND_VIDEO and self.mode == MODE_SEQUENCE:
                errors.append(
                    f"{label} is a video; a frame sequence takes images only (use slideshow mode)"
                )
            elif self.mode == MODE_SLIDESHOW and clip.kind == CLIP_KIND_IMAGE:
                if not MIN_STILL_SECONDS <= clip.duration_seconds <= MAX_STILL_SECONDS:
                    errors.append(
                        f"{label} must hold for {MIN_STILL_SECONDS:g}-{MAX_STILL_SECONDS:g} seconds"
                    )
            elif clip.kind == CLIP_KIND_VIDEO and clip.duration_seconds <= 0:
                errors.append(f"{label} has no usable duration")
            if len(clip.sha256) != 64:
                errors.append(f"{label} has no recorded SHA-256")
        if self.audio is not None:
            if len(self.audio.sha256) != 64:
                errors.append("the audio track has no recorded SHA-256")
            if not 0.0 <= self.audio.fade_out_seconds <= MAX_FADE_OUT_SECONDS:
                errors.append(f"audio fade-out must be 0-{MAX_FADE_OUT_SECONDS:g} seconds")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "clips": [clip.to_dict() for clip in self.clips],
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "transition_seconds": self.transition_seconds,
            "encode": self.encode.to_dict(),
            "clip_name": self.clip_name,
            "audio": self.audio.to_dict() if self.audio is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MovieAssemblySpec:
        """Rebuild a frozen spec; a malformed record raises ``MovieAssemblySpecError`` (never a partial spec)."""

        if not isinstance(data, Mapping) or not data:
            raise MovieAssemblySpecError("movie assembly spec is missing")
        try:
            clips = tuple(
                AssemblyClip.from_dict(_mapping(item)) for item in data.get("clips") or ()
            )
            audio_data = data.get("audio")
            return cls(
                schema=str(data.get("schema") or ""),
                mode=str(_require(data, "mode")),
                clips=clips,
                width=int(_require(data, "width")),
                height=int(_require(data, "height")),
                fps=int(_require(data, "fps")),
                transition_seconds=float(data.get("transition_seconds") or 0.0),
                encode=AssemblyEncode.from_dict(_mapping(_require(data, "encode"))),
                clip_name=str(_require(data, "clip_name")),
                audio=AssemblyAudio.from_dict(_mapping(audio_data)) if audio_data else None,
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, MovieAssemblySpecError):
                raise
            raise MovieAssemblySpecError(f"movie assembly spec is malformed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class AssemblyTimeline:
    """Exact frame arithmetic for one spec at its target rate."""

    fps: int
    #: Frames each item contributes before transitions overlap them.
    clip_frames: tuple[int, ...]
    #: Frames each crossfade overlaps two neighbours (0 = hard cuts).
    transition_frames: int
    #: Where each crossfade starts, in output frames (one per boundary; empty without transitions).
    transition_offsets: tuple[int, ...]
    total_frames: int

    @property
    def duration_seconds(self) -> float:
        return self.total_frames / self.fps

    @property
    def transition_seconds(self) -> float:
        return self.transition_frames / self.fps


def frames_for(seconds: float, fps: int) -> int:
    """Whole frames for a duration at ``fps`` (rounded, at least one)."""

    return max(1, round(float(seconds) * int(fps)))


def plan_timeline(spec: MovieAssemblySpec) -> AssemblyTimeline:
    """The frame plan of ``spec``. Raises ``MovieAssemblySpecError`` when the transition cannot fit.

    A crossfade overlaps the end of one item with the start of the next, so with N items and T transition frames
    the movie has sum(frames) - (N - 1) * T frames. Each item must be at least 2 * T frames long, otherwise its two
    crossfades would overlap each other.
    """

    fps = int(spec.fps)
    if fps < MIN_FPS:
        raise MovieAssemblySpecError(f"fps must be at least {MIN_FPS}")
    if spec.mode == MODE_SEQUENCE:
        frames = tuple(1 for _ in spec.clips)
        return AssemblyTimeline(fps, frames, 0, (), len(frames))
    frames = tuple(frames_for(clip.duration_seconds, fps) for clip in spec.clips)
    transition = round(float(spec.transition_seconds) * fps) if len(frames) > 1 else 0
    if transition > 0:
        shortest = min(frames)
        if shortest < 2 * transition:
            raise MovieAssemblySpecError(
                f"the {spec.transition_seconds:g} s transition is longer than half of the shortest item "
                f"({shortest / fps:.2f} s); shorten the transition or lengthen that item"
            )
    offsets: list[int] = []
    elapsed = 0
    for index, count in enumerate(frames[:-1]):
        elapsed += count
        if transition > 0:
            offsets.append(elapsed - (index + 1) * transition)
    total = sum(frames) - (len(frames) - 1) * transition
    return AssemblyTimeline(fps, frames, transition, tuple(offsets), total)


__all__ = [
    "ASSEMBLY_MODES",
    "AUDIO_EXTENSIONS",
    "AssemblyAudio",
    "AssemblyClip",
    "AssemblyEncode",
    "AssemblyTimeline",
    "CODEC_ALIASES",
    "CLIP_KIND_IMAGE",
    "CLIP_KIND_VIDEO",
    "MAX_DIMENSION",
    "MAX_FADE_OUT_SECONDS",
    "MAX_FPS",
    "MAX_SEQUENCE_FRAMES",
    "MAX_SLIDESHOW_CLIPS",
    "MAX_STILL_SECONDS",
    "MAX_TRANSITION_SECONDS",
    "MIN_DIMENSION",
    "MIN_FPS",
    "MIN_STILL_SECONDS",
    "MODE_SEQUENCE",
    "MODE_SLIDESHOW",
    "MOVIE_ASSEMBLY_SCHEMA",
    "MOVIE_ASSEMBLY_STAGE",
    "MovieAssemblySpec",
    "MovieAssemblySpecError",
    "SOFTWARE_VIDEO_CODECS",
    "STILL_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "frames_for",
    "kind_for_suffix",
    "plan_timeline",
]
