"""Read storyboard cuts back from the repository and pin lead-ins (PR-VID-STORY-380, spec 7.5).

Tk-free helpers for the storyboard submission service. A node's cut is the root's hash-pinned manifest or, for a
take, the prefix through the take's own range of one attempt's cut manifest. Job records are read defensively: a
corrupt repository row or a changed manifest on one attempt is skipped (and logged), and an older usable attempt is
used instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from src.queue.job_repository import JobRepositoryError
from src.video.sequence_ledger import SequenceLedgerError, read_ledger
from src.video.sequence_locator import locate_ledger
from src.video.sequence_plan import StoryboardLeadIn
from src.video.sequence_resume import find_ledger_path
from src.video.storyboard_cut import (
    CutFrame,
    CutManifest,
    CutManifestError,
    read_cut_manifest,
    write_cut_manifest,
)
from src.video.storyboard_root import STORYBOARDS_FOLDER
from src.video.storyboard_tree import Take, TreeRoot

LEADINS_FOLDER: Final = "leadins"

logger = logging.getLogger(__name__)


def read_job(repository: Any, job_id: str) -> Any | None:
    """``repository.get_job_model(job_id)``, or ``None`` when the job is absent or its record cannot be read."""

    if repository is None:
        return None
    try:
        return repository.get_job_model(job_id)
    except (JobRepositoryError, ValueError) as exc:
        logger.warning("storyboard: skipping job %s; its record cannot be read: %s", job_id, exc)
        return None


def _status(job: Any) -> str:
    status = getattr(job, "status", None)
    return str(getattr(status, "value", status) or "")


def _reference(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping) and value.get("path") and value.get("sha256"):
        return value
    return None


def manifest_reference(
    job_id: str, job: Any, output_roots: Iterable[str | None]
) -> Mapping[str, Any] | None:
    """The ``{path, sha256}`` of a take job's cut manifest: its result, else its ledger (running or stopped)."""

    result = getattr(job, "result", None)
    metadata = result.get("metadata") if isinstance(result, Mapping) else None
    artifact = metadata.get("sequence_artifact") if isinstance(metadata, Mapping) else None
    reference = _reference(artifact.get("cut_manifest") if isinstance(artifact, Mapping) else None)
    if reference is not None:
        return reference
    njr = getattr(job, "_normalized_record", None)
    roots = [*output_roots, getattr(njr, "path_output_dir", None)]
    path = find_ledger_path(result) or locate_ledger(job_id, [r for r in roots if r])
    if not path:
        return None
    try:
        ledger = read_ledger(Path(path))
    except SequenceLedgerError:
        return None
    return _reference(ledger.cut_manifest) if ledger.job_id == job_id else None


def root_cut(root: TreeRoot) -> CutManifest | None:
    """The root clip's cut (hash-pinned), or ``None`` for an image root."""

    if root.kind != "clip" or not root.manifest_path:
        return None
    return read_cut_manifest(root.manifest_path, expected_sha256=root.manifest_sha256)


def take_cut(repository: Any, take: Take, output_roots: Iterable[str | None]) -> CutManifest | None:
    """The take's cut: the prefix through its own range of its newest completed attempt's manifest, else its newest
    attempt's manifest that covers it.

    An attempt whose record cannot be read, or whose manifest is missing or changed, is skipped for an older usable
    one. ``None`` when no attempt has frames for the take; when every candidate failed, the first failure is raised.
    """

    roots = list(output_roots)
    completed: list[tuple[str, Mapping[str, Any]]] = []
    others: list[tuple[str, Mapping[str, Any]]] = []
    for job_id in reversed(take.attempts):
        job = read_job(repository, job_id)
        reference = None if job is None else manifest_reference(job_id, job, roots)
        if reference is not None:
            (completed if _status(job) == "completed" else others).append((job_id, reference))
    first_error: CutManifestError | None = None
    for job_id, reference in (*completed, *others):
        try:
            manifest = read_cut_manifest(
                str(reference["path"]), expected_sha256=str(reference["sha256"])
            )
        except CutManifestError as exc:
            logger.warning(
                "storyboard: attempt %s of take %s is unusable: %s", job_id, take.take_id, exc
            )
            first_error = first_error or exc
            continue
        owned = [item for item in manifest.segment_ranges() if item.owner == take.take_id]
        if owned:
            return manifest.prefix(owned[-1].end + 1)
    if first_error is not None:
        raise first_error
    return None


def write_lead_in(
    output_root: str | Path, storyboard_id: str, batch_id: str, cut: CutManifest
) -> StoryboardLeadIn:
    """Copy the lead-in's frame references (never frames) to ``<output_root>/storyboards/<id>/leadins/<batch>.json``.

    The plan pins this copy, not the parent's job manifest, because a still-running chain rewrites that after every
    segment. Frame paths are written resolved (ruling R1), matching the exact-source path admission records.
    """

    frames = tuple(
        CutFrame(path=str(Path(frame.path).resolve()), sha256=frame.sha256) for frame in cut.frames
    )
    target = (
        Path(output_root).expanduser().resolve()
        / STORYBOARDS_FOLDER
        / storyboard_id
        / LEADINS_FOLDER
        / f"{batch_id}.json"
    )
    written = write_cut_manifest(target, replace(cut, frames=frames))
    return StoryboardLeadIn(
        manifest_path=written.path,
        manifest_sha256=written.sha256,
        frame_count=len(frames),
        handoff_path=frames[-1].path,
        handoff_sha256=frames[-1].sha256,
    )


__all__ = [
    "LEADINS_FOLDER",
    "manifest_reference",
    "read_job",
    "root_cut",
    "take_cut",
    "write_lead_in",
]
