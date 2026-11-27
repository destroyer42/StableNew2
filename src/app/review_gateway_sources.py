"""Which Output Library items are a job's authoritative outputs, for phone publishing (PHONE-FAST).

A video job leaves working files beside its result: the frames Comfy saved, and the un-smoothed clip behind a RIFE
result. Neither is something to review. They are recognized without the job database:

* every image under the ``movie_clips`` route is a frame (that route's outputs are movies);
* an image a video manifest of its own run folder lists in ``frame_paths`` is a frame, whatever the route;
* a clip a manifest records as retained, or (for manifests written before ``retained_paths`` existed) a clip listed
  after the first of an interpolated result, is the un-smoothed source.

Only files below the Output root are read. Anything unreadable excludes nothing. Blocking file work for the sync
worker, never Tk.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.app.site_media_files import SiteOutputError, inside, open_scoped
from src.app.site_output_library import LibraryItem
from src.state.output_routing import OUTPUT_ROUTE_MOVIE_CLIPS

log = logging.getLogger(__name__)

#: Ledger states for an item that is deliberately never sent.
FRAME = "frame"
RETAINED = "retained"

_MANIFEST_LIMIT = 8 * 1024 * 1024
_CACHED_FOLDERS = 256
#: How Comfy's ``SaveImage`` names a file (``name_00001_.png``).
_NUMBERED_FRAME = re.compile(r"_\d{5}_?\.(png|jpe?g|webp)$", re.IGNORECASE)


def may_be_unrecorded_frame(item: LibraryItem) -> bool:
    """An image that could be a running video job's frame: no StableNew metadata, and named as Comfy names frames."""

    return (
        item.kind == "image"
        and item.provenance == "unknown"
        and _NUMBERED_FRAME.search(item.path) is not None
    )


def _names(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {Path(value).name.casefold() for value in values if isinstance(value, str) and value}


def _listed(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """``(frame names, retained clip names)`` one video manifest records; both empty for any other manifest."""

    if not payload.get("video_path"):
        return set(), set()
    artifact = payload.get("artifact")
    retained = _names(artifact.get("retained_paths")) if isinstance(artifact, Mapping) else set()
    videos = payload.get("video_paths")
    if payload.get("interpolation") and isinstance(videos, list):
        retained |= _names(videos[1:])
    return _names(payload.get("frame_paths")), retained


class SourceFilter:
    def __init__(self, output_root: Path) -> None:
        self._root = output_root
        #: manifests folder -> (its mtime when read, frame names, retained names)
        self._folders: dict[Path, tuple[int, frozenset[str], frozenset[str]]] = {}

    def exclusion(self, item: LibraryItem) -> str:
        """``FRAME``, ``RETAINED`` or ``""`` (publish it)."""

        parts = Path(item.path).parts
        if not parts or ".." in parts:
            return ""
        if item.kind == "image" and parts[0].casefold() == OUTPUT_ROUTE_MOVIE_CLIPS.casefold():
            return FRAME
        frames, retained = self._recorded((self._root / item.path).parent / "manifests")
        name = parts[-1].casefold()
        if item.kind == "image" and name in frames:
            return FRAME
        if item.kind == "video" and name in retained:
            return RETAINED
        return ""

    def _recorded(self, folder: Path) -> tuple[frozenset[str], frozenset[str]]:
        empty: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
        try:
            stamp = folder.stat().st_mtime_ns
            known = self._folders.get(folder)
            if known is not None and known[0] == stamp:
                return known[1], known[2]
            inside(self._root, folder)
            files = list(folder.glob("*.json"))
        except (OSError, SiteOutputError):
            return empty
        frames: set[str] = set()
        retained: set[str] = set()
        for path in files:
            try:
                with open_scoped(self._root, path) as stream:
                    raw = stream.read(_MANIFEST_LIMIT + 1)
                payload = json.loads(raw) if len(raw) <= _MANIFEST_LIMIT else None
            except (OSError, SiteOutputError, ValueError, RecursionError):
                log.debug("Review gateway publish could not read a run manifest")
                continue
            if isinstance(payload, Mapping):
                found, kept = _listed(payload)
                frames |= found
                retained |= kept
        if len(self._folders) >= _CACHED_FOLDERS:
            self._folders.pop(next(iter(self._folders)))
        self._folders[folder] = (stamp, frozenset(frames), frozenset(retained))
        return frozenset(frames), frozenset(retained)
