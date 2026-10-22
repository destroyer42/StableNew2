"""PR-VID-SEQ-331A on the canonical path with real SQLite state (fake Comfy backend; no GPU, runtime or network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.gui.view_contracts.movie_clips_contract import extract_source_paths_from_bundle
from src.queue.job_model import JobStatus
from src.video.sequence_history import sequence_history_info
from src.video.sequence_ledger import LEDGER_FILE_NAME
from src.video.sequence_resume import SequenceResumeError
from src.video.video_artifact_helpers import video_bundle_from_result
from tests.pipeline.test_pr_vid_seq_330_canonical import (  # noqa: F401
    Stack,
    _submit,
    stack_factory,
)
from tests.pipeline.test_pr_vid_seq_330_runner import FakeComfy, needs_ffmpeg


@needs_ffmpeg
def test_send_to_movie_clips_from_recent_outputs_loads_the_assembled_movie_once(
    tmp_path: Path,
    stack_factory,  # noqa: F811
) -> None:
    stack = stack_factory(FakeComfy())
    job = stack.wait(_submit(stack, tmp_path, count=3))
    assert job.status == JobStatus.COMPLETED

    # Recent outputs hands Movie Clips the bundle the result recorded...
    recorded = video_bundle_from_result(job.result)
    # ...and Job History builds its own from the same result; the two must agree.
    history = AppController._get_history_video_bundle(
        object.__new__(AppController), SimpleNamespace(result=job.result)
    )

    assert recorded is not None and history is not None
    movie = Path(recorded["primary_path"])
    assert movie.name == "walk.mp4" and movie.is_file()
    assert extract_source_paths_from_bundle(recorded) == [str(movie)]
    assert extract_source_paths_from_bundle(history) == [str(movie)]
    # The per-segment clips are still recorded, apart from the bundle a consumer plays.
    sequence = job.result["metadata"]["sequence_artifact"]
    assert len(sequence["all_output_paths"]) == 4


@needs_ffmpeg
def test_history_reads_progress_and_actions_from_a_stored_sequence_job(
    tmp_path: Path,
    stack_factory,  # noqa: F811
) -> None:
    backend = FakeComfy(fail_on=2)
    stack = stack_factory(backend)
    parent_id = _submit(stack, tmp_path, count=4)
    parent = stack.wait(parent_id)
    entry = next(e for e in stack.repository.list_recent_jobs(limit=10) if e.job_id == parent_id)

    info = sequence_history_info(entry.snapshot, entry.result, entry.status)

    assert parent.status == JobStatus.FAILED and info is not None
    assert (info.total_segments, info.completed_segments) == (4, 2)
    assert info.can_resume and info.can_replay and info.ledger_path
    assert info.ledger_path.endswith(LEDGER_FILE_NAME)
    assert stack.controller.sequence_job_progress(parent_id) == (2, 4, "failed")


@needs_ffmpeg
def test_a_job_that_recorded_no_ledger_is_resumed_from_the_ledger_found_by_its_job_id(
    tmp_path: Path,
    stack_factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeComfy(fail_on=2)
    stack = stack_factory(backend)
    parent_id = _submit(stack, tmp_path, count=3)
    stack.wait(parent_id)
    backend.fail_on = None
    before = len(backend.requests)
    # A cancelled job records no result, so nothing points at its checkpoint.
    monkeypatch.setattr(
        "src.controller.video_sequence_controller.find_ledger_path", lambda _r: None
    )

    assert stack.controller.sequence_job_progress(parent_id) == (2, 3, "failed")
    child_id = stack.controller.resume_sequence(parent_id)
    child = stack.wait(child_id)

    assert child.status == JobStatus.COMPLETED and child_id != parent_id
    assert len(backend.requests) - before == 1  # only the unfinished segment ran


def test_a_job_with_no_recorded_ledger_and_none_on_disk_is_refused_with_the_manual_route(
    tmp_path: Path,
    stack_factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = stack_factory(FakeComfy(fail_on=1))
    parent_id = _submit(stack, tmp_path, count=2)
    stack.wait(parent_id)
    monkeypatch.setattr(
        "src.controller.video_sequence_controller.find_ledger_path", lambda _r: None
    )
    monkeypatch.setattr("src.controller.video_sequence_controller.locate_ledger", lambda *_a: None)
    queued = len(stack.queue.list_jobs())

    with pytest.raises(SequenceResumeError, match="sequence_state.json"):
        stack.controller.resume_sequence(parent_id)
    assert stack.controller.sequence_job_progress(parent_id) is None
    assert len(stack.queue.list_jobs()) == queued
