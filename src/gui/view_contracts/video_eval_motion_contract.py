"""Toolkit-neutral helpers for authoring a case's driving-motion reference in the eval editor (PR-VID-MOTION-410).

The Tk mixin (``src/gui/views/video_eval_editor_motion.py``) only renders. What each field is, how a bound clip or library
asset is merged into a case, and how the Motion Library is opened live here, so they can be tested without a display.
Binding touches no job and queues nothing; the library is only read.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from src.video.motion_library.config import load_library_root
from src.video.video_eval_motion import (
    FPS_CONVERSIONS,
    MOTION_CATEGORIES,
    PREP_AS_IS,
    PREP_WORKFLOW,
    PREPARATION_MODES,
    as_mapping,
    as_mapping_or_none,
)

CATEGORY_LABELS = tuple(label for _key, label in MOTION_CATEGORIES)
_CATEGORY_BY_LABEL = {label: key for key, label in MOTION_CATEGORIES}
_LABEL_BY_CATEGORY = dict(MOTION_CATEGORIES)
PREPARATION_LABELS = {
    PREP_AS_IS: "Use the driving video as it is (unprepared)",
    PREP_WORKFLOW: "Prepare for each workflow, version and length (Prepare Motion Source)",
}
LIBRARY_LIST_LIMIT = 300
#: ``(key, label, kind)`` for the text fields of the motion block, in display order. ``kind`` is ``line`` or ``text``.
TEXT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("action", "Intended action", "text"),
    ("motion_prompt", "Motion prompt", "text"),
    ("expected_outcome", "Expected observable outcome", "text"),
    ("direction", "Expected direction (optional)", "line"),
)
ANNOTATION_FIELDS: tuple[tuple[str, str], ...] = (
    ("framing", "Framing"),
    ("viewpoint", "Viewpoint"),
    ("source_compatibility", "Source compatibility category"),
)


def category_label(key: Any) -> str:
    return _LABEL_BY_CATEGORY.get(str(key or ""), "")


def category_key(label: str) -> str:
    return _CATEGORY_BY_LABEL.get(label, "")


def preparation_choice_labels() -> tuple[str, ...]:
    return tuple(PREPARATION_LABELS[mode] for mode in PREPARATION_MODES)


def preparation_mode_for(label: str) -> str:
    return next((mode for mode, text in PREPARATION_LABELS.items() if text == label), PREP_AS_IS)


def whole_or_none(text: str) -> int | str | None:
    """A frame number from a text box: a whole number, ``None`` when blank, the raw text when invalid (validation reports it)."""

    value = text.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def provenance_line(motion: Mapping[str, Any]) -> str:
    driving = as_mapping(motion.get("driving"))
    library = as_mapping_or_none(driving.get("library_asset"))
    if not driving.get("path"):
        return "No driving reference bound yet."
    if library:
        origin = as_mapping_or_none(library.get("derived_from"))
        harvested = (
            f"; harvested from original {str(origin.get('original_sha256'))[:12]}... frames "
            f"{origin.get('start_frame')}-{origin.get('end_frame')}"
            if origin
            else ""
        )
        return f"Motion Library asset {library.get('asset_id')} (bytes verified at binding{harvested})."
    return "Local video. Its provenance is not verified; it is not treated as a library asset or a generated clip."


def summary_lines(motion: Mapping[str, Any]) -> list[str]:
    driving = as_mapping(motion.get("driving"))
    lines = [provenance_line(motion)]
    if driving.get("path"):
        lines.append(f"Driving video: {driving['path']}")
    if driving.get("sha256"):
        lines.append(f"SHA-256: {driving['sha256']}")
    return lines


def merge_bound(motion: MutableMapping[str, Any], bound: Mapping[str, Any]) -> None:
    """Apply a bound clip or library suggestion to a motion block.

    The driving file and its identity are replaced (that is what binding means). Everything else the library supplies is a
    *suggestion*: it fills only fields the operator has left blank and never overwrites what they typed."""

    motion["driving"] = dict(bound["driving"])
    annotations = motion.setdefault("annotations", {})
    if isinstance(annotations, dict):
        for key, value in (bound.get("annotations") or {}).items():
            if not str(annotations.get(key) or "").strip():
                annotations[key] = value
    for key in ("direction", "action"):
        if bound.get(key) and not str(motion.get(key) or "").strip():
            motion[key] = bound[key]


@dataclass(frozen=True)
class LibraryChoice:
    asset_id: str
    label: str


def library_choices(store: Any, query: str = "") -> tuple[LibraryChoice, ...]:
    """Cataloged clips for a picker, newest import first, optionally filtered by name, tag or id. Bounded."""

    needle = query.strip().casefold()
    rows: list[LibraryChoice] = []
    for asset in sorted(store.assets(), key=lambda a: getattr(a, "imported_at", ""), reverse=True):
        haystack = " ".join(
            [
                asset.display_name,
                asset.asset_id,
                " ".join(getattr(asset, "tags", ())),
                getattr(asset, "motion_label", ""),
            ]
        ).casefold()
        if needle and needle not in haystack:
            continue
        harvested = " (harvested)" if getattr(asset, "harvest", None) is not None else ""
        rows.append(
            LibraryChoice(asset.asset_id, f"{asset.display_name}{harvested} · {asset.asset_id}")
        )
        if len(rows) >= LIBRARY_LIST_LIMIT:
            break
    return tuple(rows)


def open_library_store(
    *,
    root: Callable[[], str] = load_library_root,
    factory: Callable[[str], Any] | None = None,
) -> tuple[Any | None, str]:
    """``(store, message)``: the configured Motion Library opened read-only in effect, or ``None`` with the reason."""

    configured = root()
    if not configured:
        return (
            None,
            "No Motion Library is configured. Set one up in Video Workflow > Motion Library first.",
        )
    try:
        if factory is None:
            from src.video.motion_library.store import MotionLibraryStore

            factory = MotionLibraryStore
        return factory(configured), ""
    except (OSError, ValueError) as exc:
        return None, f"The Motion Library could not be opened: {exc}"


__all__ = [
    "ANNOTATION_FIELDS",
    "CATEGORY_LABELS",
    "FPS_CONVERSIONS",
    "LIBRARY_LIST_LIMIT",
    "PREPARATION_LABELS",
    "TEXT_FIELDS",
    "LibraryChoice",
    "category_key",
    "category_label",
    "library_choices",
    "merge_bound",
    "open_library_store",
    "preparation_choice_labels",
    "preparation_mode_for",
    "provenance_line",
    "summary_lines",
    "whole_or_none",
]
