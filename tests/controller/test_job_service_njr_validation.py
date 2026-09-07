from __future__ import annotations

import pytest

from src.controller.job_service import JobService
from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    SourceDescriptor,
    SourceKind,
    StageConfig,
)
from src.pipeline.stage_models import StageType
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from tests.helpers.njr_factory import make_pipeline_njr


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


def _make_record(prompt_source: str, prompt_pack_id: str | None) -> NormalizedJobRecord:
    source_kind = {
        "pack": SourceKind.PROMPT_PACK,
        "reprocess": SourceKind.REPROCESS,
    }.get(prompt_source, SourceKind.CLI)
    return make_pipeline_njr(
        job_id="record",
        config={"prompt": "test"},
        positive_prompt="test",
        stage_chain=[_make_stage()],
        source_kind=source_kind.value,
        prompt_pack_id=prompt_pack_id,
    )


def _make_job(record: NormalizedJobRecord, prompt_source: str, prompt_pack_id: str | None) -> Job:
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


def test_pack_job_missing_prompt_pack_id_is_unconstructable(service: JobService) -> None:
    del service
    with pytest.raises(ValueError, match="requires source.id"):
        SourceDescriptor(kind=SourceKind.PROMPT_PACK)


def test_manual_job_missing_prompt_pack_id_allowed(service: JobService) -> None:
    record = _make_record(prompt_source="manual", prompt_pack_id=None)
    job = _make_job(record, prompt_source="manual", prompt_pack_id=None)
    service._prepare_job_for_submission(job)
    assert job.status == JobStatus.QUEUED
    assert job.result is None


def test_job_from_njr_preserves_reprocess_source_and_prompt_source(service: JobService) -> None:
    record = make_pipeline_njr(
        job_id="record",
        source_kind=SourceKind.REPROCESS.value,
        extra_metadata={
            "submission_source": "review_tab",
            "reprocess": {"source": "review_tab"},
        },
    )
    job = service._job_from_njr(
        record,
        run_request=type(
            "Req",
            (),
            {
                "run_mode": type("Mode", (), {"value": "queue"})(),
                "source": type("Source", (), {"value": "add_to_queue"})(),
                "prompt_pack_id": "reprocess_pack",
            },
        )(),
    )

    assert job.source == "review_tab"
    assert job.prompt_source == "reprocess"
    assert job.snapshot["run_config"]["prompt_source"] == "reprocess"
