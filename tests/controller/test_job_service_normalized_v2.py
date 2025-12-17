from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.queue.job_model import Job
from src.queue.job_queue import JobQueue
from src.queue.stub_runner import StubRunner
from src.utils.snapshot_builder_v2 import build_job_snapshot


def _make_normalized_record() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=str(uuid.uuid4()),
        config={"prompt": "test", "model": "sdxl", "steps": 20},
        path_output_dir="output",
        filename_template="{seed}",
        seed=1234,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=time.time(),
        prompt_pack_id="core-pack",
        prompt_pack_name="Core Pack",
        prompt_pack_row_index=0,
        positive_prompt="(<embedding:test>) test prompt",
        negative_prompt="neg: bad anatomy",
        positive_embeddings=["test"],
        negative_embeddings=["bad_anatomy"],
        lora_tags=[],
        matrix_slot_values={},
        steps=20,
        cfg_scale=7.5,
        width=512,
        height=512,
        sampler_name="Euler a",
        scheduler="ddim",
        base_model="sdxl",
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
        ],
        loop_type="pipeline",
        loop_count=1,
        images_per_prompt=1,
        run_mode="QUEUE",
        queue_source="ADD_TO_QUEUE",
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
