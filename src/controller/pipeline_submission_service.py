from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.queue.job_model import Job, JobPriority
from src.utils.snapshot_builder_v2 import build_job_snapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelinePreviewSubmissionResult:
    submitted_jobs: int
    run_mode: str


class PipelinePreviewSubmissionService:
    """Own conversion and submission of preview NJRs onto the queue."""

    def __init__(
        self,
        *,
        job_service: Any,
        run_job_callback: Callable[[Job], dict | None],
        learning_enabled: bool,
    ) -> None:
        self._job_service = job_service
        self._run_job_callback = run_job_callback
        self._learning_enabled = learning_enabled

    @staticmethod
    def _attach_submission_batch_id(record: Any, submission_batch_id: str) -> None:
        extra_metadata = getattr(record, "extra_metadata", None)
        if not isinstance(extra_metadata, dict):
            extra_metadata = {}
        else:
            extra_metadata = dict(extra_metadata)
        extra_metadata["submission_batch_id"] = submission_batch_id
        record.extra_metadata = extra_metadata

    def to_queue_job(
        self,
        record: Any,
        *,
        run_mode: str,
        source: str,
        prompt_source: str,
        prompt_pack_id: str | None,
        last_run_config: dict[str, Any] | None,
    ) -> Job:
        if record is None:
            raise ValueError("PR-CTRL-205: to_queue_job requires a NormalizedJobRecord")

        config_snapshot = record.to_queue_snapshot()
        randomizer_metadata = record.randomizer_summary
        effective_prompt_pack_id = prompt_pack_id or getattr(record, "prompt_pack_id", None) or None
        prompt_source_value = prompt_source or getattr(record, "prompt_source", None) or "manual"
        prompt_source_value = str(prompt_source_value).lower()
        if effective_prompt_pack_id and prompt_source_value != "pack":
            prompt_source_value = "pack"

        job = Job(
            job_id=record.job_id,
            priority=JobPriority.NORMAL,
            run_mode=run_mode,
            source=source,
            prompt_source=prompt_source_value,
            prompt_pack_id=effective_prompt_pack_id,
            config_snapshot=config_snapshot,
            randomizer_metadata=randomizer_metadata,
            variant_index=record.variant_index,
            variant_total=record.variant_total,
            learning_enabled=self._learning_enabled,
        )
        job.snapshot = build_job_snapshot(job, record, run_config=last_run_config)
        job._normalized_record = record  # type: ignore[attr-defined]
        logger.debug(
            "Prepared NJR-backed job for queue",
            extra={
                "job_id": job.job_id,
                "prompt_source": prompt_source_value,
                "prompt_pack_id": effective_prompt_pack_id,
                "prompt_pack_name": getattr(record, "prompt_pack_name", None),
            },
        )
        return job

    def submit_preview_jobs(
        self,
        normalized_jobs: list[Any],
        *,
        run_mode: str,
        source: str,
        prompt_source: str,
        prompt_pack_id: str | None,
        last_run_config: dict[str, Any] | None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> PipelinePreviewSubmissionResult | None:
        if not normalized_jobs:
            return None

        submitted_count = 0
        submission_batch_id = uuid4().hex
        effective_prompt_pack_id = prompt_pack_id
        if not effective_prompt_pack_id:
            effective_prompt_pack_id = (last_run_config or {}).get("prompt_pack_id")

        jobs_to_submit: list[Job] = []
        for record in normalized_jobs:
            try:
                self._attach_submission_batch_id(record, submission_batch_id)
                job = self.to_queue_job(
                    record,
                    run_mode=run_mode,
                    source=source,
                    prompt_source=prompt_source,
                    prompt_pack_id=effective_prompt_pack_id,
                    last_run_config=last_run_config,
                )
                job.payload = lambda j=job: self._run_job_callback(j)
                jobs_to_submit.append(job)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to submit job %s: %s", getattr(record, "job_id", None), exc)
                if on_error:
                    on_error(exc)

        if not jobs_to_submit:
            return None
        submit_many = getattr(self._job_service, "submit_jobs_with_run_mode", None)
        if callable(submit_many):
            submit_many(jobs_to_submit, batch_queue_update=True)
        else:
            for job in jobs_to_submit:
                self._job_service.submit_job_with_run_mode(job)
        submitted_count = len(jobs_to_submit)
        return PipelinePreviewSubmissionResult(submitted_jobs=submitted_count, run_mode=run_mode)
