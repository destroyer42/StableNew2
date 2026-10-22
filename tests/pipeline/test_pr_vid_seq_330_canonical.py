"""PR-VID-SEQ-330-CORE on the canonical path with real state: JobService -> SQLite queue/repository -> run_njr.

A fake Comfy backend writes small real PNGs; the queue, repository, runner and controller are the production ones, over
a temporary SQLite file. No GPU, runtime or network is touched. FFmpeg-backed tests skip when FFmpeg is absent.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.submission_policy_v26 import SubmissionPolicy
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.video import VideoBackendRegistry
from src.video.sequence_ledger import read_ledger, verify_segment_files
from src.video.sequence_plan import SequencePlan
from src.video.sequence_resume import SequenceResumeError
from tests.pipeline.test_pr_vid_seq_330_runner import (
    FakeComfy,
    _form,
    _intent,
    _png,
    needs_ffmpeg,
)

TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class Stack:
    """The production queue stack over a temporary SQLite file, with a fake video backend."""

    def __init__(self, root: Path, backend: FakeComfy) -> None:
        self.root = root
        self.backend = backend
        self.repository = JobRepository(root / "state" / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.queue_runner = SingleNodeJobRunner(self.queue, run_callable=None, poll_interval=0.01)
        self.job_service = JobService(
            self.queue, runner=self.queue_runner, history_store=self.repository
        )
        registry = VideoBackendRegistry()
        registry.register(backend)
        runner = PipelineRunner(
            Mock(), Mock(), runs_base_dir=str(root / "runs"), video_backend_registry=registry
        )
        runner._pipeline = (
            SimpleNamespace()
        )  # no Mock: its attributes would not serialise into SQLite
        self.queue_runner.run_callable = PipelineController(
            pipeline_runner=runner, job_service=self.job_service
        )._run_job
        self.job_service.auto_run_enabled = True
        self.controller = VideoWorkflowController(
            app_controller=SimpleNamespace(
                job_service=self.job_service, output_dir=str(root / "output")
            )
        )

    def wait(self, job_id: str, timeout: float = 60.0) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.queue.get_job(job_id)
            if job is not None and job.status in TERMINAL:
                return job
            time.sleep(0.05)
        raise TimeoutError(f"job {job_id} did not finish")

    def close(self) -> None:
        self.job_service.stop()
        self.repository.close()


@pytest.fixture
def stack_factory(tmp_path: Path):
    stacks: list[Stack] = []

    def make(backend: FakeComfy) -> Stack:
        stack = Stack(tmp_path, backend)
        stacks.append(stack)
        return stack

    yield make
    for stack in stacks:
        stack.close()


def _submit(stack: Stack, tmp_path: Path, count: int = 4) -> str:
    source = _png(tmp_path / "source.png", 9)
    return stack.controller.submit_sequence_job(
        source_image_path=str(source), form_data=_form(), sequence_intent=_intent(count)
    )


@needs_ffmpeg
def test_a_failed_sequence_resumes_as_a_fresh_queued_job_over_real_sqlite_state(
    tmp_path: Path, stack_factory
) -> None:
    backend = FakeComfy(fail_on=2)
    stack = stack_factory(backend)

    parent_id = _submit(stack, tmp_path, count=4)
    parent = stack.wait(parent_id)

    # SQLite owns the lifecycle; the ledger is only evidence of how far the run got.
    assert parent.status == JobStatus.FAILED
    parent_njr = parent._normalized_record
    assert parent_njr is not None
    plan = SequencePlan.from_dict(dict(parent_njr.stage_chain[0].extra)["sequence_metadata"])
    pointer = parent.result["metadata"]["sequence_artifact"]
    ledger = read_ledger(Path(pointer["ledger_path"]), expected_sha256=pointer["ledger_sha256"])
    assert (ledger.job_id, ledger.plan_sha256) == (parent_id, plan.plan_sha256())
    assert (ledger.state, ledger.completed_prefix, ledger.next_segment) == ("failed", 2, 2)
    assert verify_segment_files(ledger.segments) == []
    parent_snapshot = parent_njr.to_queue_snapshot()
    assert [r["seed"] for r in backend.requests] == [
        100,
        101,
        102,
    ]  # segment 2 is where it fell over

    backend.fail_on = None  # the operator fixed whatever broke; nothing resumes by itself
    before = len(backend.requests)
    child_id = stack.controller.resume_sequence(parent_id, from_segment=2)
    child = stack.wait(child_id)

    assert child_id != parent_id and child.status == JobStatus.COMPLETED
    assert child._normalized_record.source.parent_job_id == parent_id
    block = dict(child._normalized_record.stage_chain[0].extra)["sequence_resume"]
    assert block["from_segment"] == 2 and block["plan_sha256"] == plan.plan_sha256()
    assert block["parent_ledger_sha256"] == pointer["ledger_sha256"]
    assert [r["seed"] for r in backend.requests[before:]] == [
        102,
        103,
    ]  # only the unfinished suffix
    assert backend.requests[before]["input_sha"] == ledger.segments[1].final_frame.file.sha256

    # The parent's immutable record and its checkpoint are untouched by the resume.
    assert stack.queue.get_job(parent_id)._normalized_record.to_queue_snapshot() == parent_snapshot
    assert read_ledger(Path(pointer["ledger_path"])).state == "failed"

    # The child no longer needs the parent's run folder once the prefix was copied.
    resumed = read_ledger(Path(child.result["metadata"]["sequence_artifact"]["ledger_path"]))
    assert [s.origin for s in resumed.segments] == ["reused", "reused", "generated", "generated"]
    assert resumed.parent["job_id"] == parent_id
    shutil.rmtree(Path(pointer["ledger_path"]).parent)
    assert verify_segment_files(resumed.segments) == []
    movie = Path(resumed.assembly["output_path"])
    assert movie.is_file() and resumed.assembly["total_frames"] == 17 + 16 + 16 + 16


def test_a_resume_that_cannot_be_verified_queues_nothing(tmp_path: Path, stack_factory) -> None:
    backend = FakeComfy(fail_on=2)
    stack = stack_factory(backend)
    parent_id = _submit(stack, tmp_path, count=3)
    parent = stack.wait(parent_id)
    pointer = parent.result["metadata"]["sequence_artifact"]
    ledger = read_ledger(Path(pointer["ledger_path"]))
    Path(ledger.segments[0].frames[0].path).write_bytes(b"tampered")
    queued_before = len(stack.queue.list_jobs())

    with pytest.raises(SequenceResumeError, match="changed since it was recorded"):
        stack.controller.resume_sequence(parent_id)
    with pytest.raises(SequenceResumeError, match="not a known sequence job"):
        stack.controller.resume_sequence("no-such-job")

    assert (
        len(stack.queue.list_jobs()) == queued_before
    )  # nothing was admitted; no silent full rerun
    assert len(backend.requests) == 3


@needs_ffmpeg
def test_a_full_replay_is_a_new_job_that_recomputes_everything_and_records_divergence(
    tmp_path: Path, stack_factory
) -> None:
    backend = FakeComfy()
    stack = stack_factory(backend)
    original_id = _submit(stack, tmp_path, count=3)
    original = stack.wait(original_id)
    assert original.status == JobStatus.COMPLETED
    original_ledger = read_ledger(
        Path(original.result["metadata"]["sequence_artifact"]["ledger_path"])
    )
    before = len(backend.requests)

    replay_id = stack.controller.replay_sequence(original_id)
    replay = stack.wait(replay_id)

    assert replay.status == JobStatus.COMPLETED and replay_id != original_id
    assert replay._normalized_record.source.parent_job_id == original_id
    extra = dict(replay._normalized_record.stage_chain[0].extra)
    assert "sequence_resume" not in extra  # a replay is never a resume
    assert len(backend.requests) - before == 3  # every segment was recomputed
    replayed = read_ledger(Path(replay.result["metadata"]["sequence_artifact"]["ledger_path"]))
    assert [s.origin for s in replayed.segments] == ["generated"] * 3
    assert replayed.replay["status"] == "comparing" and replayed.replay["compared_segments"] == [
        0,
        1,
        2,
    ]
    # The fake backend is deterministic, so every final frame is identical; a divergent one would be listed.
    assert replayed.replay["diverged_segments"] == []
    assert [s.final_frame.file.sha256 for s in replayed.segments] == [
        s.final_frame.file.sha256 for s in original_ledger.segments
    ]


@needs_ffmpeg
def test_a_replay_of_a_resumed_job_is_a_full_replay_not_a_second_resume(
    tmp_path: Path, stack_factory
) -> None:
    backend = FakeComfy(fail_on=1)
    stack = stack_factory(backend)
    parent_id = _submit(stack, tmp_path, count=3)
    stack.wait(parent_id)
    backend.fail_on = None
    child_id = stack.controller.resume_sequence(parent_id)
    assert stack.wait(child_id).status == JobStatus.COMPLETED
    before = len(backend.requests)

    replay_id = stack.controller.replay_sequence(child_id)
    replay = stack.wait(replay_id)

    assert replay.status == JobStatus.COMPLETED
    assert len(backend.requests) - before == 3  # nothing reused: the whole plan ran again
    assert "sequence_resume" not in dict(replay._normalized_record.stage_chain[0].extra)


def test_the_submission_goes_through_the_one_job_service_boundary(
    tmp_path: Path, stack_factory
) -> None:
    stack = stack_factory(FakeComfy())
    submitted: list[list[Any]] = []
    original = stack.job_service.submit_njrs

    def spy(njrs: Any, policy: SubmissionPolicy) -> Any:
        submitted.append(list(njrs))
        return original(njrs, policy)

    stack.job_service.submit_njrs = spy  # type: ignore[method-assign]
    job_id = _submit(stack, tmp_path, count=2)
    stack.wait(job_id)

    assert len(submitted) == 1 and len(submitted[0]) == 1  # one NJR, one submit, no nested job
    assert len([j for j in stack.queue.list_jobs() if j.job_id != job_id]) == 0


@needs_ffmpeg
def test_a_resume_submitted_during_a_gpu_loss_quarantine_waits_for_the_operator(
    tmp_path: Path, stack_factory
) -> None:
    backend = FakeComfy(fail_on=1)
    stack = stack_factory(backend)
    parent_id = _submit(stack, tmp_path, count=3)
    stack.wait(parent_id)
    backend.fail_on = None
    stack.queue.quarantine_gpu_dispatch({"incident_id": "gpu-loss-1", "reason": "device lost"})
    before = len(backend.requests)

    child_id = stack.controller.resume_sequence(parent_id)  # admitted like any job...
    time.sleep(0.6)

    assert stack.queue.get_job(child_id).status == JobStatus.QUEUED  # ...but never dispatched
    assert len(backend.requests) == before  # no automatic resume after a device loss

    assert (
        stack.queue.release_gpu_quarantine("gpu-loss-1") is True
    )  # the operator's explicit release
    child = stack.wait(child_id)
    assert child.status == JobStatus.COMPLETED and len(backend.requests) - before == 2
