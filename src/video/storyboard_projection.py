"""Read-only projection of a storyboard's takes from the repository (PR-VID-STORY-380, spec 7.7).

The storyboard file records takes and their job ids (attempts) and nothing else. This module reads each take's state,
progress, cut manifest, stitched video and own clip back from the repository and the job's ledger. It writes nothing
and never touches job state. Hashing is left to admission: the frame check here is an existence check only.

Worker-side: it reads files. The Storyboard tab runs it through its work runner.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from src.queue.job_model import JobStatus
from src.video.sequence_history import find_sequence_artifact
from src.video.sequence_ledger import SequenceLedger, SequenceLedgerError, read_ledger
from src.video.sequence_locator import locate_ledger
from src.video.sequence_resume import find_ledger_path
from src.video.storyboard_cut import (
    CutFrame,
    CutManifest,
    CutManifestError,
    read_cut_manifest,
)
from src.video.storyboard_tree import StoryboardTree, Take

logger = logging.getLogger(__name__)

TakeState = Literal["pending", "queued", "running", "completed", "failed", "cancelled", "unknown"]

#: Fixed copy (spec 7.9).
PROBLEM_PREFIX: Final = "frames missing or changed: "

_STATES: Final[Mapping[JobStatus, TakeState]] = {
    JobStatus.QUEUED: "queued",
    JobStatus.RUNNING: "running",
    JobStatus.COMPLETED: "completed",
    JobStatus.FAILED: "failed",
    JobStatus.CANCELLED: "cancelled",
}


@dataclass(frozen=True, slots=True)
class TakeView:
    take_id: str
    state: TakeState
    status_text: str
    shown_job_id: str | None
    #: Path and SHA-256 of the cut manifest the card shows (the job's own manifest, covering this take).
    manifest: CutFrame | None
    stitched_path: str | None
    clip_path: str | None
    #: True when the stitched video file exists. A take with a manifest but no video is ``not encoded``.
    encoded: bool
    frames_ok: bool
    problem: str
    can_resume: bool
    can_replay: bool
    #: First frame this take owns (for its card thumbnail); ``None`` until it has a readable manifest.
    thumbnail_path: str | None = None


def _state(entry: Any) -> TakeState:
    status = getattr(entry, "status", None)
    if isinstance(status, JobStatus):
        return _STATES.get(status, "unknown")
    try:
        return _STATES.get(JobStatus(str(getattr(status, "value", status))), "unknown")
    except ValueError:
        return "unknown"


def _shown_attempt(take: Take, entries: Mapping[str, Any]) -> str | None:
    """The newest completed attempt, else the newest attempt the repository still holds."""

    known = [job_id for job_id in take.attempts if job_id in entries]
    for job_id in reversed(known):
        if _state(entries[job_id]) == "completed":
            return job_id
    return known[-1] if known else None


def _reference(value: Any) -> CutFrame | None:
    if isinstance(value, Mapping) and value.get("path") and value.get("sha256"):
        return CutFrame(path=str(value["path"]), sha256=str(value["sha256"]))
    return None


def _read_ledger(job_id: str, result: Any, roots: Iterable[str]) -> SequenceLedger | None:
    path = find_ledger_path(result) or locate_ledger(job_id, list(roots))
    if not path:
        return None
    try:
        ledger = read_ledger(Path(path))
    except SequenceLedgerError as exc:
        logger.debug("storyboard: ledger of job %s is unreadable: %s", job_id, exc)
        return None
    return ledger if ledger.job_id == job_id else None


def _status_text(state: TakeState, ledger: SequenceLedger | None) -> str:
    if state == "running" and ledger is not None and ledger.total_segments > 0:
        current = min(ledger.completed_prefix + 1, ledger.total_segments)
        return f"running segment {current} of {ledger.total_segments}"
    return state


def _own_clip(artifact: Mapping[str, Any], ledger: SequenceLedger | None, index: int) -> str | None:
    provenance = artifact.get("segment_provenance")
    if isinstance(provenance, (list, tuple)):
        for item in provenance:
            if (
                isinstance(item, Mapping)
                and item.get("segment_index") == index
                and item.get("primary_output_path")
            ):
                return str(item["primary_output_path"])
    if ledger is not None:
        for segment in ledger.segments:
            if segment.index == index and segment.clip is not None:
                return segment.clip.path
    return None


def _cut_for_take(reference: CutFrame, take: Take) -> tuple[CutManifest | None, str]:
    """The job's manifest, if it covers this take; else the reason it cannot be read."""

    try:
        manifest = read_cut_manifest(reference.path, expected_sha256=reference.sha256)
    except CutManifestError as exc:
        return None, f"{PROBLEM_PREFIX}{reference.path} ({exc})"
    if not any(item.owner == take.take_id for item in manifest.segment_ranges()):
        return None, ""
    return manifest, ""


def project_take(
    take: Take,
    entries: Mapping[str, Any],
    *,
    output_roots: Sequence[str],
    check_frames: Callable[[CutManifest], str | None],
) -> TakeView:
    shown = _shown_attempt(take, entries)
    if shown is None:
        state: TakeState = "pending" if not take.attempts else "unknown"
        return TakeView(
            take.take_id, state, state, None, None, None, None, False, True, "", False, False
        )
    entry = entries[shown]
    state = _state(entry)
    result = getattr(entry, "result", None)
    roots = [root for root in output_roots if root]
    ledger = _read_ledger(shown, result, roots)
    artifact = find_sequence_artifact(result) or {}
    reference = _reference(artifact.get("cut_manifest")) or (
        None if ledger is None else _reference(ledger.cut_manifest)
    )
    assembled = artifact.get("assembled_video")
    if not isinstance(assembled, Mapping) and ledger is not None:
        assembled = ledger.assembly
    stitched = (
        str(assembled["output_path"])
        if isinstance(assembled, Mapping) and assembled.get("output_path")
        else None
    )
    manifest, problem = (None, "") if reference is None else _cut_for_take(reference, take)
    frames_ok = True
    if manifest is not None:
        missing = check_frames(manifest.prefix(_end_of(manifest, take) + 1))
        if missing is not None:
            frames_ok, problem = False, f"{PROBLEM_PREFIX}{missing}"
    elif problem:
        frames_ok = False
    terminal = state in ("completed", "failed", "cancelled")
    return TakeView(
        take_id=take.take_id,
        state=state,
        status_text=_status_text(state, ledger),
        shown_job_id=shown,
        manifest=reference if manifest is not None else None,
        stitched_path=stitched,
        clip_path=_own_clip(artifact, ledger, take.segment_index),
        encoded=bool(stitched) and Path(str(stitched)).is_file(),
        frames_ok=frames_ok,
        problem=problem,
        can_resume=state in ("failed", "cancelled"),
        can_replay=terminal,
        thumbnail_path=None if manifest is None else _thumbnail(manifest, take),
    )


def _thumbnail(manifest: CutManifest, take: Take) -> str | None:
    owned = [item for item in manifest.segment_ranges() if item.owner == take.take_id]
    return manifest.frames[owned[0].start].path if owned else None


def _end_of(manifest: CutManifest, take: Take) -> int:
    owned = [item for item in manifest.segment_ranges() if item.owner == take.take_id]
    return owned[-1].end


def project_storyboard(
    tree: StoryboardTree,
    repository: Any,
    *,
    output_roots: Sequence[str],
    check_frames: Callable[[CutManifest], str | None],
) -> dict[str, TakeView]:
    """Every take's view, in the tree's creation order. Read-only; one bounded repository read."""

    job_ids = list(dict.fromkeys(job for take in tree.takes for job in take.attempts))
    entries: Mapping[str, Any] = {}
    if job_ids and repository is not None:
        entries = repository.get_job_entries(job_ids)
    return {
        take.take_id: project_take(
            take, entries, output_roots=output_roots, check_frames=check_frames
        )
        for take in tree.takes
    }


def first_missing_frame(manifest: CutManifest) -> str | None:
    """The first frame file that does not exist (existence only; admission hashes)."""

    for frame in manifest.frames:
        if not Path(frame.path).is_file():
            return frame.path
    return None


__all__ = [
    "PROBLEM_PREFIX",
    "TakeState",
    "TakeView",
    "first_missing_frame",
    "project_storyboard",
    "project_take",
]
