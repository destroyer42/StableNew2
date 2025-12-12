from __future__ import annotations

from typing import Optional

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.stage_models import StageType
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue


class DummyRunner:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def run_once(self, job: Job) -> dict[str, str]:
        return {}

    def cancel_current(self) -> None:
        pass


def _make_stage() -> StageConfig:
    return StageConfig(
        stage_type=StageType.TXT2IMG,
        enabled=True,
        steps=20,
        cfg_scale=7.0,
        sampler_name="Euler a",
    )


def _make_record(prompt_source: str, prompt_pack_id: Optional[str]) -> NormalizedJobRecord:
    stage = _make_stage()
    record = NormalizedJobRecord(
        job_id="record",
        config={"prompt": "test"},
        path_output_dir="output",
        filename_template="{seed}",
        stage_chain=[stage],
        randomizer_summary=None,
    )
    record.positive_prompt = "test"
    record.prompt_source = prompt_source
    record.prompt_pack_id = prompt_pack_id or ""
    return record



def _make_job(record: NormalizedJobRecord, prompt_source: str, prompt_pack_id: Optional[str]) -> Job:
    job = Job(
        job_id="job",
        priority=JobPriority.NORMAL,
        run_mode="queue",
        source="gui",
        prompt_source=prompt_source,
        prompt_pack_id=prompt_pack_id,
    )
    job._normalized_record = record
    return job


@pytest.fixture
def service() -> JobService:
    queue = JobQueue()
    runner = DummyRunner()
    return JobService(queue, runner)


def test_pack_job_missing_prompt_pack_id_raises(service: JobService) -> None:
    record = _make_record(prompt_source="pack", prompt_pack_id=None)
    job = _make_job(record, prompt_source="pack", prompt_pack_id=None)
    service._prepare_job_for_submission(job)
    assert job.status == JobStatus.FAILED
    assert job.result and job.result.get("code") == "pack_required"


def test_manual_job_missing_prompt_pack_id_allowed(service: JobService) -> None:
    record = _make_record(prompt_source="manual", prompt_pack_id=None)
    job = _make_job(record, prompt_source="manual", prompt_pack_id=None)
    service._prepare_job_for_submission(job)
    assert job.status == JobStatus.FAILED
    assert job.result and job.result.get("code") == "pack_required"
