"""Typed policy for submitting an already compiled NJR to the queue."""

from __future__ import annotations

from dataclasses import dataclass

from src.queue.job_model import JobPriority


@dataclass(frozen=True, slots=True)
class SubmissionPolicy:
    """Scheduling choices that are not part of immutable authorized work."""

    priority: JobPriority = JobPriority.NORMAL
    start_when_idle: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.priority, JobPriority):
            raise TypeError("SubmissionPolicy.priority must be a JobPriority")


__all__ = ["SubmissionPolicy"]
