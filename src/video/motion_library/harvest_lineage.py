"""How strongly a harvest source's originating job/artifact is established (PR-VID-MOTION-400).

Identity is **never** inferred from a file name, a folder, a timestamp or a similar-looking prompt.  The only evidence
accepted is the canonical History record of the named job (completed, no error, naming this exact artifact path) and,
when the record kept one, the artifact's SHA-256 compared with the bytes about to be cut:

* ``verified``  - History names this artifact and its recorded SHA-256 equals the file's SHA-256;
* ``recorded``  - History names this artifact but kept no SHA-256, so the bytes are not independently verified;
* ``path_only`` - all that is known is where the file is (an imported file, a different artifact of the job, a
  recorded SHA-256 that no longer matches, or a job that was not found or did not complete);
* ``none``      - nothing is claimed.

A library asset is its own evidence: a StableNew-generated asset's recorded job is verified because the library
re-hashed the file; a harvested asset passes its own lineage on (the chain is kept, not strengthened).
"""

from __future__ import annotations

import os
from pathlib import Path

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.video.motion_library.harvest import HarvestLineage
from src.video.motion_library.importer import _history_video_path
from src.video.motion_library.models import (
    LINEAGE_NONE,
    LINEAGE_PATH_ONLY,
    LINEAGE_RECORDED,
    LINEAGE_VERIFIED,
    MotionAsset,
    clean_text,
)
from src.video.video_artifact_helpers import video_bundle_from_result


def _same_path(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        try:
            return os.path.normcase(os.path.abspath(str(Path(value).expanduser())))
        except (OSError, ValueError):
            return value

    return bool(left) and bool(right) and norm(left) == norm(right)


def path_only(path: str, note: str = "") -> HarvestLineage:
    return HarvestLineage(
        LINEAGE_PATH_ONLY,
        artifact_path=str(path or ""),
        note=clean_text(
            note or "Only the file's location is known; no originating job is claimed.", 300
        ),
    )


def lineage_from_history(
    entry: JobHistoryEntry | None, selected_path: str, selected_sha256: str, *, job_id: str = ""
) -> HarvestLineage:
    """Lineage of ``selected_path`` (whose bytes hash to ``selected_sha256``) against one canonical History entry."""

    claimed = str(job_id or (entry.job_id if entry is not None else ""))
    if entry is None:
        return path_only(
            selected_path, f"Job {claimed or '?'} was not found in History; no job is claimed."
        )
    if entry.status is not JobStatus.COMPLETED:
        return path_only(selected_path, f"Job {entry.job_id} did not complete; no job is claimed.")
    result = entry.result if isinstance(entry.result, dict) else {}
    if result.get("error"):
        return path_only(selected_path, f"Job {entry.job_id} recorded an error; no job is claimed.")
    bundle = video_bundle_from_result(result)
    recorded_path, reason = _history_video_path(bundle or {})
    if recorded_path is None:
        return path_only(selected_path, f"Job {entry.job_id}: {reason} No job is claimed.")
    if not _same_path(recorded_path, selected_path):
        return path_only(
            selected_path,
            f"This file is not the video artifact job {entry.job_id} recorded; no job is claimed.",
        )
    recorded_sha = str((bundle or {}).get("sha256") or "").lower()
    if not recorded_sha:
        return HarvestLineage(
            LINEAGE_RECORDED,
            entry.job_id,
            str(recorded_path),
            "",
            "History records this artifact path but no SHA-256, so the bytes are not independently verified.",
        )
    if recorded_sha != selected_sha256:
        return path_only(
            selected_path,
            f"The file no longer matches the SHA-256 job {entry.job_id} recorded; no job is claimed.",
        )
    return HarvestLineage(
        LINEAGE_VERIFIED,
        entry.job_id,
        str(recorded_path),
        recorded_sha,
        "History names this artifact and its recorded SHA-256 matches the file.",
    )


def lineage_from_asset(asset: MotionAsset) -> HarvestLineage:
    """Lineage of a cut taken from a library asset (its bytes were already verified by the caller)."""

    if asset.harvest is not None and asset.harvest.lineage_state != LINEAGE_NONE:
        h = asset.harvest
        return HarvestLineage(
            h.lineage_state,
            h.lineage_job_id,
            h.lineage_artifact_path,
            h.lineage_artifact_sha256,
            clean_text(
                f"Inherited from harvested library clip '{asset.display_name}'. {h.lineage_note}",
                300,
            ),
        )
    origin = asset.origin
    if origin is not None and origin.job_id:
        return HarvestLineage(
            LINEAGE_VERIFIED if origin.artifact_sha256 == asset.sha256 else LINEAGE_RECORDED,
            origin.job_id,
            origin.artifact_path,
            origin.artifact_sha256,
            clean_text(f"Library clip '{asset.display_name}' was kept from this job.", 300),
        )
    return HarvestLineage(
        LINEAGE_NONE, note=clean_text(f"Cut from library clip '{asset.display_name}'.", 300)
    )


__all__ = ["lineage_from_asset", "lineage_from_history", "path_only"]
