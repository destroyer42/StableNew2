"""Resolve a batch's recorded outputs against the file system (PR-BATCH-OPS-201).

Pure derivation over the already-projected ``BatchSummary`` plus read-only file checks (existence and, for images, a
header-level ``PIL`` verify). Nothing is copied, moved, opened or handed to another tab here; the caller does that
only with what this returns, so a missing or unreadable file can never look like a successful hand-off.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.queue.batch_projection import BatchSummary, OutputKind


@dataclass(frozen=True)
class OutputResolution:
    images: tuple[str, ...] = ()
    videos: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    #: ``(job_id, path, reason)`` for every referenced output that is missing, moved or not a valid image.
    unavailable: tuple[tuple[str, str, str], ...] = ()
    jobs_without_outputs: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()


def _is_valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception:  # noqa: BLE001 - any decode failure means "not a usable image"
        return False
    return True


def resolve_job_outputs(
    summary: BatchSummary, job_ids: Sequence[str], *, verify_images: bool = True
) -> OutputResolution:
    """Existing, usable outputs of ``job_ids`` in selection order, then artifact order."""

    images: list[str] = []
    videos: list[str] = []
    folders: list[str] = []
    unavailable: list[tuple[str, str, str]] = []
    without: list[str] = []
    for job_id in dict.fromkeys(job_ids):
        job = summary.job(job_id)
        if job is None or not job.artifacts:
            without.append(job_id)
            continue
        for ref in job.artifacts:
            if ref.origin == "thumbnail" and job.workload_kind != "video":
                continue  # a thumbnail is a Review candidate only for a video job's explicit hand-off
            path = Path(ref.path)
            if not path.is_file():
                unavailable.append((job_id, ref.path, "missing or moved"))
                continue
            folder = str(path.parent)
            if folder not in folders:
                folders.append(folder)
            if ref.kind is OutputKind.VIDEO and ref.path not in videos:
                videos.append(ref.path)
            elif ref.kind is OutputKind.IMAGE and ref.path not in images:
                if not verify_images or _is_valid_image(path):
                    images.append(ref.path)
                else:
                    unavailable.append((job_id, ref.path, "not a readable image"))
    messages: list[str] = []
    if without:
        messages.append(f"{len(without)} selected job(s) have no recorded output.")
    if unavailable:
        messages.append(f"{len(unavailable)} recorded output file(s) are missing or unreadable.")
    return OutputResolution(
        tuple(images), tuple(videos), tuple(folders), tuple(unavailable), tuple(without), tuple(messages)
    )


__all__ = ["OutputResolution", "resolve_job_outputs"]
