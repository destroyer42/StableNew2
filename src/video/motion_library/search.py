"""Local search over the catalog (PR-VID-MOTION-LIB-353).

Pure functions over in-memory records: filtering never opens a video, spawns a process or touches the
disk, so it stays responsive however many clips are catalogued.  An empty field in the query means
"any".  An unannotated attribute never matches a filter that asks for a specific value.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.video.motion_library.models import (
    LOOP_LOOPABLE,
    LOOP_ONE_SHOT,
    MotionAsset,
    normalize_tag,
)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str = ""
    tags: tuple[str, ...] = ()
    source_categories: tuple[str, ...] = ()
    subject_kind: str = ""
    subject_count: int | None = None
    framing: str = ""
    viewpoint: str = ""
    camera_movement: str = ""
    motion_intensity: str = ""
    #: ``loopable`` or ``one_shot``; empty means either.
    loop: str = ""
    #: ``reviewed``, ``unreviewed`` or ``rejected``; empty means any.
    review: str = ""
    min_seconds: float | None = None
    max_seconds: float | None = None
    min_frames: int | None = None
    max_frames: int | None = None
    good_for_motion_only: bool = False

    @property
    def is_empty(self) -> bool:
        return self == SearchQuery()


def _haystack(asset: MotionAsset) -> str:
    parts = [
        asset.display_name,
        " ".join(asset.tags),
        asset.source_reference,
        asset.motion_direction,
        asset.start_pose,
        asset.end_pose,
        asset.quality_notes,
        asset.provenance_notes,
        asset.origin.motion_label if asset.origin is not None else "",
    ]
    return " ".join(parts).lower()


def matches(asset: MotionAsset, query: SearchQuery) -> bool:
    terms = query.text.lower().split()
    if terms:
        haystack = _haystack(asset)
        if not all(term in haystack for term in terms):
            return False
    for tag in query.tags:
        wanted = normalize_tag(tag)
        if wanted and wanted not in asset.tags:
            return False
    if query.source_categories and asset.source_category not in query.source_categories:
        return False
    for wanted, actual in (
        (query.subject_kind, asset.subject_kind),
        (query.framing, asset.framing),
        (query.viewpoint, asset.viewpoint),
        (query.camera_movement, asset.camera_movement),
        (query.motion_intensity, asset.motion_intensity),
    ):
        if wanted and actual != wanted:
            return False
    if query.subject_count is not None and asset.subject_count != query.subject_count:
        return False
    if query.loop:
        if query.loop not in {LOOP_LOOPABLE, LOOP_ONE_SHOT} or asset.loop_suitability != query.loop:
            return False
    if query.review and asset.review_status != query.review:
        return False
    if query.good_for_motion_only and asset.good_for_motion is not True:
        return False
    if query.min_seconds is not None or query.max_seconds is not None:
        if asset.duration_seconds is None:
            return False
        if query.min_seconds is not None and asset.duration_seconds < query.min_seconds:
            return False
        if query.max_seconds is not None and asset.duration_seconds > query.max_seconds:
            return False
    if query.min_frames is not None or query.max_frames is not None:
        if asset.frame_count is None:
            return False
        if query.min_frames is not None and asset.frame_count < query.min_frames:
            return False
        if query.max_frames is not None and asset.frame_count > query.max_frames:
            return False
    return True


def search_assets(assets: Iterable[MotionAsset], query: SearchQuery) -> list[MotionAsset]:
    """Matching assets ordered by name (case-insensitive), then import time."""

    found = [asset for asset in assets if matches(asset, query)]
    found.sort(key=lambda a: (a.display_name.lower(), a.imported_at, a.asset_id))
    return found


def known_tags(assets: Iterable[MotionAsset]) -> tuple[str, ...]:
    """Every tag in use, sorted, for a filter picker."""

    return tuple(sorted({tag for asset in assets for tag in asset.tags}))


__all__ = ["SearchQuery", "known_tags", "matches", "search_assets"]
