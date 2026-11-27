"""RUN-LEAN: the queue projection's output, and what it costs per already-seen job."""

from __future__ import annotations

from types import SimpleNamespace

from src.controller.app_controller import AppController
from src.pipeline.job_models_v2 import UnifiedJobSummary
from src.queue.job_model import Job, JobStatus
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


def _job(job_id: str, prompt: str, status: JobStatus = JobStatus.QUEUED) -> Job:
    job = make_test_job_from_njr(make_test_njr(job_id=job_id, prompt=prompt))
    job.status = status
    return job


def _controller(jobs: list[Job]) -> SimpleNamespace:
    timings: list[dict[str, int]] = []
    return SimpleNamespace(
        _list_service_jobs=lambda: list(jobs),
        _record_queue_projection_timing=lambda **fields: timings.append(fields),
        timings=timings,
    )


def _project(controller: SimpleNamespace):
    return AppController._build_queue_projection(controller)


def test_projection_lists_each_job_with_its_prompt_preview_and_status() -> None:
    bare = Job(job_id="no-njr")
    controller = _controller([_job("a", "first prompt", JobStatus.RUNNING), _job("b", "second prompt"), bare])

    items, summaries = _project(controller)

    assert items == ["first prompt", "second prompt", "no-njr"]
    assert [(s.job_id, s.status) for s in summaries[:2]] == [("a", "RUNNING"), ("b", "QUEUED")]
    assert controller.timings[-1]["job_count"] == 3
    assert controller.timings[-1]["fallback_count"] == 1


def test_projection_follows_a_status_change_and_a_removed_job() -> None:
    jobs = [_job("a", "one"), _job("b", "two")]
    controller = _controller(jobs)
    _project(controller)

    jobs[0].status = JobStatus.RUNNING
    del jobs[1]
    items, summaries = _project(controller)

    assert items == ["one"]
    assert [(s.job_id, s.status) for s in summaries] == [("a", "RUNNING")]


def test_a_job_already_projected_is_not_converted_again(monkeypatch) -> None:
    converted: list[str] = []
    original = UnifiedJobSummary.from_normalized_record.__func__

    def counting(cls, record, **kwargs):
        converted.append(record.job_id)
        return original(cls, record, **kwargs)

    monkeypatch.setattr(UnifiedJobSummary, "from_normalized_record", classmethod(counting))
    jobs = [_job("a", "one"), _job("b", "two")]
    controller = _controller(jobs)

    _project(controller)
    jobs[0].status = JobStatus.RUNNING
    jobs.append(_job("c", "three"))
    _, summaries = _project(controller)

    assert converted == ["a", "b", "c"]
    assert [s.status for s in summaries] == ["RUNNING", "QUEUED", "QUEUED"]


def test_a_replaced_record_under_the_same_job_id_is_converted_again() -> None:
    jobs = [_job("a", "before")]
    controller = _controller(jobs)
    _project(controller)

    jobs[0] = _job("a", "after")
    items, _ = _project(controller)

    assert items == ["after"]
