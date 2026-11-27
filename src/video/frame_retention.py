"""Remove a clip's retained PNG frames a day after the clip exists (VID-FRAME, owner decision 2026-11-27).

Only frames a backend manifest lists under ``frames_out``, lying in that run's own folder, are candidates, and only
once the clip they were encoded into exists, is not empty and is more than a day old. Never removed: anything the job
records as an output, the first frame (the thumbnail), the last frame (the exact hand-off), any frame a cut manifest
names, and anything in a sequence run, an evaluation or the archive. When a cut manifest or a Storyboard file cannot
be read, nothing at all is removed: what it protects is unknown. Deletion cannot be undone.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from src.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

MARKER_NAME: Final = "frames_removed.json"
MIN_AGE_SECONDS: Final = 86_400
_CUT_SCHEMA: Final = "stablenew.storyboard_cut.v1"
_CUT_FILE_NAMES: Final = frozenset({"root_cut.json", "storyboard_cut.json"})
_SEQUENCE_LEDGER: Final = "sequence_state.json"
_SKIPPED_FOLDERS: Final = frozenset({"video_eval", "_archive", ".stablenew-library"})


@dataclass(frozen=True)
class FrameSweep:
    frames: int = 0
    bytes: int = 0
    runs: int = 0
    refused: str = ""  # why nothing was removed


class _Unknown(RuntimeError):
    """What a record protects cannot be established."""


def frames_were_removed(run_dir: str | Path) -> bool:
    return (Path(run_dir) / MARKER_NAME).is_file()


def _key(path: str | Path) -> tuple[str, str]:
    """Folder name and file name: records may hold relative paths, and matching too much only keeps more."""

    text = Path(str(path).replace("\\", "/"))
    return text.parent.name.casefold(), text.name.casefold()


def _read(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Unknown(f"{path} cannot be read: {exc}") from exc
    if not isinstance(data, Mapping):
        raise _Unknown(f"{path} is not a JSON object")
    return data


def _walk(root: Path) -> Iterator[tuple[Path, list[str]]]:
    for folder, names, files in os.walk(root, followlinks=False):
        names[:] = [
            name
            for name in names
            if name.casefold() not in _SKIPPED_FOLDERS and not os.path.islink(Path(folder) / name)
        ]
        yield Path(folder), files


def _cut_frames(path: Path) -> set[tuple[str, str]]:
    data = _read(path)
    frames = data.get("frames")
    if data.get("schema") != _CUT_SCHEMA or not isinstance(frames, list):
        raise _Unknown(f"{path} is not a cut manifest this version understands")
    return {_key(item["path"]) for item in frames if isinstance(item, Mapping) and item.get("path")}


def _tree_references(tree_root: Path) -> tuple[set[Path], set[tuple[str, str]]]:
    """The cut manifests and start images Storyboard files name (a root may live under another output folder)."""

    manifests: set[Path] = set()
    images: set[tuple[str, str]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key == "manifest_path" and isinstance(item, str) and item:
                    if Path(item).is_file():
                        manifests.add(Path(item))
                elif key == "image_path" and isinstance(item, str) and item:
                    images.add(_key(item))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for tree in sorted(tree_root.glob("*.json")) if tree_root.is_dir() else ():
        visit(_read(tree))
    return manifests, images


def _protected(root: Path, tree_root: Path) -> set[tuple[str, str]]:
    manifests, protected = _tree_references(tree_root)
    for folder, files in _walk(root):
        lead_ins = folder.name == "leadins"
        manifests.update(
            folder / name
            for name in files
            if name in _CUT_FILE_NAMES or (lead_ins and name.endswith(".json"))
        )
    for manifest in manifests:
        protected |= _cut_frames(manifest)
    return protected


def _recorded_outputs(record: Mapping[str, Any]) -> set[tuple[str, str]]:
    paths: list[Any] = []
    for block in (record, record.get("artifact")):
        if not isinstance(block, Mapping):
            continue
        for key in ("output_paths", "video_paths", "gif_paths", "retained_paths"):
            paths.extend(block.get(key) or ())
        paths.append(block.get("primary_path"))
    return {_key(path) for path in paths if path}


def _candidates(run: Path, record: Mapping[str, Any], cutoff: float) -> list[Path]:
    frames_out = record.get("frames_out")
    if not isinstance(frames_out, Mapping):
        return []
    listed = [str(item) for item in frames_out.get("frame_paths") or () if item]
    clip_text = str(frames_out.get("video_path") or "")
    if len(listed) < 3 or not clip_text:
        return []
    clip = run / _key(clip_text)[1]
    try:
        info = clip.stat()
    except OSError:
        return []
    if info.st_size <= 0 or info.st_mtime > cutoff:
        return []
    keep = _recorded_outputs(record) | {_key(listed[0]), _key(listed[-1])}
    found = []
    for text in listed[1:-1]:
        folder, name = _key(text)
        frame = run / name
        if folder != run.name.casefold() or not name.endswith(".png") or _key(text) in keep:
            continue
        if frame.is_file() and not frame.is_symlink():
            found.append(frame)
    return found


def sweep_retained_frames(
    output_root: str | Path,
    *,
    tree_root: str | Path,
    now: float | None = None,
    min_age_seconds: float = MIN_AGE_SECONDS,
    should_stop: Callable[[], bool] = lambda: False,
) -> FrameSweep:
    """One pass over ``output_root``; ``should_stop`` is asked before each run folder."""

    root = Path(output_root).expanduser().resolve()
    if not root.is_dir():
        return FrameSweep()
    try:
        protected = _protected(root, Path(tree_root))
    except _Unknown as exc:
        logger.warning("No video frames were removed: %s", exc)
        return FrameSweep(refused=str(exc))
    cutoff = (time.time() if now is None else now) - min_age_seconds
    removed = size = runs = 0
    for folder, files in _walk(root):
        if folder.name != "manifests":
            continue
        run = folder.parent
        if (run / _SEQUENCE_LEDGER).exists():
            continue
        if should_stop():
            break
        doomed: dict[str, int] = {}
        for name in files:
            if not name.endswith(".json"):
                continue
            try:
                record = _read(folder / name)
            except _Unknown:
                continue  # an unreadable backend manifest lists nothing, so nothing of it is removed
            for frame in _candidates(run, record, cutoff):
                if _key(frame) not in protected:
                    doomed[frame.name] = frame.stat().st_size
        if not doomed:
            continue
        try:
            # Written first: a reader that finds a frame gone must be able to tell why.
            atomic_write_json(
                run / MARKER_NAME,
                {"removed_at": time.time(), "frames": sorted(doomed)},
                indent=1,
            )
        except OSError as exc:
            logger.warning("Frames of %s were kept: the removal record failed: %s", run, exc)
            continue
        runs += 1
        for name, bytes_ in doomed.items():
            try:
                (run / name).unlink()
            except OSError as exc:
                logger.warning("Could not remove %s: %s", run / name, exc)
                continue
            removed += 1
            size += bytes_
    if removed:
        logger.info(
            "Removed %d video frame PNGs (%.1f GB) from %d clip folders; clips were kept.",
            removed,
            size / 1e9,
            runs,
        )
    return FrameSweep(frames=removed, bytes=size, runs=runs)


__all__ = [
    "MARKER_NAME",
    "MIN_AGE_SECONDS",
    "FrameSweep",
    "frames_were_removed",
    "sweep_retained_frames",
]
