"""Which Output Library items are a job's authoritative outputs, for phone publishing (PHONE-FAST).

Only a job's final outputs are published, so this names where they are and everything else is left out: a file in an
output route's run folder (``<route>/<run>/<file>``, or one of its stage folders) or a Photo Optimize result
(``PhotoOptimize/workspace/assets/<asset>/outputs/<file>``). A new folder under the Output root is not published until
it is recognized here. Two kinds are left out:

* ``WORKING``: a file StableNew keeps to work with (prepared or imported inputs, temporary and conditioning files).
  Withdrawn from the phone if it was sent before.
* ``NOT_OUTPUT``: any other folder, such as one the owner made. Not sent; what is already on the phone stays.

A video job also leaves working files beside its result: the frames Comfy saved, and the un-smoothed clip behind a RIFE
result. Neither is something to review. They are recognized without the job database:

* every image under the ``movie_clips`` route is a frame (that route's outputs are movies);
* an image a video manifest of its own run folder lists in ``frame_paths``, or names as the clip's poster
  (``thumbnail_path``), is a frame, whatever the route;
* a clip a manifest records as retained, or (for manifests written before ``retained_paths`` existed) a clip listed
  after the first of an interpolated result, is the un-smoothed source.

Eval outputs are not published either (RG-170): they are rated blind in the phone's "To rate" tab, and the Review inbox
would show their model and workflow. They are anything under the ``video_eval`` run folders, and any output whose run
manifest names a job that an eval's ``run.json`` lists.

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

from src.app.review_gateway_protocol import RUN_ID
from src.app.site_media_files import SiteOutputError, inside, open_scoped
from src.app.site_output_library import LibraryItem
from src.state.output_routing import (
    KNOWN_OUTPUT_ROUTE_DIRS,
    OUTPUT_ROUTE_MOVIE_CLIPS,
    OUTPUT_ROUTE_PHOTO_OPTIMIZE,
)
from src.video.video_eval_run import EVAL_OUTPUT_FOLDER, RUN_MANIFEST_NAME

log = logging.getLogger(__name__)

#: Ledger states for an item that is deliberately never sent.
FRAME = "frame"
RETAINED = "retained"
EVAL = "eval_output"
WORKING = "working_file"
NOT_OUTPUT = "not_output"

#: Folders under the Output root that StableNew fills with inputs and intermediates. Literals, so the sync worker does
#: not import the video modules that write them; a test checks them against those modules' own names.
_WORKING_FOLDERS = frozenset(
    {
        "prepared_video_sources",
        "prepared_driving_videos",
        "eval_plans",
        "storyboards",
        "continue_frames",
    }
)
_ROUTES = frozenset(route.casefold() for route in KNOWN_OUTPUT_ROUTE_DIRS)
#: The folders inside a run folder that hold final outputs (the upscale stage writes to ``upscaled``).
_STAGE_FOLDERS = frozenset({"txt2img", "img2img", "adetailer", "upscaled", "video"})

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


def _placement(parts: tuple[str, ...]) -> str:
    """``""`` where a job writes its final outputs, else ``WORKING`` or ``NOT_OUTPUT``."""

    names = [part.casefold() for part in parts]
    if names[0] in _WORKING_FOLDERS:
        return WORKING
    if len(names) > 1 and RUN_ID.fullmatch(parts[0]):
        names.insert(0, "")  # a run folder from before the output routes, directly under the root
    elif names[0] not in _ROUTES or len(names) < 2:
        return NOT_OUTPUT
    if names[0] == OUTPUT_ROUTE_PHOTO_OPTIMIZE.casefold() and names[1] == "workspace":
        result = len(names) == 6 and names[2] == "assets" and names[4] == "outputs"
        return "" if result else WORKING
    # ``<route>/<run>/<file>`` or a stage folder below the run: any other folder there is temporary, conditioning or
    # intermediate work.
    return "" if len(names) <= 3 or (len(names) == 4 and names[2] in _STAGE_FOLDERS) else WORKING


def _listed(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """``(frame and poster names, retained clip names)`` one video manifest records; both empty for any other."""

    if not payload.get("video_path"):
        return set(), set()
    artifact = payload.get("artifact")
    retained = _names(artifact.get("retained_paths")) if isinstance(artifact, Mapping) else set()
    videos = payload.get("video_paths")
    if payload.get("interpolation") and isinstance(videos, list):
        retained |= _names(videos[1:])
    posters = [payload.get("thumbnail_path")]
    if isinstance(artifact, Mapping):
        posters.append(artifact.get("thumbnail_path"))
    return _names(payload.get("frame_paths")) | _names(posters), retained


def _job_ids(value: Any, depth: int = 0) -> set[str]:
    """Every ``job_id`` recorded anywhere in a manifest: video manifests keep it under their compiled workflow."""

    found: set[str] = set()
    if depth < 6 and isinstance(value, Mapping):
        for key, inner in value.items():
            if key == "job_id" and isinstance(inner, str) and inner:
                found.add(inner)
            else:
                found |= _job_ids(inner, depth + 1)
    return found


def _output_names(payload: Mapping[str, Any]) -> set[str]:
    artifact = payload.get("artifact")
    artifact = artifact if isinstance(artifact, Mapping) else {}
    names = _names([payload.get("video_path"), payload.get("path"), artifact.get("primary_path")])
    for listed in (
        payload.get("video_paths"),
        payload.get("output_paths"),
        payload.get("gif_paths"),
        artifact.get("output_paths"),
    ):
        names |= _names(listed)
    return names


class SourceFilter:
    def __init__(self, output_root: Path) -> None:
        self._root = output_root
        #: manifests folder -> (its mtime when read, frame names, retained names, output name -> job ids)
        self._folders: dict[
            Path, tuple[int, frozenset[str], frozenset[str], dict[str, set[str]]]
        ] = {}
        #: The eval run files seen (folder, mtime) and the job ids they list.
        self._eval_seen: tuple[tuple[str, int], ...] = ()
        self._eval_ids: frozenset[str] = frozenset()

    def is_eval_output(self, relative: str) -> bool:
        """Whether the file at this Output-relative path belongs to a video eval."""

        parts = Path(relative).parts
        if not parts or ".." in parts:
            return False
        if parts[0].casefold() == EVAL_OUTPUT_FOLDER:
            return True
        jobs = self._recorded((self._root / relative).parent / "manifests")[2]
        recorded = jobs.get(parts[-1].casefold())
        if not recorded:
            return False
        return not recorded.isdisjoint(self._eval_job_ids())

    def exclusion(self, item: LibraryItem) -> str:
        """``EVAL``, ``FRAME``, ``RETAINED``, ``WORKING``, ``NOT_OUTPUT`` or ``""`` (publish it)."""

        return self.exclusion_of(item.path, item.kind)

    def exclusion_of(self, rel_path: str, kind: str) -> str:
        """``exclusion`` for a path below the Output root; it still answers for a file that is gone."""

        parts = Path(rel_path).parts
        if not parts or ".." in parts:
            return ""
        if self.is_eval_output(rel_path):
            return EVAL
        if kind == "image" and parts[0].casefold() == OUTPUT_ROUTE_MOVIE_CLIPS.casefold():
            return FRAME
        frames, retained, _jobs = self._recorded((self._root / rel_path).parent / "manifests")
        name = parts[-1].casefold()
        if kind == "image" and name in frames:
            return FRAME
        if kind == "video" and name in retained:
            return RETAINED
        # Last, so a frame or un-smoothed clip is recognized as one wherever its run folder is.
        return _placement(parts)

    def _read_json(self, path: Path) -> Mapping[str, Any] | None:
        try:
            with open_scoped(self._root, path) as stream:
                raw = stream.read(_MANIFEST_LIMIT + 1)
            payload = json.loads(raw) if len(raw) <= _MANIFEST_LIMIT else None
        except (OSError, SiteOutputError, ValueError, RecursionError):
            log.debug("Review gateway publish could not read a run manifest")
            return None
        return payload if isinstance(payload, Mapping) else None

    def _eval_job_ids(self) -> frozenset[str]:
        try:
            runs = sorted((self._root / EVAL_OUTPUT_FOLDER).glob(f"*/{RUN_MANIFEST_NAME}"))
            seen = tuple((path.parent.name, path.stat().st_mtime_ns) for path in runs)
        except OSError:
            return self._eval_ids
        if seen == self._eval_seen:
            return self._eval_ids
        found: set[str] = set()
        for path in runs:
            jobs = (self._read_json(path) or {}).get("jobs")
            if isinstance(jobs, list):
                found.update(
                    job["job_id"]
                    for job in jobs
                    if isinstance(job, Mapping) and isinstance(job.get("job_id"), str)
                )
        self._eval_seen, self._eval_ids = seen, frozenset(found)
        return self._eval_ids

    def _recorded(self, folder: Path) -> tuple[frozenset[str], frozenset[str], dict[str, set[str]]]:
        empty: tuple[frozenset[str], frozenset[str], dict[str, set[str]]] = (
            frozenset(),
            frozenset(),
            {},
        )
        try:
            stamp = folder.stat().st_mtime_ns
            known = self._folders.get(folder)
            if known is not None and known[0] == stamp:
                return known[1], known[2], known[3]
            inside(self._root, folder)
            files = list(folder.glob("*.json"))
        except (OSError, SiteOutputError):
            return empty
        frames: set[str] = set()
        retained: set[str] = set()
        jobs: dict[str, set[str]] = {}
        for path in files:
            payload = self._read_json(path)
            if payload is not None:
                found, kept = _listed(payload)
                frames |= found
                retained |= kept
                job_ids = _job_ids(payload)
                if job_ids:
                    for output in _output_names(payload):
                        jobs.setdefault(output, set()).update(job_ids)
        if len(self._folders) >= _CACHED_FOLDERS:
            self._folders.pop(next(iter(self._folders)))
        self._folders[folder] = (stamp, frozenset(frames), frozenset(retained), jobs)
        return frozenset(frames), frozenset(retained), jobs
