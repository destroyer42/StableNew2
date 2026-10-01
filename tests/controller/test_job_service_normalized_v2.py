from __future__ import annotations

import uuid
from collections.abc import Mapping

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.stub_runner import StubRunner
from src.utils.snapshot_builder_v2 import build_job_snapshot
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def _make_normalized_record() -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id=str(uuid.uuid4()),
        config={"prompt": "test", "model": "sdxl", "steps": 20},
        positive_prompt="(<embedding:test>) test prompt",
        negative_prompt="neg: bad anatomy",
        positive_embeddings=["test"],
        negative_embeddings=["bad_anatomy"],
        stage_chain=[make_stage_config("txt2img", steps=20, cfg_scale=7.5)],
        prompt_pack_id="core-pack",
        prompt_pack_name="Core Pack",
        prompt_pack_row_index=0,
        seed=1234,
    )


def _build_job_with_snapshot(
    record: NormalizedJobRecord, *, run_config: Mapping[str, object] | None = None
) -> Job:
    job = Job(job_id=record.job_id, run_mode="queue", prompt_pack_id=record.prompt_pack_id)
    job.snapshot = build_job_snapshot(job, record, run_config=run_config)
    return job


class TestJobServiceNormalizedEnforcement:
    def test_requires_normalized_snapshot_before_submission(self) -> None:
        queue = JobQueue()
        runner = StubRunner(queue)
        service = JobService(queue, runner, require_normalized_records=True)

        job = Job(job_id="missing-normalized", run_mode="queue")

        with pytest.raises(ValueError):
            service.submit_job_with_run_mode(job)

    def test_accepts_normalized_record_when_present(self) -> None:
        queue = JobQueue()
        runner = StubRunner(queue)
        service = JobService(queue, runner, require_normalized_records=True)

        record = _make_normalized_record()
        job = _build_job_with_snapshot(record, run_config={"run_mode": "queue"})

        service.submit_job_with_run_mode(job)

        queued = queue.list_jobs()
        assert any(queued_job.job_id == job.job_id for queued_job in queued)
        assert getattr(job, "unified_summary", None) is not None
