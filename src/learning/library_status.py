"""Experiment Library status from exact recorded job IDs; a read-only projection.

A saved session records each variant's status as it was when the session was saved. A variant saved while
queued or running keeps that status on disk even after its job finished, so the Library would keep showing
"Queued" for work that is long done. This projection reads each such variant's job by its exact recorded
ID through the existing reconciliation lookup (``read_job_evidence``) and reports the repository's status.

It never saves the session, binds or tracks jobs, replays completions, retries, or changes any lifecycle.
Opening the experiment still runs the full reconciliation. An identity that cannot be resolved is shown as
requiring attention rather than hidden.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.learning.experiment_lifecycle import classify_experiment_lifecycle
from src.learning.experiment_reconciliation import read_job_evidence

#: Saved variant statuses whose job may have moved on since the session was saved.
OPEN_STATUSES = frozenset({"pending", "queued", "running"})


@dataclass(frozen=True)
class LibraryStatus:
    lifecycle: str
    note: str = ""


def has_open_jobs(payload: Mapping[str, Any] | None) -> bool:
    """Whether any saved variant with a recorded job is still queued, pending or running on disk."""
    return any(
        isinstance(item, Mapping)
        and str(item.get("job_id") or "").strip()
        and str(item.get("status") or "").strip().lower() in OPEN_STATUSES
        for item in list((payload or {}).get("plan") or [])
    )


def library_status(
    payload: Mapping[str, Any] | None, repository: Any, *, saved_rating_count: int = 0
) -> LibraryStatus:
    """The lifecycle to show for a saved experiment, with saved open jobs read from job history."""
    saved = classify_experiment_lifecycle(payload, saved_rating_count=saved_rating_count)
    if not has_open_jobs(payload):
        return LibraryStatus(saved)
    if not callable(getattr(repository, "get_job_model", None)):
        return LibraryStatus(
            saved, "Job history unavailable; showing the status saved with the session."
        )
    from src.gui.learning_state import LearningExperiment, LearningVariant

    projected = copy.deepcopy(dict(payload or {}))
    try:
        experiment = LearningExperiment.from_dict(dict(projected.get("current_experiment") or {}))
    except (TypeError, ValueError, AttributeError):
        return LibraryStatus(saved, "Saved session could not be read; open it to reconcile.")
    observed: Counter[str] = Counter()
    unresolved = 0
    for item in projected.get("plan") or []:
        if (
            not isinstance(item, dict)
            or str(item.get("status") or "").strip().lower() not in OPEN_STATUSES
        ):
            continue
        if not str(item.get("job_id") or "").strip():
            continue
        try:
            variant = LearningVariant.from_dict(item)
        except (TypeError, ValueError):
            variant = None
        evidence = (
            read_job_evidence(repository, experiment, variant) if variant is not None else None
        )
        if evidence is None or evidence.error or evidence.job is None:
            unresolved += 1
            item["status"] = "requires_attention"
            continue
        status = str(getattr(evidence.job.status, "value", evidence.job.status) or "").lower()
        if status:
            item["status"] = status
            observed[status] += 1
    lifecycle = classify_experiment_lifecycle(projected, saved_rating_count=saved_rating_count)
    parts = [f"{count} {status}" for status, count in sorted(observed.items())]
    if unresolved:
        parts.append(f"{unresolved} could not be matched to a recorded job")
    note = f"Job history: {', '.join(parts)}." if parts else ""
    if lifecycle != saved:
        note = f"{note} Saved as {saved}; open it to load results.".strip()
    return LibraryStatus(lifecycle, note)
