"""Movie Clips tab UI normalization helpers.

PR-GUI-VIDEO-001: View contract for Movie Clips tab source selection
and clip settings display.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Source mode labels
# ---------------------------------------------------------------------------

SOURCE_MODE_FOLDER = "folder"
SOURCE_MODE_MANUAL = "manual"

SOURCE_MODE_LABELS: dict[str, str] = {
    SOURCE_MODE_FOLDER: "From Run Folder",
    SOURCE_MODE_MANUAL: "Manual File List",
}


def format_source_mode_label(mode: str) -> str:
    """Return the human-readable label for a source mode."""
    return SOURCE_MODE_LABELS.get(mode, mode)


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
