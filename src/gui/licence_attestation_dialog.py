"""The desktop's per-job licence confirmation (VID-CAND-LTX25), asked at Queue and never saved.

Every Tk screen that queues a video job calls this just before it queues.  The sentence and the decision about which
workflows need it live in ``src/video/licence_attestation.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from tkinter import messagebox
from typing import Any

from src.video.licence_attestation import attestation_record, declared_attestation, workflow_ids_of

NOT_CONFIRMED = "Not queued: the licence confirmation was not given."


def ask_licence_attestation(
    parent: Any, workflow_ids: Iterable[Any], *, job_count: int = 1
) -> dict[str, Any] | None:
    """``{}`` when these workflows need none, the record when the operator confirms, ``None`` when they do not.

    Tk thread only.  The dialog defaults to No, so a stray Enter confirms nothing.
    """

    declared = declared_attestation(*workflow_ids)
    if declared is None:
        return {}
    message = declared.text
    if job_count > 1:
        message += f"\n\nThis applies to all {job_count} LTX-2.5 jobs you are queueing."
    if not messagebox.askyesno(
        "Confirm before queueing",
        message,
        icon=messagebox.WARNING,
        default=messagebox.NO,
        parent=parent,
    ):
        return None
    return attestation_record(declared)


def ask_for_jobs(parent: Any, records: Iterable[Any]) -> dict[str, Any] | None:
    """The same question for already built NJRs (a batch or an eval run): one confirmation for those that need it."""

    needing = [
        ids for ids in (workflow_ids_of(record) for record in records) if declared_attestation(*ids)
    ]
    return ask_licence_attestation(
        parent, [item for ids in needing for item in ids], job_count=len(needing)
    )


__all__ = ["NOT_CONFIRMED", "ask_for_jobs", "ask_licence_attestation"]
