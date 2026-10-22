"""Recent video outputs recovered from canonical persisted jobs (PR-VID-UX-314).

The Video Workflow tab shows the newest finished clips so a user never has to hunt through ``output/``.
Nothing here is a second history: every row is derived, read-only, from a ``JobHistoryEntry`` the SQLite
repository already owns (its recorded video bundle and its frozen NJR snapshot).  Nothing is written,
queued, repaired or probed beyond a file-existence check, and no directory is scanned.

Rules (each has a test):

* only a ``COMPLETED`` job without a recorded error qualifies;
* a job qualifies only when its recorded bundle names a supported video file that exists right now, so an
  output that was moved or deleted is not offered (Open and Reveal would fail);
* the result is bounded by ``limit`` and ordered newest first by the repository's own timestamps;
* provenance (workflow, source image, seed, length) is read from the frozen NJR snapshot when it is there and
  is simply empty when it is not; it is never recomputed.

It imports nothing from the GUI or controller layers.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.video.video_artifact_helpers import video_bundle_from_result
from src.video.video_review_group import bundle_video_path

#: How many newest completed jobs are inspected to find ``limit`` playable clips.
DEFAULT_SCAN_WINDOW = 60
DEFAULT_LIMIT = 12


@dataclass(frozen=True)
class RecentVideoOutput:
    """One finished clip and the facts a user needs to recognise it."""

    job_id: str
    video_path: str
    completed_at: datetime | None
    backend_id: str = ""
    workflow_label: str = ""
    source_image_path: str = ""
    seed: int | None = None
    frame_count: int | None = None
    fps: float | None = None
    #: The recorded bundle, unchanged, so Send to Movie hands over exactly what history recorded.
    bundle: Mapping[str, Any] = field(default_factory=dict)

    @property
    def file_name(self) -> str:
        return Path(self.video_path).name

    @property
    def length_text(self) -> str:
        if self.frame_count and self.fps:
            return f"{self.frame_count} frames (~{self.frame_count / self.fps:.1f} s)"
        if self.frame_count:
            return f"{self.frame_count} frames"
        return "-"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalized_job(snapshot: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return _mapping(_mapping(snapshot).get("normalized_job"))


def _video_block(snapshot: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The frozen ``video_workflow`` config of a stored NJR snapshot, or an empty mapping."""

    workload = _mapping(_normalized_job(snapshot).get("workload"))
    return _mapping(_mapping(workload.get("config")).get("video_workflow"))


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _workflow_label(
    entry: JobHistoryEntry, block: Mapping[str, Any], bundle: Mapping[str, Any]
) -> str:
    provenance = _mapping(_normalized_job(entry.snapshot).get("provenance"))
    named = _mapping(_mapping(provenance.get("metadata")).get("video_workflow"))
    if named.get("display_name"):
        return str(named["display_name"])
    if block.get("workflow_id"):
        return str(block["workflow_id"])
    return str(bundle.get("backend_id") or bundle.get("stage") or "")


def recent_output_from_entry(
    entry: JobHistoryEntry, *, is_file: Callable[[str], bool] = os.path.isfile
) -> RecentVideoOutput | None:
    """The playable clip of one finished job, or ``None`` when it has none (see the module rules)."""

    if entry.status is not JobStatus.COMPLETED:
        return None
    result = entry.result if isinstance(entry.result, dict) else {}
    if result.get("error"):
        return None
    bundle = video_bundle_from_result(result)
    if bundle is None:
        return None
    path, _reason = bundle_video_path(bundle)
    if path is None:
        return None
    try:
        if not is_file(path):
            return None
    except (OSError, ValueError):
        return None
    block = _video_block(entry.snapshot)
    source = _mapping(block.get("source_preparation")).get("original_source_path")
    return RecentVideoOutput(
        job_id=entry.job_id,
        video_path=path,
        completed_at=entry.completed_at or entry.created_at,
        backend_id=str(block.get("backend_id") or bundle.get("backend_id") or ""),
        workflow_label=_workflow_label(entry, block, bundle),
        source_image_path=str(source or bundle.get("source_image_path") or ""),
        seed=_int_or_none(block.get("seed")),
        frame_count=_int_or_none(block.get("frame_count")) or _int_or_none(bundle.get("count")),
        fps=_float_or_none(block.get("fps")),
        bundle=dict(bundle),
    )


def discover_recent_video_outputs(
    entries: Iterable[JobHistoryEntry],
    *,
    limit: int = DEFAULT_LIMIT,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> list[RecentVideoOutput]:
    """Playable clips of ``entries`` (already newest first), at most ``limit``."""

    wanted = max(0, int(limit))
    found: list[RecentVideoOutput] = []
    for entry in entries:
        if len(found) >= wanted:
            break
        output = recent_output_from_entry(entry, is_file=is_file)
        if output is not None:
            found.append(output)
    return found


def list_recent_video_outputs(
    repository: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    scan_window: int = DEFAULT_SCAN_WINDOW,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> list[RecentVideoOutput]:
    """Newest playable clips from the repository's completed jobs (one bounded read; worker-safe)."""

    reader = getattr(repository, "list_recent_jobs", None)
    if not callable(reader):
        return []
    entries = reader(statuses={JobStatus.COMPLETED}, limit=max(int(limit), int(scan_window)))
    return discover_recent_video_outputs(entries, limit=limit, is_file=is_file)


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_SCAN_WINDOW",
    "RecentVideoOutput",
    "discover_recent_video_outputs",
    "list_recent_video_outputs",
    "recent_output_from_entry",
]
