"""Move a clip's retained PNG frames to the Recycle Bin 7 days after the clip exists.

VID-FRAME (owner decision 2026-11-27), changed by KEEP-SPACE (owner decision 2026-11-28: 7 days, Recycle Bin).

Only frames a backend manifest lists under ``frames_out``, lying in that run's own folder, are candidates, and only
once the clip they were encoded into exists, is not empty and is more than 7 days old. Never removed: anything the job
records as an output, the first frame (the thumbnail), the last frame (the exact hand-off), any frame a cut manifest
names, and anything in a sequence run, an evaluation or the archive. When a cut manifest or a Storyboard file cannot
be read, nothing at all is removed: what it protects is unknown.

Nothing is deleted here. Frames go to the Recycle Bin, and only when everything a pass found fits in its free room:
Windows would otherwise delete files permanently (``src/utils/recycle_bin.py``). Disk space is freed when the bin is
emptied.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from src.utils.atomic_io import atomic_write_json
from src.utils.recycle_bin import MAX_SHELL_PATH, BinRoom, RecycleBin, RecycleBinRefused

logger = logging.getLogger(__name__)

MARKER_NAME: Final = "frames_removed.json"
MIN_AGE_SECONDS: Final = 7 * 86_400
_BIN_OVERHEAD_BYTES: Final = 4096  # per file: cluster rounding and the bin's own index entry
_CUT_SCHEMA: Final = "stablenew.storyboard_cut.v1"
_CUT_FILE_NAMES: Final = frozenset({"root_cut.json", "storyboard_cut.json"})
_SEQUENCE_LEDGER: Final = "sequence_state.json"
_SKIPPED_FOLDERS: Final = frozenset({"video_eval", "_archive", ".stablenew-library"})


@dataclass(frozen=True)
class FrameSweep:
    frames: int = 0
    bytes: int = 0
    runs: int = 0
    refused: str = ""  # why nothing was moved: what is protected is unknown
    bin_refusal: str = ""  # why the Recycle Bin cannot take them, or stopped taking them
    bin_room: str = ""  # dry run: the free room and limit of the bins the frames would go to
    stopped: bool = False  # a move began and was cut short; ``frames`` is what did move


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
        if len(str(frame)) > MAX_SHELL_PATH:
            continue  # the Recycle Bin cannot take it, so it stays
        if frame.is_file() and not frame.is_symlink():
            found.append(frame)
    return found


def _planned(
    root: Path, protected: set[tuple[str, str]], cutoff: float, should_stop: Callable[[], bool]
) -> list[tuple[Path, dict[str, int]]] | None:
    """Each run folder with the frames (name and size) a pass would move; ``None`` when asked to stop."""

    plan: list[tuple[Path, dict[str, int]]] = []
    for folder, files in _walk(root):
        if folder.name != "manifests":
            continue
        run = folder.parent
        # A large output folder holds far more image records than clip records: open only a clip's own manifest
        # (named after it), and none in a run already swept or inside a sequence.
        if (run / _SEQUENCE_LEDGER).exists() or frames_were_removed(run):
            continue
        clips = {clip.stem for clip in run.glob("*.mp4")}
        if not clips:
            continue
        if should_stop():
            return None
        doomed: dict[str, int] = {}
        for name in files:
            if not name.endswith(".json") or name.removesuffix(".json") not in clips:
                continue
            try:
                record = _read(folder / name)
            except _Unknown:
                continue  # an unreadable backend manifest lists nothing, so nothing of it is moved
            for frame in _candidates(run, record, cutoff):
                if _key(frame) not in protected:
                    doomed[frame.name] = frame.stat().st_size
        if doomed:
            plan.append((run, doomed))
    return plan


def _bin_rooms(plan: list[tuple[Path, dict[str, int]]], recycle_bin: RecycleBin) -> list[BinRoom]:
    """The bins the plan would use, or ``RecycleBinRefused`` when one cannot take its whole share."""

    needed: dict[str, int] = {}
    for run, doomed in plan:
        volume = recycle_bin.volume_of(run)
        share = sum(doomed.values()) + _BIN_OVERHEAD_BYTES * len(doomed)
        needed[volume] = needed.get(volume, 0) + share
    rooms = []
    for volume, size in needed.items():
        room = recycle_bin.room(volume)
        if size > room.free_bytes:
            raise RecycleBinRefused(
                f"The frames need {size / 1e9:.1f} GB. {room.describe()} Windows would permanently delete what "
                "does not fit, so nothing is moved. Make the bin larger (Recycle Bin Properties) or empty it."
            )
        rooms.append(room)
    return rooms


def _move(
    plan: list[tuple[Path, dict[str, int]]],
    recycle_bin: RecycleBin,
    should_stop: Callable[[], bool],
) -> FrameSweep:
    moved = size = runs = 0
    refusal = ""
    for run, doomed in plan:
        if should_stop():
            break
        present = [name for name in doomed if (run / name).is_file()]
        if not present:
            continue
        try:
            # Written first: a reader that finds a frame gone must be able to tell why.
            atomic_write_json(
                run / MARKER_NAME,
                {"removed_at": time.time(), "to": "recycle_bin", "frames": sorted(present)},
                indent=1,
            )
        except OSError as exc:
            logger.warning("Frames of %s were kept: the removal record failed: %s", run, exc)
            continue
        try:
            recycle_bin.move([run / name for name in present])
        except (RecycleBinRefused, OSError) as exc:
            refusal = f"{exc} The cleanup stopped at {run}."
            logger.warning("%s", refusal)
        gone = [name for name in present if not (run / name).exists()]
        if gone:
            runs += 1
            moved += len(gone)
            size += sum(doomed[name] for name in gone)
        else:
            (run / MARKER_NAME).unlink(missing_ok=True)  # nothing left: the run is looked at again
        if refusal:
            break
    if moved:
        logger.info(
            "Moved %d video frame PNGs (%.1f GB) from %d clip folders to the Recycle Bin; clips were kept.",
            moved,
            size / 1e9,
            runs,
        )
    return FrameSweep(
        frames=moved, bytes=size, runs=runs, bin_refusal=refusal, stopped=bool(refusal)
    )


def sweep_retained_frames(
    output_root: str | Path,
    *,
    tree_root: str | Path,
    recycle_bin: RecycleBin,
    now: float | None = None,
    min_age_seconds: float = MIN_AGE_SECONDS,
    should_stop: Callable[[], bool] = lambda: False,
    dry_run: bool = False,
) -> FrameSweep:
    """One pass over ``output_root``; ``should_stop`` is asked before each run folder.

    The pass first finds everything, then asks whether the Recycle Bin can take all of it, then moves it run by run.
    ``dry_run`` reports what a pass would move and whether the bin can take it, and writes and moves nothing."""

    root = Path(output_root).expanduser().resolve()
    if not root.is_dir():
        return FrameSweep()
    try:
        protected = _protected(root, Path(tree_root))
    except _Unknown as exc:
        logger.warning("No video frames were moved: %s", exc)
        return FrameSweep(refused=str(exc))
    cutoff = (time.time() if now is None else now) - min_age_seconds
    plan = _planned(root, protected, cutoff, should_stop)
    if not plan:
        return FrameSweep()
    found = FrameSweep(
        frames=sum(len(doomed) for _run, doomed in plan),
        bytes=sum(sum(doomed.values()) for _run, doomed in plan),
        runs=len(plan),
    )
    try:
        rooms = _bin_rooms(plan, recycle_bin)
    except RecycleBinRefused as exc:
        logger.warning("No video frames were moved to the Recycle Bin: %s", exc)
        # A real pass reports what it moved (nothing); the dry run reports what was due.
        return replace(found, bin_refusal=str(exc)) if dry_run else FrameSweep(bin_refusal=str(exc))
    if dry_run:
        return replace(found, bin_room=" ".join(room.describe() for room in rooms))
    return _move(plan, recycle_bin, should_stop)


__all__ = [
    "MARKER_NAME",
    "MIN_AGE_SECONDS",
    "FrameSweep",
    "frames_were_removed",
    "sweep_retained_frames",
]
