"""Source opening and bounded frame previews for the Harvest Motion workspace (PR-VID-MOTION-400).

Everything here is an explicit, read-only operation on one video: hash it (chunked, cancellable), probe it with the
existing bounded FFprobe/FFmpeg helpers, decide how strongly its originating job is established, and decode a few
exact frames by seeking.  It never decodes a whole source, writes a file, queues a job or starts a runtime.  Toolkit
neutral: the controller and the Tk dialog call these from a worker.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from src.queue.job_history_store import JobHistoryEntry
from src.video.driving_video_inspection import (
    PREVIEW_FRAME_COUNT,
    STATUS_FAILED,
    DrivingVideoFacts,
    DrivingVideoInspection,
    inspect_driving_video,
)
from src.video.motion_library.harvest import HarvestLineage
from src.video.motion_library.harvest_lineage import (
    lineage_from_asset,
    lineage_from_history,
    path_only,
)
from src.video.motion_library.harvest_window import parse_rate
from src.video.motion_library.hashing import HashCancelled, sha256_file
from src.video.motion_library.importer import SUPPORTED_SUFFIXES
from src.video.motion_library.models import MotionAsset
from src.video.motion_library.store import LibraryError, MotionLibraryStore
from src.video.motion_library.verification import FILE_OK, verify_content
from src.video.motion_source_plan import source_rate

HistoryReader = Callable[[str], JobHistoryEntry | None]
Inspector = Callable[..., DrivingVideoInspection]


@dataclass(frozen=True, slots=True)
class HarvestSourceRef:
    """What a surface hands to the workspace: the exact file, and *claims* about where it came from.

    ``job_id`` and ``asset_id`` are claims; ``open_harvest_source`` checks them against History and the library and
    reports how much of each could be established."""

    path: str
    label: str = ""
    job_id: str = ""
    asset_id: str = ""
    surface: str = ""
    #: What the content-visibility policy classifies (name, tags, prompt ...).  Not part of the source identity.
    subject: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class ExistingHarvest:
    asset_id: str
    name: str
    start_frame: int
    end_frame: int
    cadence: str


@dataclass(frozen=True, slots=True)
class HarvestSourceInfo:
    ref: HarvestSourceRef
    ok: bool
    error: str = ""
    path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    facts: DrivingVideoFacts | None = None
    rate: Fraction | None = None
    frame_count: int | None = None
    #: ``reported`` means the container states the count; anything else is an estimate and a window past it is only
    #: refused when decoding proves the frames are not there.
    frame_count_reliable: bool = False
    lineage: HarvestLineage = field(default_factory=HarvestLineage)
    library_asset_id: str = ""
    existing_harvests: tuple[ExistingHarvest, ...] = ()
    notes: tuple[str, ...] = ()


def _fail(ref: HarvestSourceRef, message: str, path: str = "") -> HarvestSourceInfo:
    return HarvestSourceInfo(ref=ref, ok=False, error=message, path=path)


def open_harvest_source(
    ref: HarvestSourceRef,
    *,
    store: MotionLibraryStore | None = None,
    history: HistoryReader | None = None,
    cancel: threading.Event | None = None,
    inspect: Inspector = inspect_driving_video,
) -> HarvestSourceInfo:
    """Verify the file, read its facts and establish what lineage the evidence supports.  Never raises."""

    text = str(ref.path or "").strip()
    if not text:
        return _fail(ref, "No video was chosen to harvest from.")
    path = Path(text).expanduser()
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return _fail(
            ref,
            f"Unsupported video format '{suffix or 'none'}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
            text,
        )
    try:
        if not path.is_file():
            return _fail(ref, f"The video file is missing or was moved: {path}", text)
        path = path.resolve()
        size = path.stat().st_size
        digest = sha256_file(path, cancel)
    except HashCancelled:
        return _fail(ref, "Opening the video was cancelled.", text)
    except OSError as exc:
        return _fail(ref, f"The video cannot be read: {exc}", text)

    probe = inspect(path, frame_count=0, cancel=cancel)
    if probe.status == STATUS_FAILED or probe.facts is None:
        reason = probe.issues[0].message if probe.issues else "The video could not be inspected."
        return _fail(ref, reason, str(path))
    facts = probe.facts
    rate = source_rate(facts)

    notes: list[str] = []
    library_asset_id = ""
    lineage = path_only(str(path), "Selected from a file; no originating job is claimed.")
    existing: tuple[ExistingHarvest, ...] = ()
    asset: MotionAsset | None = None
    if store is not None:
        asset = store.find_by_sha(digest)
        if asset is not None:
            library_asset_id = asset.asset_id
            existing = tuple(
                ExistingHarvest(
                    a.asset_id,
                    a.display_name,
                    a.harvest.start_frame,
                    a.harvest.end_frame,
                    a.harvest.cadence,
                )
                for a in store.harvests_of(digest)
                if a.harvest is not None
            )
    if ref.job_id:
        entry: JobHistoryEntry | None = None
        if history is not None:
            try:
                entry = history(ref.job_id)
            except Exception:  # noqa: BLE001 - a History read problem downgrades lineage, it never blocks harvesting
                entry = None
                notes.append(
                    "History could not be read, so the originating job is not established."
                )
        lineage = lineage_from_history(entry, str(path), digest, job_id=ref.job_id)
    elif asset is not None:
        try:
            check = (
                verify_content(asset, store.asset_path(asset), cancel)
                if store is not None
                else None
            )
        except LibraryError:
            check = None
        if check is not None and check.state == FILE_OK:
            lineage = lineage_from_asset(asset)
        else:
            lineage = path_only(
                str(path), "The library clip could not be verified; no lineage is claimed."
            )
    if facts.fps_is_variable_suspected:
        notes.append(
            "This video may be variable frame rate. It can be viewed here, but a window cannot be cut from it "
            "exactly; re-encode it at a constant frame rate first."
        )
    elif rate is None:
        notes.append(
            "The video reports no frame rate, so times cannot be placed; use frame numbers."
        )
    return HarvestSourceInfo(
        ref=ref,
        ok=True,
        path=str(path),
        sha256=digest,
        size_bytes=size,
        facts=facts,
        rate=rate,
        frame_count=facts.frame_count,
        frame_count_reliable=facts.frame_count_basis == "reported",
        lineage=lineage,
        library_asset_id=library_asset_id,
        existing_harvests=existing,
        notes=tuple(notes),
    )


@dataclass(frozen=True, slots=True)
class FramePreview:
    frame: int
    png_bytes: bytes
    caption: str


def preview_frames(
    path: str,
    frames: Sequence[int],
    rate: Fraction | None,
    *,
    cancel: threading.Event | None = None,
    inspect: Inspector = inspect_driving_video,
    label: str = "Frame",
) -> tuple[tuple[FramePreview, ...], tuple[str, ...]]:
    """Decode up to three exact frames by seeking (never the whole video).  Returns ``(previews, issues)``.

    FFmpeg's accurate input seek returns the first frame whose timestamp is *at or after* the requested time.  A frame
    ``n`` therefore is requested at ``n / rate`` truncated *down* to a millisecond: that is never later than the
    frame's own timestamp and, because a frame lasts longer than a millisecond, always later than the previous
    frame's.  (The middle of the interval would return frame ``n + 1``, and rounding to nearest can land just
    past frame ``n`` and return nothing for the last frame.)"""

    wanted = list(dict.fromkeys(int(f) for f in frames))[:PREVIEW_FRAME_COUNT]
    if not wanted:
        return (), ()
    if rate is None:
        return (), ("The video reports no frame rate, so frames cannot be located by number.",)
    positions = [math.floor(Fraction(n) / rate * 1000) / 1000 for n in wanted]
    result = inspect(path, frame_count=len(positions), positions=positions, cancel=cancel)
    if result.status == STATUS_FAILED:
        return (), tuple(issue.message for issue in result.issues) or (
            "The frames could not be read.",
        )
    by_position = {round(frame.position_seconds, 6): frame for frame in result.frames}
    previews = tuple(
        FramePreview(n, by_position[round(pos, 6)].png_bytes, f"{label} {n}")
        for n, pos in zip(wanted, positions, strict=True)
        if round(pos, 6) in by_position
    )
    issues = tuple(issue.message for issue in result.issues)
    return previews, issues


def representative_frames(start: int, end: int) -> tuple[int, int, int]:
    """First, middle and last frame of ``[start, end)`` (end exclusive)."""

    last = max(start, end - 1)
    return start, start + (last - start) // 2, last


__all__ = [
    "ExistingHarvest",
    "FramePreview",
    "HarvestSourceInfo",
    "HarvestSourceRef",
    "open_harvest_source",
    "parse_rate",
    "preview_frames",
    "representative_frames",
]
