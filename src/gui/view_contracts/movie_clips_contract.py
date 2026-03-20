"""Movie Clips tab UI normalization helpers.

PR-GUI-VIDEO-001: View contract for Movie Clips tab source selection
and clip settings display.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
        export_output = bundle.get("export_output") if isinstance(bundle.get("export_output"), dict) else bundle
        artifact_bundle = export_output.get("artifact_bundle") if isinstance(export_output, dict) else None
        resolved = artifact_bundle if isinstance(artifact_bundle, dict) else (
            export_output if isinstance(export_output, dict) else {}
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
    """Return a short summary string for the image list count."""
    if count == 0:
        return "No images selected"
    if count == 1:
        return "1 image selected"
    return f"{count} images selected"


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

QUALITY_OPTIONS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
CODEC_OPTIONS = ["libx264", "libx265", "vp9"]
MODE_OPTIONS = ["sequence", "slideshow"]
