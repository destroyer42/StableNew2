"""A point-in-time, read-only view of the catalog for the browser (PR-VID-MOTION-LIB-353).

Building a snapshot costs one ``stat`` per asset (presence, size, timestamp) and never hashes, decodes or
spawns a process, so the browser can refresh it freely.  It is plain data: the GUI filters and sorts it
locally while the operator types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from src.video.motion_library.models import MotionAsset
from src.video.motion_library.store import LibraryError, MotionLibraryStore
from src.video.motion_library.verification import FILE_UNREADABLE, FileCheck, quick_check


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    configured: bool
    root: str = ""
    suggested_root: str = ""
    assets: tuple[MotionAsset, ...] = ()
    checks: Mapping[str, FileCheck] = field(default_factory=dict)
    thumbnails: Mapping[str, str] = field(default_factory=dict)
    #: The safely resolved file of each asset the in-app preview may play.
    media_paths: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    revision: int = 0
    #: A refusal to open the library at all (corrupt or newer manifest, unusable folder).
    error: str = ""


def build_snapshot(store: MotionLibraryStore) -> LibrarySnapshot:
    assets = store.assets()
    checks: dict[str, FileCheck] = {}
    thumbnails: dict[str, str] = {}
    media_paths: dict[str, str] = {}
    for asset in assets:
        try:
            path = store.asset_path(asset)
            media_paths[asset.asset_id] = str(path)
            checks[asset.asset_id] = quick_check(asset, path)
        except LibraryError as exc:
            checks[asset.asset_id] = FileCheck(FILE_UNREADABLE, str(exc))
        thumb = store.thumbnail_path(asset)
        if thumb is not None and thumb.is_file():
            thumbnails[asset.asset_id] = str(thumb)
    issues = list(store.report.issues)
    if store.report.orphan_files:
        issues.append(
            f"{len(store.report.orphan_files)} copied file(s) in the library folder have no catalog record "
            "and were left untouched."
        )
    return LibrarySnapshot(
        configured=True,
        root=str(store.root),
        assets=assets,
        checks=checks,
        thumbnails=thumbnails,
        media_paths=media_paths,
        issues=tuple(issues),
        revision=store.revision,
    )


__all__ = ["LibrarySnapshot", "build_snapshot"]
