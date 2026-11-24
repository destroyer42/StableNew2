"""Tk-free state of the Storyboard clip picker and of the media-visibility preferences (PR-VID-STORY-IMPORT).

Nothing here imports ``tkinter`` or touches media. The picker dialog renders :class:`ImportActions`; the tab renders and
persists :class:`MediaPrefs`. The visibility flags are presentation preferences only: they live in the application's UI
state file (``UIStateStore``) next to window geometry and never in a Storyboard file or a job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Protocol

from src.video.storyboard_import import ClipImportPlan, default_clip_folder

logger = logging.getLogger(__name__)

UI_STATE_KEY: Final = "storyboard_media"
MP4_PATTERNS: Final = ("*.mp4", "*.MP4")
IMAGE_PATTERNS: Final = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.tif", "*.tiff")


def clip_dialog_options(output_root: str | None) -> dict[str, Any]:
    """Arguments of the native file browser for a video clip: opens in ``movie_clips``, MP4 only (any case)."""

    return {
        "title": "Choose the MP4 clip to continue",
        "initialdir": default_clip_folder(output_root),
        "filetypes": [("MP4 video", MP4_PATTERNS), ("All files", "*.*")],
    }


def image_dialog_options(output_root: str | None) -> dict[str, Any]:
    return {
        "title": "Choose the still image",
        "initialdir": default_clip_folder(output_root),
        "filetypes": [("Images", IMAGE_PATTERNS), ("All files", "*.*")],
    }


# ----------------------------------------------------------------------------------------- the picker's buttons


@dataclass(frozen=True, slots=True)
class ImportActions:
    can_create: bool
    #: Why Create is unavailable (empty when it is available).
    hint: str
    show_conversion: bool
    show_media_choice: bool


def import_actions(
    plan: ClipImportPlan | None,
    *,
    conversion_accepted: bool,
    media_chosen: bool,
    known_refused: bool = False,
) -> ImportActions:
    """What the picker offers for the inspected clip. ``known_refused``: the clip's own job was tried and refused."""

    if plan is None:
        return ImportActions(False, "Choose a video clip first.", False, False)
    choice = plan.route == "choose" or known_refused
    if plan.route == "job" and not media_chosen and not known_refused:
        return ImportActions(True, "", False, True)
    compat = plan.compatibility
    if choice and not media_chosen:
        return ImportActions(False, "Import the encoded MP4 as media to continue.", False, True)
    if compat is None:
        return ImportActions(False, "Choose the workflow for the new takes.", False, choice)
    if compat.blockers:
        return ImportActions(False, " ".join(compat.blockers), False, choice)
    if compat.needs_conversion and not conversion_accepted:
        return ImportActions(False, "Tick “Apply this conversion” to continue.", True, choice)
    return ImportActions(True, "", compat.needs_conversion, choice)


# ----------------------------------------------------------------------------------------- media visibility


@dataclass(frozen=True, slots=True)
class MediaPrefs:
    """Whether the Storyboard tab shows take thumbnails and the frame viewer. Both default to visible."""

    thumbnails: bool = True
    viewer: bool = True

    def to_state(self) -> dict[str, bool]:
        return {"thumbnails": self.thumbnails, "viewer": self.viewer}

    @classmethod
    def from_state(cls, value: Any) -> MediaPrefs:
        """A missing, malformed or partial record falls back to visible for each flag (never raises)."""

        if not isinstance(value, dict):
            return cls()
        return cls(
            thumbnails=value["thumbnails"] if isinstance(value.get("thumbnails"), bool) else True,
            viewer=value["viewer"] if isinstance(value.get("viewer"), bool) else True,
        )


class _StateStore(Protocol):
    def load_state(self, *, strict: bool = False) -> dict[str, Any] | None: ...

    def update_state(self, changes: dict[str, Any]) -> bool: ...


def load_media_prefs(store: _StateStore | None) -> MediaPrefs:
    if store is None:
        return MediaPrefs()
    try:
        state = store.load_state() or {}
    except Exception:  # noqa: BLE001 - a preference must never stop the tab from opening
        logger.warning("storyboard: the media preferences could not be read", exc_info=True)
        return MediaPrefs()
    return MediaPrefs.from_state(state.get(UI_STATE_KEY))


def save_media_prefs(store: _StateStore | None, prefs: MediaPrefs) -> bool:
    """Persist the flags; ``False`` (and a log line) when they could not be written. Never raises."""

    if store is None:
        return False
    try:
        return bool(store.update_state({UI_STATE_KEY: prefs.to_state()}))
    except Exception:  # noqa: BLE001 - presentation only: the toggle still works for this session
        logger.warning("storyboard: the media preferences could not be saved", exc_info=True)
        return False


__all__ = [
    "IMAGE_PATTERNS",
    "MP4_PATTERNS",
    "UI_STATE_KEY",
    "ImportActions",
    "MediaPrefs",
    "clip_dialog_options",
    "image_dialog_options",
    "import_actions",
    "load_media_prefs",
    "save_media_prefs",
]
