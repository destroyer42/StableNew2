"""What Job History needs to know about a sequence job, read from its stored snapshot and result (PR-VID-SEQ-331A).

Pure and read-only: it inspects the mappings the repository already holds, so History can decide which actions to offer
and what progress to show without touching the queue or the file system. Lifecycle stays with the repository: the
status passed in is the repository's, and the ledger numbers are only evidence of how far the run got.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from src.queue.job_model import JobStatus
from src.video.sequence_resume import PLAN_KEY

_SEQUENCE_STAGES: Final = ("video_workflow", "svd_native")
_ARTIFACT_KEY: Final = "sequence_artifact"
_MAX_DEPTH: Final = 6
#: A ledger is small JSON; refuse anything larger rather than load it for a progress label.
_MAX_LEDGER_BYTES: Final = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SequenceHistoryInfo:
    """A sequence job as History sees it."""

    total_segments: int
    completed_segments: int
    status: JobStatus
    ledger_path: str | None = None
    ledger_state: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def can_resume(self) -> bool:
        """A failed or cancelled run continues from its checkpoint; a finished one has nothing left to resume."""

        return self.status in (JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def can_replay(self) -> bool:
        """A full replay recomputes every segment, so any finished run may be replayed."""

        return self.terminal

    @property
    def label(self) -> str:
        done = f"{self.completed_segments} of {self.total_segments} segments done"
        if self.status is JobStatus.COMPLETED:
            return f"Sequence: all {self.total_segments} segments done."
        if self.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            tail = "Resume continues from the checkpoint; Replay recomputes everything."
            return f"Sequence {self.status.value}: {done}. {tail}"
        return f"Sequence {self.status.value}: {done}."


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def planned_segments(snapshot: Mapping[str, Any] | None) -> int:
    """How many segments the frozen plan has, or 0 when the job is not a sequence."""

    workload = _mapping(_mapping(_mapping(snapshot).get("normalized_job")).get("workload"))
    config = _mapping(workload.get("config"))
    for stage in _SEQUENCE_STAGES:
        plan = _mapping(_mapping(config.get(stage)).get(PLAN_KEY))
        segments = plan.get("segments")
        if isinstance(segments, (list, tuple)) and segments:
            return len(segments)
    return 0


def find_sequence_artifact(result: Any, _depth: int = 0) -> Mapping[str, Any] | None:
    """The ``sequence_artifact`` pointer a run left in its result metadata (searched, not assumed)."""

    if _depth > _MAX_DEPTH:
        return None
    if isinstance(result, Mapping):
        found = result.get(_ARTIFACT_KEY)
        if isinstance(found, Mapping):
            return found
        children: Any = result.values()
    elif isinstance(result, (list, tuple)):
        children = result
    else:
        return None
    for child in children:
        nested = find_sequence_artifact(child, _depth + 1)
        if nested is not None:
            return nested
    return None


def sequence_history_info(
    snapshot: Mapping[str, Any] | None, result: Any, status: JobStatus
) -> SequenceHistoryInfo | None:
    """``None`` for an ordinary job; otherwise the facts History shows and the actions it offers."""

    total = planned_segments(snapshot)
    if total <= 0:
        return None
    artifact = _mapping(find_sequence_artifact(result))
    try:
        completed = int(artifact.get("completed_segments") or 0)
    except (TypeError, ValueError):
        completed = 0
    return SequenceHistoryInfo(
        total_segments=total,
        completed_segments=max(0, min(completed, total)),
        status=status,
        ledger_path=str(artifact["ledger_path"]) if artifact.get("ledger_path") else None,
        ledger_state=str(artifact.get("ledger_state") or ""),
    )


def read_ledger_progress(ledger_path: str | Path) -> tuple[int, int, str] | None:
    """``(completed_segments, total_segments, state)`` from a ledger file, or ``None`` when it cannot be read.

    Evidence for a progress label only; resume re-verifies the whole checkpoint before it trusts anything."""

    try:
        path = Path(ledger_path)
        if path.stat().st_size > _MAX_LEDGER_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            int(data["completed_prefix"]),
            int(data["total_segments"]),
            str(data.get("state") or ""),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


__all__ = [
    "SequenceHistoryInfo",
    "find_sequence_artifact",
    "planned_segments",
    "read_ledger_progress",
    "sequence_history_info",
]
