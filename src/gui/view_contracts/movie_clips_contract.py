"""Movie Clips tab UI normalization helpers.

PR-GUI-VIDEO-001: View contract for Movie Clips tab source selection
and clip settings display. PR-VID-ASM-332: images and videos in the
operator's order, reordering, per-still durations and assembly settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.video.movie_assembly_models import (
    AUDIO_EXTENSIONS,
    MODE_SLIDESHOW,
    STILL_EXTENSIONS,
    VIDEO_EXTENSIONS,
)

# ---------------------------------------------------------------------------
# Source mode labels
# ---------------------------------------------------------------------------

SOURCE_MODE_FOLDER = "folder"
SOURCE_MODE_MANUAL = "manual"

SOURCE_MODE_LABELS: dict[str, str] = {
    SOURCE_MODE_FOLDER: "From Run Folder",
    SOURCE_MODE_MANUAL: "Manual File List",
}

CANONICAL_SOURCE_SEQUENCE = "sequence"
CANONICAL_SOURCE_ASSEMBLED = "assembled_video"
CANONICAL_SOURCE_VIDEO_BUNDLE = "video_bundle"


def format_source_mode_label(mode: str) -> str:
    """Return the human-readable label for a source mode."""
    return SOURCE_MODE_LABELS.get(mode, mode)


def detect_canonical_source_kind(bundle: dict[str, Any] | None) -> str:
    """Return the canonical bundle kind consumed by Movie Clips."""
    if not isinstance(bundle, dict):
        return ""
    if isinstance(bundle.get("segment_provenance"), list):
        return CANONICAL_SOURCE_SEQUENCE
    if isinstance(bundle.get("export_output"), dict):
        return CANONICAL_SOURCE_ASSEMBLED
    if bundle.get("stage") == "assembled_video":
        return CANONICAL_SOURCE_ASSEMBLED
    return CANONICAL_SOURCE_VIDEO_BUNDLE


def extract_source_paths_from_bundle(bundle: dict[str, Any] | None) -> list[str]:
    """Resolve the best Movie Clips source paths from a canonical bundle.

    Preference order:
    - sequence artifact -> per-segment output clips
    - assembled result -> final export output clip(s)
    - generic video bundle -> frame paths first, then output paths, then primary
    """
    if not isinstance(bundle, dict):
        return []

    kind = detect_canonical_source_kind(bundle)
    if kind == CANONICAL_SOURCE_SEQUENCE:
        paths: list[str] = []
        for segment in bundle.get("segment_provenance") or []:
            if not isinstance(segment, dict):
                continue
            primary = segment.get("primary_output_path")
            if primary:
                paths.append(str(primary))
                continue
            output_paths = [str(item) for item in segment.get("output_paths") or [] if item]
            if output_paths:
                paths.append(output_paths[0])
        return paths

    if kind == CANONICAL_SOURCE_ASSEMBLED:
        export_output = (
            bundle.get("export_output") if isinstance(bundle.get("export_output"), dict) else bundle
        )
        artifact_bundle = (
            export_output.get("artifact_bundle") if isinstance(export_output, dict) else None
        )
        resolved = (
            artifact_bundle
            if isinstance(artifact_bundle, dict)
            else (export_output if isinstance(export_output, dict) else {})
        )
        output_paths = [str(item) for item in resolved.get("output_paths") or [] if item]
        if output_paths:
            return output_paths
        primary = resolved.get("primary_path")
        return [str(primary)] if primary else []

    frame_paths = [str(item) for item in bundle.get("frame_paths") or [] if item]
    if frame_paths:
        return frame_paths
    output_paths = [str(item) for item in bundle.get("output_paths") or [] if item]
    if output_paths:
        return output_paths
    primary = bundle.get("primary_path")
    return [str(primary)] if primary else []


def format_canonical_source_summary(bundle: dict[str, Any] | None) -> str:
    """Return a short status string for a canonical Movie Clips source bundle."""
    kind = detect_canonical_source_kind(bundle)
    count = len(extract_source_paths_from_bundle(bundle))
    if kind == CANONICAL_SOURCE_SEQUENCE:
        return f"Loaded {count} sequence segment(s)."
    if kind == CANONICAL_SOURCE_ASSEMBLED:
        return "Loaded assembled video output."
    if count == 0:
        return "No valid sources found in bundle."
    return f"Loaded {count} source item(s) from video bundle."


# ---------------------------------------------------------------------------
# Image list ordering
# ---------------------------------------------------------------------------


def sort_image_names(names: list[str]) -> list[str]:
    """Return image names in deterministic alphabetical order."""
    return sorted(names)


def format_image_list_summary(count: int) -> str:
    """Return a short summary string for the clip list count."""
    if count == 0:
        return "No items selected"
    if count == 1:
        return "1 item selected"
    return f"{count} items selected"


# ---------------------------------------------------------------------------
# Media, ordering and per-clip display (PR-VID-ASM-332)
# ---------------------------------------------------------------------------


def _patterns(extensions: frozenset[str]) -> str:
    return " ".join(f"*{suffix}" for suffix in sorted(extensions))


SOURCE_FILE_TYPES = [
    ("Images and videos", _patterns(STILL_EXTENSIONS | VIDEO_EXTENSIONS)),
    ("Images", _patterns(STILL_EXTENSIONS)),
    ("Videos", _patterns(VIDEO_EXTENSIONS)),
    ("All Files", "*.*"),
]
AUDIO_FILE_TYPES = [("Audio", _patterns(AUDIO_EXTENSIONS)), ("All Files", "*.*")]


def is_video_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_media_path(path: str | Path) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in STILL_EXTENSIONS or suffix in VIDEO_EXTENSIONS


def move_items[T](
    items: Sequence[T], selected: Sequence[int], delta: int
) -> tuple[list[T], list[int]]:
    """Move the selected entries one step (``delta`` -1 up, +1 down); return the new list and selection.

    Entries keep their relative order; an entry at the edge, or blocked by a selected entry that cannot move, stays.
    """

    result = list(items)
    chosen = sorted({index for index in selected if 0 <= index < len(result)}, reverse=delta > 0)
    blocked: set[int] = set()
    positions: list[int] = []
    for index in chosen:
        target = index + delta
        if delta == 0 or not 0 <= target < len(result) or target in blocked:
            blocked.add(index)
            positions.append(index)
            continue
        result[index], result[target] = result[target], result[index]
        positions.append(target)
    return result, sorted(positions)


def format_clip_entry(
    path: str | Path,
    *,
    mode: str,
    duration_seconds: float | None,
    default_seconds: float,
) -> str:
    """One list row: the file name, plus how long it plays in a slideshow."""

    name = Path(path).name
    if is_video_path(path):
        return f"{name}  (video)"
    if mode != MODE_SLIDESHOW:
        return name
    seconds = default_seconds if duration_seconds is None else duration_seconds
    return f"{name}  ({seconds:g} s)"


# ---------------------------------------------------------------------------
# Clip settings summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipSettingsSummary:
    fps: int
    codec: str
    quality: str
    mode: str  # "sequence" or "slideshow"

    def to_display_string(self) -> str:
        return f"{self.fps} fps  |  {self.codec}  |  {self.quality}  |  {self.mode}"


def build_clip_settings_summary(
    fps: int,
    codec: str,
    quality: str,
    mode: str,
) -> ClipSettingsSummary:
    """Build a ClipSettingsSummary from raw values."""
    return ClipSettingsSummary(
        fps=max(1, int(fps)),
        codec=str(codec).strip() or "libx264",
        quality=str(quality).strip() or "medium",
        mode=str(mode).strip() or "sequence",
    )


# ---------------------------------------------------------------------------
# Default clip settings (used by the tab on first open)
# ---------------------------------------------------------------------------

DEFAULT_FPS = 24
DEFAULT_CODEC = "libx264"
DEFAULT_QUALITY = "medium"
DEFAULT_MODE = "sequence"
RESOLUTION_MATCH_FIRST = "match_first"
DEFAULT_RESOLUTION = RESOLUTION_MATCH_FIRST
DEFAULT_STILL_SECONDS = 3.0
DEFAULT_TRANSITION_SECONDS = 0.5
DEFAULT_FADE_OUT_SECONDS = 1.0
DEFAULT_CLIP_NAME = "movie"
RESOLUTION_OPTIONS = [
    RESOLUTION_MATCH_FIRST,
    "1920x1080",
    "1280x720",
    "1080x1920",
    "720x1280",
    "1024x1024",
    "768x768",
    "512x512",
]

QUALITY_OPTIONS = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]
CODEC_OPTIONS = ["libx264", "libx265", "vp9"]
MODE_OPTIONS = ["sequence", "slideshow"]
