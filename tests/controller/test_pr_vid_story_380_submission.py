"""PR-VID-STORY-380: the storyboard submission service (create, preview, submit, reconcile) and the History refusal.

The service runs over the real NJR builder, workflow registry and storyboard store (under ``tmp_path``). The job
service is a recording fake: ``submit_njrs`` records each batch's size and puts the NJRs in a fake repository that
serves them back (``get_job_model``, ``list_recent_jobs``). Frames are small real PNGs; nothing starts Comfy, FFmpeg or
a GPU.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.storyboard_submission_service import (
    ContinueRequest,
    ContinueRow,
    StoryboardSubmissionService,
)
from src.controller.video_workflow_controller import VideoWorkflowController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from src.video.sequence_ledger import BASIS_NATIVE, FileRecord
from src.video.sequence_plan import (
    ROOT_PARENT,
    SEQUENCE_POLICY_VERSION_V2,
    SequencePlan,
    SequencePlanError,
    StoryboardLeadIn,
)
from src.video.sequence_resume import REPLAY_KEY, RESUME_KEY
from src.video.storyboard import StoryboardError
from src.video.storyboard_cut import (
    CutManifestError,
    read_cut_manifest,
    take_manifest,
    write_cut_manifest,
)
from src.video.storyboard_history import from_history
from src.video.storyboard_tree import StoryboardTree, StoryboardTreeError, Take
from src.video.storyboard_tree_store import MAX_BYTES, StoryboardTreeStore
from tests.helpers.storyboard_380 import (
    A14B_SIZE,
    REG,
    FakeJob,
    FakeRepository,
    builder,
    frames_out_job,
    png,
    run_dir,
    take_job,
)

# --------------------------------------------------------------------------------------------- fakes


class RecordingRepository(FakeRepository):
    """``FakeRepository`` plus the newest-first ``list_recent_jobs`` that reconciliation reads."""

    def list_recent_jobs(self, *, limit: int = 50, statuses: Any = None) -> list[Any]:
        return [SimpleNamespace(job_id=job_id) for job_id in reversed(list(self.jobs))][:limit]

    def merge(self, other: FakeRepository) -> None:
        self.jobs.update(other.jobs)
        self.files.update(other.files)

    def _directed(self, job_id: str, key: str, block: dict[str, Any]) -> str:
        parent = self.jobs[job_id]._normalized_record
        assert parent is not None
        child = compile_replay_intent(
            ReplayIntent(record=parent, run_directives={"video_workflow": {key: block}})
        )
        return self.add(child, status=JobStatus.QUEUED)

    def add_resume_of(self, job_id: str) -> str:
        block = {
            "parent_job_id": job_id,
            "parent_ledger_path": "sequence_state.json",
            "parent_ledger_sha256": "0" * 64,
            "plan_sha256": "0" * 64,
            "from_segment": 0,
        }
        return self._directed(job_id, RESUME_KEY, block)

    def add_replay_of(self, job_id: str) -> str:
        block = {
            "parent_job_id": job_id,
            "parent_ledger_path": "sequence_state.json",
            "parent_ledger_sha256": "0" * 64,
        }
        return self._directed(job_id, REPLAY_KEY, block)


class RecordingJobService:
    def __init__(self, repository: RecordingRepository) -> None:
        self.repository = repository
        self.calls: list[int] = []
        self.njrs: list[NormalizedJobRecord] = []

    def submit_njrs(self, njrs: list[NormalizedJobRecord], policy: Any) -> list[str]:
        self.calls.append(len(njrs))
        self.njrs.extend(njrs)
        return [self.repository.add(njr, status=JobStatus.QUEUED) for njr in njrs]


class FlakyStore(StoryboardTreeStore):
    """``fail_next_save_after = n``: the next ``n`` saves succeed, then one fails (a simulated stop)."""

    fail_next_save_after: int | None = None

    def save(self, tree: StoryboardTree) -> StoryboardTree:
        if self.fail_next_save_after is not None:
            if self.fail_next_save_after == 0:
                self.fail_next_save_after = None
                raise StoryboardTreeError("simulated stop before the attempts were recorded")
            self.fail_next_save_after -= 1
        return super().save(tree)


class RecordingService(StoryboardSubmissionService):
    fail_build_on_row: int | None = None
    fake_repository: RecordingRepository
    fake_job_service: RecordingJobService

    def _admit(self, position: int, **kwargs: Any) -> Any:
        if self.fail_build_on_row is not None and position == self.fail_build_on_row - 1:
            raise SequencePlanError(f"row {self.fail_build_on_row} refused by the test")
        return super()._admit(position, **kwargs)

    @property
    def job_service_calls(self) -> list[int]:
        return self.fake_job_service.calls


def _seed_draws() -> Iterator[int]:
    """Duplicates first, so the batch must redraw to keep sibling seeds distinct."""

    yield from (5, 5, 6, 6, 5, 7)
    yield from range(100, 100_000)


@pytest.fixture
def service(tmp_path: Path) -> RecordingService:
    repository = RecordingRepository()
    job_service = RecordingJobService(repository)
    draws = _seed_draws()
    built = RecordingService(
        njr_builder=builder(tmp_path),
        workflow_registry=REG,
        job_service=lambda: job_service,
        repository=lambda: repository,
        store=FlakyStore(tmp_path / "trees"),
        output_root=lambda: str(tmp_path),
        draw_seed=lambda: next(draws),
    )
    built.fake_repository = repository
    built.fake_job_service = job_service
    return built


@pytest.fixture
def tree_with_clip_root(service: RecordingService, tmp_path: Path) -> StoryboardTree:
    repo, job_id, _frames = frames_out_job(tmp_path, count=81)
    service.fake_repository.merge(repo)
    return service.create_from_clip(job_id, "Scene")


# --------------------------------------------------------------------------------------------- helpers


def _request(
    tree: StoryboardTree,
    *,
    rows: int = 1,
    mode: str = "parallel",
    handoff_index: int | None = 77,
    parent_id: str = ROOT_PARENT,
    prompts: tuple[str, ...] | None = None,
) -> ContinueRequest:
    texts = prompts or tuple(f"row {n} moves on" for n in range(1, rows + 1))
    return ContinueRequest(
        storyboard_id=tree.storyboard_id,
        expected_revision=tree.revision,
        parent_id=parent_id,
        handoff_index=handoff_index,
        mode=mode,  # type: ignore[arg-type]
        rows=tuple(ContinueRow(prompt=text, negative_prompt="", seed="") for text in texts),
    )


def _plan(njr: NormalizedJobRecord) -> SequencePlan:
    return SequencePlan.from_dict(dict(njr.stage_chain[0].extra)["sequence_metadata"])


def _seeds(service: RecordingService) -> list[int]:
    return [s.seed for njr in service.fake_job_service.njrs for s in _plan(njr).segments]


def _lead_in_of_last_njr(service: RecordingService) -> StoryboardLeadIn:
    link = _plan(service.fake_job_service.njrs[-1]).storyboard
    assert link is not None and link.lead_in is not None
    return link.lead_in


def _root_frame(tree: StoryboardTree, index: int) -> Path:
    manifest = read_cut_manifest(tree.root.manifest_path, expected_sha256=tree.root.manifest_sha256)
    return Path(manifest.frames[index].path)


def _move_to_archive(path: Path) -> None:
    archive = path.parent.parent / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(archive / path.name))


def _take(tree: StoryboardTree, prompt: str) -> Take:
    return next(t for t in tree.takes if t.prompt == prompt and t.replay_of is None)


def _chain_take(tree: StoryboardTree, *, position: int) -> Take:
    return next(t for t in tree.takes if t.mode == "sequential" and t.chain_position == position)


def _set_status(
    service: RecordingService, job_id: str, status: JobStatus, result: Any = None
) -> None:
    job = service.fake_repository.jobs[job_id]
    service.fake_repository.jobs[job_id] = replace(job, status=status, result=result)


# --------------------------------------------------------------------------------------------- trees


@pytest.fixture
def near_cap_tree(service: RecordingService, tree_with_clip_root: StoryboardTree) -> StoryboardTree:
    """The clip tree padded with takes until fewer than 1,000 bytes are left under the 2 MB cap."""

    tree = tree_with_clip_root

    def size(candidate: StoryboardTree) -> int:
        return len(json.dumps(candidate.to_dict(), indent=2).encode("utf-8"))

    def padding(number: int, length: int) -> Take:
        return Take.from_dict(
            {
                "take_id": f"pad{number}",
                "parent_id": ROOT_PARENT,
                "handoff_index": 0,
                "mode": "parallel",
                "batch_id": "padding",
                "chain_position": 0,
                "segment_index": 0,
                "prompt": "x" * length,
                "negative_prompt": "",
                "seed_intent": "",
                "attempts": [],
                "replay_of": None,
                "mark": "dropped",
                "created_at": tree.created_at,
            }
        )

    number = 0
    while size(tree) + 61_000 < MAX_BYTES:
        tree = tree.with_take(padding(number, 60_000))
        number += 1
    room = MAX_BYTES - size(tree.with_take(padding(number, 0))) - 600
    tree = tree.with_take(padding(number, room))
    assert MAX_BYTES - 1_000 < size(tree) <= MAX_BYTES
    return service.store.save(tree)


@pytest.fixture
def tree_with_finished_chain(
    service: RecordingService, tree_with_clip_root: StoryboardTree, tmp_path: Path
) -> StoryboardTree:
    """A completed three-row chain from root frame 81: its cut is 81 lead-in frames plus 80 per take."""

    result = service.submit(
        _request(tree_with_clip_root, rows=3, mode="sequential", handoff_index=80)
    )
    job_id = result.job_ids[0]
    plan = _plan(service.fake_job_service.njrs[-1])
    assert plan.storyboard is not None and plan.storyboard.lead_in is not None
    lead_in = read_cut_manifest(
        plan.storyboard.lead_in.manifest_path,
        expected_sha256=plan.storyboard.lead_in.manifest_sha256,
    )
    folder = run_dir(tmp_path, job_id)
    segments = []
    for spec, take_id in zip(plan.segments, plan.storyboard.take_ids, strict=True):
        records = tuple(
            FileRecord.of(
                png(folder / f"seg{spec.index}_{n:05d}_.png", A14B_SIZE, (spec.index * 60, n, 30))
            )
            for n in range(spec.frame_count)
        )
        segments.append((take_id, records, spec.overlap_frames, BASIS_NATIVE))
    cut = take_manifest(
        lead_in=lead_in,
        segments=segments,
        fps=plan.fps,
        width=A14B_SIZE[0],
        height=A14B_SIZE[1],
        job_id=job_id,
    )
    written = write_cut_manifest(folder / "storyboard_cut.json", cut)
    reference = {"path": written.path, "sha256": written.sha256}
    _set_status(
        service,
        job_id,
        JobStatus.COMPLETED,
        {"metadata": {"sequence_artifact": {"cut_manifest": reference}}},
    )
    return result.tree


@pytest.fixture
def tree_with_failed_and_completed_takes(
    service: RecordingService, tree_with_clip_root: StoryboardTree
) -> StoryboardTree:
    result = service.submit(_request(tree_with_clip_root, rows=2, prompts=("failed", "completed")))
    _set_status(service, _take(result.tree, "failed").attempts[0], JobStatus.FAILED)
    _set_status(service, _take(result.tree, "completed").attempts[0], JobStatus.COMPLETED)
    return result.tree


@pytest.fixture
def v2_job_repository(tmp_path: Path) -> FakeRepository:
    repo, job_id, _frames = take_job(tmp_path, segments=2)
    job = repo.jobs.pop(job_id)
    assert job._normalized_record is not None
    njr = replace(job._normalized_record, job_id="job-v2")
    repo.jobs["job-v2"] = FakeJob("job-v2", job.status, job.result, njr)
    return repo


# --------------------------------------------------------------------------------------------- submit


def test_parallel_submit_is_one_call_all_or_none(service, tree_with_clip_root):
    result = service.submit(
        _request(tree_with_clip_root, rows=3, mode="parallel", handoff_index=77)
    )
    assert service.job_service_calls == [3]  # one submit_njrs call carrying three NJRs
    assert len(result.job_ids) == 3 and len(set(_seeds(service))) == 3
    assert all(t.attempts for t in result.tree.takes)
    assert [t.attempts[0] for t in result.tree.takes] == list(result.job_ids)
    plans = [_plan(njr) for njr in service.fake_job_service.njrs]
    assert all(p.policy_version == SEQUENCE_POLICY_VERSION_V2 for p in plans)
    assert [p.storyboard.take_ids for p in plans] == [(t,) for t in result.take_ids]
    lead_in = _lead_in_of_last_njr(service)
    assert lead_in.frame_count == 78
    assert Path(lead_in.manifest_path).parent.name == "leadins"
    assert lead_in.handoff_path == str(_root_frame(tree_with_clip_root, 77).resolve())


def test_admission_failure_queues_nothing_and_removes_pending(service, tree_with_clip_root):
    service.fail_build_on_row = 2
    with pytest.raises(SequencePlanError):
        service.submit(_request(tree_with_clip_root, rows=3, mode="parallel", handoff_index=77))
    assert (
        service.job_service_calls == []
        and service.store.load(tree_with_clip_root.storyboard_id).takes == ()
    )


def test_stale_revision_is_refused_before_submission(service, tree_with_clip_root):
    with pytest.raises(StoryboardTreeError, match="Revision conflict"):
        service.submit(replace(_request(tree_with_clip_root, rows=1), expected_revision=0))
    assert service.job_service_calls == []


def test_oversize_storyboard_refuses_before_submission(service, near_cap_tree):
    with pytest.raises(StoryboardTreeError, match="exceeds the 2 MB limit"):
        service.submit(_request(near_cap_tree, rows=6))
    assert service.job_service_calls == []
    assert service.store.load(near_cap_tree.storyboard_id) == near_cap_tree


def test_submit_refuses_when_a_lead_in_frame_was_moved(service, tree_with_clip_root):
    _move_to_archive(_root_frame(tree_with_clip_root, 10))
    with pytest.raises(CutManifestError, match="lead-in frame is missing"):
        service.submit(_request(tree_with_clip_root, rows=1, handoff_index=77))
    assert service.job_service_calls == []
    assert service.store.load(tree_with_clip_root.storyboard_id).takes == ()


def test_sequential_submit_is_one_job_with_a_chain_of_takes(service, tree_with_clip_root):
    result = service.submit(
        _request(tree_with_clip_root, rows=3, mode="sequential", handoff_index=80)
    )
    chain = sorted(result.tree.takes, key=lambda t: t.chain_position)
    assert len(result.job_ids) == 1 and [t.handoff_index for t in chain] == [80, None, None]
    assert chain[1].parent_id == chain[0].take_id
    assert chain[2].parent_id == chain[1].take_id
    assert all(t.attempts == result.job_ids for t in chain)
    plan = _plan(service.fake_job_service.njrs[-1])
    assert plan.storyboard.take_ids == tuple(t.take_id for t in chain)
    assert [s.anchor_policy for s in plan.segments] == [
        "source",
        "carry_last_frame",
        "carry_last_frame",
    ]


def test_branch_from_a_middle_chain_take_uses_its_prefix(service, tree_with_finished_chain):
    middle = _chain_take(tree_with_finished_chain, position=1)
    request = _request(
        tree_with_finished_chain, rows=1, parent_id=middle.take_id, handoff_index=120
    )
    service.submit(request)
    assert _lead_in_of_last_njr(service).frame_count == 121
    cut = service.parent_cut(service.store.load(request.storyboard_id), middle.take_id)
    assert (
        cut is not None
        and len(cut.frames) == 81 + 80 + 80
        and cut.ranges[-1].owner == middle.take_id
    )


def test_handoff_outside_the_parent_cut_is_refused(service, tree_with_clip_root):
    with pytest.raises(StoryboardTreeError, match="outside this 81-frame cut"):
        service.submit(_request(tree_with_clip_root, rows=1, handoff_index=81))
    assert service.job_service_calls == []


@pytest.mark.parametrize(
    "rows, message",
    [
        ((), "1 to 6 rows"),
        (tuple(ContinueRow("go", "", "") for _ in range(7)), "1 to 6 rows"),
        ((ContinueRow("go", "", ""), ContinueRow("  ", "", "")), "Row 2 needs a positive prompt"),
    ],
)
def test_rows_are_checked_first(service, tree_with_clip_root, rows, message):
    with pytest.raises(StoryboardTreeError, match=message):
        service.submit(replace(_request(tree_with_clip_root), rows=rows))
    assert service.job_service_calls == []


def test_given_seeds_are_used_as_given(service, tree_with_clip_root):
    request = replace(
        _request(tree_with_clip_root),
        rows=(ContinueRow("a", "", "5"), ContinueRow("b", "", ""), ContinueRow("c", "", "random")),
    )
    service.submit(request)
    seeds = _seeds(service)
    assert seeds[0] == 5 and len(set(seeds)) == 3


def test_preview_submits_and_writes_nothing(service, tree_with_clip_root, tmp_path):
    preview = service.preview(
        _request(tree_with_clip_root, rows=3, mode="sequential", handoff_index=80)
    )
    assert (preview.jobs, preview.segments, preview.lead_in_frames, preview.fps) == (1, 3, 81, 16)
    assert preview.total_cut_frames == 81 + 80 * 3 and preview.seeds == ("random",) * 3
    parallel = service.preview(_request(tree_with_clip_root, rows=2, handoff_index=9))
    assert (parallel.jobs, parallel.total_cut_frames) == (2, 10 + 80)
    assert service.job_service_calls == []
    assert not (tmp_path / "storyboards" / tree_with_clip_root.storyboard_id / "leadins").exists()


def test_image_root_first_takes_have_no_lead_in(service, tmp_path):
    from tests.helpers.storyboard_380 import a14b_settings

    still = png(tmp_path / "stills" / "still.png", A14B_SIZE)
    tree = service.create_from_image(str(still), a14b_settings(frame_count=17), "From a still")
    assert tree.root.kind == "image" and tree.root.fps == 16
    result = service.submit(_request(tree, rows=2, handoff_index=None))
    plans = [_plan(njr) for njr in service.fake_job_service.njrs]
    assert all(p.storyboard.lead_in is None for p in plans) and len(result.job_ids) == 2
    with pytest.raises(StoryboardTreeError, match="no frames to continue from"):
        service.submit(_request(result.tree, rows=1, handoff_index=3))


# --------------------------------------------------------------------------------------------- reconcile


def test_stop_between_submission_and_recording_is_reconciled(service, tree_with_clip_root):
    service.store.fail_next_save_after = 1  # pending write succeeds, attempt write fails
    with pytest.raises(StoryboardTreeError):
        service.submit(_request(tree_with_clip_root, rows=2))
    tree = service.reconcile(tree_with_clip_root.storyboard_id)
    assert all(len(t.attempts) == 1 for t in tree.takes) and service.job_service_calls == [2]
    assert len(tree.takes) == 2
    assert service.reconcile(tree.storyboard_id) == tree  # nothing left to adopt; no save


def test_resume_joins_the_take_and_replay_becomes_a_sibling(
    service, tree_with_failed_and_completed_takes
):
    tree = tree_with_failed_and_completed_takes
    service.fake_repository.add_resume_of(_take(tree, "failed").attempts[0])
    service.fake_repository.add_replay_of(_take(tree, "completed").attempts[0])
    after = service.reconcile(tree.storyboard_id)
    assert len(_take(after, "failed").attempts) == 2
    replay = next(t for t in after.takes if t.replay_of == _take(tree, "completed").take_id)
    assert replay.parent_id == _take(tree, "completed").parent_id and after.label(
        replay.take_id
    ) != after.label(replay.replay_of)
    assert (
        replay.handoff_index == _take(tree, "completed").handoff_index and len(replay.attempts) == 1
    )


def test_a_chain_replay_becomes_a_new_chain(service, tree_with_clip_root):
    result = service.submit(
        _request(tree_with_clip_root, rows=2, mode="sequential", handoff_index=80)
    )
    service.fake_repository.add_replay_of(result.job_ids[0])
    after = service.reconcile(result.tree.storyboard_id)
    replays = [t for t in after.takes if t.replay_of is not None]
    first, second = sorted(replays, key=lambda t: t.chain_position)
    assert second.parent_id == first.take_id and first.parent_id == ROOT_PARENT
    assert first.attempts == second.attempts and first.batch_id == second.batch_id


# --------------------------------------------------------------------------------------------- surfaces


def test_history_refuses_v2_plans(v2_job_repository):
    with pytest.raises(StoryboardError, match="Open it in the Storyboard tab"):
        from_history(v2_job_repository, "job-v2")


def test_video_workflow_controller_exposes_the_service(tmp_path):
    repository = RecordingRepository()
    app = SimpleNamespace(
        job_service=SimpleNamespace(history_store=repository), output_dir=str(tmp_path)
    )
    controller = VideoWorkflowController(app_controller=app, workflow_registry=REG)
    assert isinstance(controller.storyboards, StoryboardSubmissionService)
    assert controller.storyboards._repository() is repository
    assert controller.storyboards._output_root() == str(tmp_path)
