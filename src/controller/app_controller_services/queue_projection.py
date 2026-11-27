"""Build the queue projection, converting each job's immutable NJR into its summary only once (RUN-LEAN).

Converting one NJR thaws its whole frozen config, about 0.2 ms. The queue is projected on every job start and finish,
so with about 1,900 jobs queued the conversion held the GIL for most of a second per completed job, while the next job
was preparing. Only the status of a summary can change, so the converted summary is kept per job and replaced only when
the status or the record itself changes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from src.pipeline.job_models_v2 import JobStatusV2, UnifiedJobSummary

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Cached:
    record: Any
    status_text: str
    summary: UnifiedJobSummary


@dataclass(frozen=True, slots=True)
class QueueProjectionResult:
    items: list[str]
    summaries: list[UnifiedJobSummary]
    fallback_count: int


class QueueSummaryProjector:
    """One cache for one queue view; holds only the jobs of the last projection."""

    def __init__(self) -> None:
        self._cache: dict[str, _Cached] = {}
        self._lock = threading.Lock()

    def project(self, jobs: Iterable[Any]) -> QueueProjectionResult:
        items: list[str] = []
        summaries: list[UnifiedJobSummary] = []
        fallback_count = 0
        with self._lock:
            previous, current = self._cache, {}
            for job in jobs:
                record = getattr(job, "_normalized_record", None)
                if record:
                    try:
                        entry = self._entry(job, record, previous.get(job.job_id))
                    except Exception as exc:
                        logger.warning("Failed to convert job %s to UnifiedJobSummary: %s", job.job_id, exc)
                        items.append(job.job_id)
                        fallback_count += 1
                        continue
                    current[job.job_id] = entry
                    summaries.append(entry.summary)
                    items.append(entry.summary.positive_prompt_preview or job.job_id)
                    continue
                logger.debug("Job %s missing NJR, using fallback queue summary", job.job_id)
                items.append(job.job_id)
                fallback_count += 1
                try:
                    status_value = str(getattr(job, "status", "queued")).lower()
                    status = (
                        JobStatusV2(status_value)
                        if status_value in JobStatusV2._value2member_map_
                        else JobStatusV2.QUEUED
                    )
                    summaries.append(UnifiedJobSummary.from_job(job, status))
                except Exception:
                    logger.warning("Job %s is left out of the queue list: no summary", job.job_id, exc_info=True)
            self._cache = current
        return QueueProjectionResult(items, summaries, fallback_count)

    @staticmethod
    def _entry(job: Any, record: Any, cached: _Cached | None) -> _Cached:
        status = getattr(job, "status", None)
        status_text = str(getattr(status, "value", status) or "").strip().upper()
        if cached is not None and cached.record is record:
            if cached.status_text == status_text:
                return cached
            base = cached.summary
        else:
            base = UnifiedJobSummary.from_normalized_record(record)
        summary = replace(base, status=status_text) if status_text else base
        return _Cached(record, status_text, summary)
