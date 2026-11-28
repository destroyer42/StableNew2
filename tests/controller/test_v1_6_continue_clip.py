"""V1-6: the continue-a-clip facade over the Storyboard service (the real builder, registry and tree store).

Jobs and files are the PR-VID-STORY-380 fakes: small real PNGs, placeholder clips, a recording job service. Nothing
starts Comfy, FFmpeg or a GPU.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.continue_clip import (
    ContinueRefused,
    continue_clip,
    find_clip_in_storyboards,
    inspect_continuation,
)
from src.controller.storyboard_submission_service import (
    ContinueRequest,
    ContinueRow,
    StoryboardSubmissionService,
)
from src.queue.job_model import JobStatus
from src.video.motion_intent import compose_prompt
from src.video.sequence_ledger import sha256_of
from src.video.sequence_plan import ROOT_PARENT
from src.video.storyboard_root import StoryboardRootError, clip_last_frame
from src.video.storyboard_tree_store import StoryboardTreeStore
from tests.helpers.storyboard_380 import (
    REG,
    FakeDecoder,
    FakeRepository,
    builder,
    frames_out_job,
    refused_job,
)


class _Jobs:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.njrs: list[Any] = []

    def submit_njrs(self, njrs: list[Any], policy: Any) -> list[str]:
        self.njrs.extend(njrs)
        return [self.repository.add(njr, status=JobStatus.QUEUED) for njr in njrs]


class _Repository(FakeRepository):
    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [SimpleNamespace(job_id=job_id) for job_id in reversed(list(self.jobs))][:limit]


def _service(tmp_path: Path, source: FakeRepository) -> tuple[StoryboardSubmissionService, _Jobs]:
    repository = _Repository(jobs=dict(source.jobs), files=dict(source.files))
    jobs = _Jobs(repository)
    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: jobs,
        repository=lambda: repository,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: 4242,
    )
    return service, jobs


def _stage(njr: Any) -> dict[str, Any]:
    return dict(njr.stage_chain[0].extra)


def test_inspect_reads_the_clip_and_writes_nothing(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=81)
    service, jobs = _service(tmp_path, repo)

    clip = inspect_continuation(service, job_id)

    assert clip.takes_storyboard and not clip.storyboard_id
    assert (clip.prompt, clip.frame_count, clip.policy.fps) == ("the person waves", 81, 16)
    assert clip.frame_paths == tuple(str(frame) for frame in frames)
    assert service.store.list_trees() == [] and jobs.njrs == []
    assert not (tmp_path / "storyboards").exists()


def test_continue_queues_one_take_from_the_last_generated_frame(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=81, smoothed_fps=32)
    service, jobs = _service(tmp_path, repo)
    clip = inspect_continuation(service, job_id)

    result = continue_clip(
        service, clip, prompt="she sits down", motion_phrase="slow movement", frame_count=49
    )

    (njr,) = jobs.njrs
    stage = _stage(njr)
    assert result.job_ids == (njr.job_id,)
    assert stage["prompt"] == compose_prompt("she sits down", "slow movement")
    assert (stage["frame_count"], stage["seed"]) == (49, 4242)
    assert stage["negative_prompt"] == "blurry, watermark"
    # The source is the clip's last generated frame, byte for byte (not the thumbnail, frame 1).
    assert sha256_of(Path(njr.input_image_paths[0])) == sha256_of(frames[-1])
    (take,) = result.tree.takes
    assert (take.parent_id, take.handoff_index, take.attempts) == (ROOT_PARENT, 80, (njr.job_id,))
    assert result.tree.root.job_id == job_id


def test_an_earlier_frame_can_be_chosen(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=17)
    service, jobs = _service(tmp_path, repo)

    continue_clip(service, inspect_continuation(service, job_id), prompt="turns", frame_index=4)

    assert sha256_of(Path(jobs.njrs[0].input_image_paths[0])) == sha256_of(frames[4])


def test_the_facade_builds_the_same_job_as_the_storyboard_tab(tmp_path: Path) -> None:
    repo, job_id, _frames = frames_out_job(tmp_path, count=17)
    service, jobs = _service(tmp_path, repo)
    first = continue_clip(
        service, inspect_continuation(service, job_id), prompt="walks on", seed="9"
    )

    service.submit(
        ContinueRequest(
            storyboard_id=first.tree.storyboard_id,
            expected_revision=first.tree.revision,
            parent_id=ROOT_PARENT,
            handoff_index=16,
            mode="sequential",
            rows=(ContinueRow(prompt="walks on", negative_prompt="", seed="9"),),
        )
    )

    mine, tab = (_stage(njr) for njr in jobs.njrs)
    differs = {key for key in mine.keys() | tab.keys() if mine.get(key) != tab.get(key)}
    # Only what names this particular take (its ids, its lead-in copy) may differ.
    assert differs <= {"sequence_metadata", "source_preparation", "video_execution"}, differs
    own = {"sequence_id", "storyboard"}
    plans = [
        {key: value for key, value in dict(stage["sequence_metadata"]).items() if key not in own}
        for stage in (mine, tab)
    ]
    assert plans[0]["segments"][0]["frame_count"] == plans[1]["segments"][0]["frame_count"] == 17
    assert [segment["prompt"] for segment in plans[0]["segments"]] == ["walks on"]
    assert plans[0]["segments"][0]["seed"] == plans[1]["segments"][0]["seed"] == 9


def test_a_clip_already_in_a_storyboard_extends_it(tmp_path: Path) -> None:
    repo, job_id, _frames = frames_out_job(tmp_path, count=17)
    service, jobs = _service(tmp_path, repo)
    first = continue_clip(service, inspect_continuation(service, job_id), prompt="one")

    again = inspect_continuation(service, job_id)
    second = continue_clip(service, again, prompt="two")

    assert again.storyboard_id == first.tree.storyboard_id and again.parent_id == ROOT_PARENT
    assert second.tree.storyboard_id == first.tree.storyboard_id
    assert len(service.store.list_trees()) == 1 and len(second.tree.takes) == 2
    # A take's own job continues that take, not a new Storyboard.
    found = find_clip_in_storyboards(service, jobs.njrs[0].job_id)
    assert found is not None and found[1] == first.take_ids[0]


def test_a_driving_video_clip_cannot_be_a_storyboard_take(tmp_path: Path) -> None:
    repo, job_id = refused_job(tmp_path, "driving_video")
    service, jobs = _service(tmp_path, repo)

    clip = inspect_continuation(service, job_id)

    assert not clip.takes_storyboard and "driving video" in clip.reason
    with pytest.raises(ContinueRefused, match="driving video"):
        continue_clip(service, clip, prompt="on")
    assert service.store.list_trees() == [] and jobs.njrs == []


@pytest.mark.parametrize("kind", ["svd", "not_completed"])
def test_a_job_that_is_not_a_finished_video_workflow_clip_is_refused(
    tmp_path: Path, kind: str
) -> None:
    repo, job_id = refused_job(tmp_path, kind)
    service, _jobs = _service(tmp_path, repo)

    with pytest.raises(ContinueRefused):
        inspect_continuation(service, job_id)


def test_another_surfaces_admission_replaces_the_submit_call(tmp_path: Path) -> None:
    repo, job_id, _frames = frames_out_job(tmp_path, count=17)
    service, jobs = _service(tmp_path, repo)
    seen: list[Any] = []

    def admit(njrs: list[Any]) -> list[str]:
        seen.extend(njrs)
        return ["phone-job-1"]

    result = continue_clip(
        service, inspect_continuation(service, job_id), prompt="waves", admit=admit
    )

    assert len(seen) == 1 and jobs.njrs == []
    assert result.job_ids == ("phone-job-1",) and result.tree.takes[0].attempts == ("phone-job-1",)


def test_a_refused_admission_leaves_no_take(tmp_path: Path) -> None:
    repo, job_id, _frames = frames_out_job(tmp_path, count=17)
    service, _jobs = _service(tmp_path, repo)

    def refuse(njrs: list[Any]) -> list[str]:
        raise RuntimeError("admission_refused")

    with pytest.raises(RuntimeError):
        continue_clip(service, inspect_continuation(service, job_id), prompt="waves", admit=refuse)

    ((storyboard_id, _title, _updated),) = service.store.list_trees()
    assert service.store.load(storyboard_id).takes == ()


def test_last_frame_is_the_recorded_frame_else_decoded_from_the_clip(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=17)
    assert clip_last_frame(repo, job_id, tmp_path / "unused") == str(frames[-1])

    frames[-1].unlink()  # frame retention removed it: decode the clip instead
    decoder = FakeDecoder(count=17)
    target = clip_last_frame(repo, job_id, tmp_path / "continue", decode_clip=decoder)

    assert Path(target) == tmp_path / "continue" / "last_frame.png" and Path(target).is_file()
    assert decoder.calls == 1
    assert [path.name for path in (tmp_path / "continue").iterdir()] == ["last_frame.png"]


def test_last_frame_refuses_a_missing_clip(tmp_path: Path) -> None:
    repo, job_id, frames = frames_out_job(tmp_path, count=17)
    frames[-1].unlink()
    repo.files[job_id]["unsmoothed"].unlink()

    with pytest.raises(StoryboardRootError, match="missing"):
        clip_last_frame(repo, job_id, tmp_path / "continue", decode_clip=FakeDecoder(count=17))
