"""V1-6: the phone's ``continue_clip`` compile (the real builder, Storyboard service and job fakes).

No GPU, Comfy, FFmpeg or network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.app.site_media_files import SiteOutputError
from src.app.site_phone_continue import compile_continuation
from src.controller.storyboard_submission_service import StoryboardSubmissionService
from src.queue.job_model import JobStatus
from src.video.sequence_ledger import sha256_of
from src.video.storyboard_tree_store import StoryboardTreeStore
from tests.helpers.storyboard_380 import (
    REG,
    FakeRepository,
    builder,
    frames_out_job,
    refused_job,
    unsmoothed_mp4,
)


class _Repository(FakeRepository):
    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [
            SimpleNamespace(job_id=job.job_id, result=job.result)
            for job in reversed(list(self.jobs.values()))
            if not statuses or job.status in statuses
        ][:limit]


def _setup(tmp_path: Path) -> SimpleNamespace:
    source, job_id, frames = frames_out_job(tmp_path, count=17)
    repository = _Repository(jobs=dict(source.jobs), files=dict(source.files))
    submitted: list[Any] = []
    service = StoryboardSubmissionService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: SimpleNamespace(submit_njrs=lambda *a: pytest.fail("not the phone")),
        repository=lambda: repository,
        store=StoryboardTreeStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: 1,
    )
    clip = unsmoothed_mp4(source, job_id)
    return SimpleNamespace(
        service=service,
        repository=repository,
        job_id=job_id,
        frames=frames,
        clip=clip,
        digest=sha256_of(clip),
        submitted=submitted,
    )


def _no_video(*_args: Any) -> Any:
    raise AssertionError("a Storyboard take does not use Make Video")


def test_preparing_writes_and_queues_nothing(tmp_path: Path) -> None:
    env = _setup(tmp_path)

    compiled = compile_continuation(
        env.service, tmp_path, env.clip, env.digest, "she turns", 7, video=_no_video
    )

    assert compiled.build is not None and compiled.video is None
    assert compiled.lines[0] == "Continues from the clip's last frame, in a new Storyboard."
    assert "Prompt: she turns" in compiled.lines
    assert env.service.store.list_trees() == []
    assert not (tmp_path / "storyboards").exists()


def test_admission_builds_one_take_with_the_phones_seed(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    compiled = compile_continuation(
        env.service, tmp_path, env.clip, env.digest, "", 7, video=_no_video
    )

    def admit(njrs: list[Any]) -> list[str]:
        env.submitted.extend(njrs)
        return ["phone-1"]

    assert compiled.build is not None
    assert compiled.build(admit) == ["phone-1"]

    (njr,) = env.submitted
    stage = dict(njr.stage_chain[0].extra)
    # No words: the clip's own prompt. The source is its last generated frame.
    assert (stage["prompt"], stage["seed"], stage["frame_count"]) == ("the person waves", 7, 17)
    assert sha256_of(Path(njr.input_image_paths[0])) == sha256_of(env.frames[-1])
    ((storyboard_id, _title, _updated),) = env.service.store.list_trees()
    (take,) = env.service.store.load(storyboard_id).takes
    assert take.attempts == ("phone-1",)


def test_the_same_request_has_the_same_identity_and_new_words_change_it(tmp_path: Path) -> None:
    env = _setup(tmp_path)

    def compile_words(words: str, seed: int) -> Any:
        return compile_continuation(
            env.service, tmp_path, env.clip, env.digest, words, seed, video=_no_video
        )

    assert compile_words("a", 1).identity == compile_words("a", 2).identity
    assert compile_words("a", 1).identity != compile_words("b", 1).identity


def test_a_driving_video_clip_is_offered_as_a_video_of_its_last_frame(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    driven, driven_id = refused_job(tmp_path, "driving_video")
    env.repository.jobs.update(driven.jobs)
    result = env.repository.jobs.pop(env.job_id).result
    env.repository.jobs[driven_id].result = result
    env.repository.jobs[driven_id].status = JobStatus.COMPLETED
    calls: list[tuple[Any, ...]] = []
    preview = object()

    def video(*args: Any) -> tuple[Any, Any]:
        calls.append(args)
        spec = SimpleNamespace(display_name="Make Video", registry_key=("wf", "1"))
        return spec, preview

    compiled = compile_continuation(
        env.service, tmp_path, env.clip, env.digest, "on she goes", 9, video=video
    )

    assert compiled.video is preview and compiled.build is None
    assert compiled.lines[:2] == (
        "This clip's engine cannot continue in a Storyboard.",
        "Makes a new clip from its last frame instead.",
    )
    ((root, frame, digest, prompt, seed),) = calls
    assert (Path(frame), prompt, seed) == (env.frames[-1], "on she goes", 9)
    assert digest == sha256_of(env.frames[-1])


def test_a_file_no_job_recorded_is_refused(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    stray = tmp_path / "stray.mp4"
    stray.write_bytes(b"not recorded")

    with pytest.raises(SiteOutputError, match="provenance_unverified"):
        compile_continuation(
            env.service, tmp_path, stray, sha256_of(stray), "go", 1, video=_no_video
        )
