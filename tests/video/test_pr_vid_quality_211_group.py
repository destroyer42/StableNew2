"""PR-VID-QUALITY-211: rebuilding an experiment's review group from persisted jobs.

Real experiment NJRs (production builder), a real temporary SQLite repository, a reopened connection standing
in for "the GUI session is gone".  No Comfy, WebUI, model or GPU.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pipeline.job_models_v2 import SourceKind
from src.queue.job_model import JobStatus
from src.queue.job_repository import EXPERIMENT_SIBLING_WINDOW, JobRepository
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.video.video_review_group import (
    ArmState,
    ReviewGroupError,
    build_review_group,
    classify_entry,
    snapshot_is_experiment_arm,
)
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.video_review_211 import (
    FFMPEG_AVAILABLE,
    build_plan,
    finish,
    make_clip,
    new_repository,
    njr_variant,
    persist,
    persist_plan,
    video_result,
)

needs_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")


def _states(group) -> dict[str, ArmState]:
    return {arm.label: arm.state for arm in group.arms}


def test_arms_resolve_into_one_group_in_a_to_d_order_whatever_the_completion_order(tmp_path):
    plan = build_plan(tmp_path, candidates=("1.5", "2", "2.5"))
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    clips = [tmp_path / f"{label}.mp4" for label in "ABCD"]
    for clip in clips:
        clip.write_bytes(b"x")
    for index in (3, 0, 2):  # D, then A, then C complete; B never does
        finish(repository, ids[index], JobStatus.COMPLETED, result=video_result(clips[index]))

    group = build_review_group(repository, ids[1])

    assert group.experiment_id == plan.experiment_id
    assert [arm.label for arm in group.arms] == ["A", "B", "C", "D"]
    assert [arm.value for arm in group.arms] == [1.0, 1.5, 2.0, 2.5]
    assert [arm.job_id for arm in group.arms] == ids
    assert group.variable_name == "pose_strength"
    assert _states(group) == {
        "A": ArmState.PLAYABLE,
        "B": ArmState.PENDING,
        "C": ArmState.PLAYABLE,
        "D": ArmState.PLAYABLE,
    }


def test_any_selected_job_reopens_the_siblings_after_the_session_is_gone(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    repository.close()

    reopened = JobRepository(tmp_path / "jobs.sqlite3")  # a new process would do exactly this
    for selected in ids:
        group = build_review_group(reopened, selected)
        assert [arm.job_id for arm in group.arms] == ids
        assert group.selected_job_id == selected
    overview = build_review_group(reopened, ids[0]).overview
    assert overview.workflow_id == "wan_animate2_drive_i2v_v1"
    assert overview.seed == 424242
    assert overview.driving_video_path.endswith("driving.mp4")
    assert len(overview.driving_video_sha256) == 64
    assert "pose_strength" not in overview.fixed_controls  # the tested control is not a fixed one
    assert overview.fixed_controls["pose_prompt"]


def test_unrelated_svd_other_experiment_and_filename_lookalikes_are_not_incorporated(tmp_path):
    plan = build_plan(tmp_path)
    other = build_plan(tmp_path / "other")
    repository = new_repository(tmp_path)
    plain = make_test_njr(prompt="an unrelated image job")
    svd_like = njr_variant(plan.arms[0].njr, job_id="svd-like-job", strip_learning_context=True)
    lookalike = tmp_path / f"{plan.experiment_id[:8]}_A.mp4"
    lookalike.write_bytes(b"x")
    ids = persist_plan(repository, plan)
    persist(repository, [plain, svd_like])
    other_ids = persist_plan(repository, other)
    finish(repository, other_ids[0], JobStatus.COMPLETED, result=video_result(lookalike))

    group = build_review_group(repository, ids[0])
    assert [arm.job_id for arm in group.arms] == ids
    assert build_review_group(repository, other_ids[0]).experiment_id == other.experiment_id

    with pytest.raises(ReviewGroupError) as refused:
        build_review_group(repository, "svd-like-job")
    assert refused.value.code == "not_video_experiment"
    with pytest.raises(ReviewGroupError, match="not an arm of a Video Workflow experiment"):
        build_review_group(repository, plain.job_id)
    with pytest.raises(ReviewGroupError) as unknown:
        build_review_group(repository, "no-such-job")
    assert unknown.value.code == "unknown_job"


def test_a_replay_descendant_is_excluded_not_merged(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    replay = njr_variant(
        plan.arms[1].njr, job_id="replay-of-b", source_kind=SourceKind.HISTORY_REPLAY.value
    )
    persist(repository, [replay])

    group = build_review_group(repository, ids[0])

    assert [arm.job_id for arm in group.arms] == ids
    assert group.excluded_job_ids == ("replay-of-b",)
    with pytest.raises(ReviewGroupError):
        build_review_group(repository, "replay-of-b")  # a replay is never itself an experiment arm


def test_duplicate_arm_provenance_fails_safely_with_a_message(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    persist(repository, [njr_variant(plan.arms[1].njr, job_id="claims-b-too")])

    with pytest.raises(ReviewGroupError) as refused:
        build_review_group(repository, ids[0])

    assert refused.value.code == "conflict"
    assert "both claim arm B" in str(refused.value)
    assert plan.experiment_id in str(refused.value)


def test_out_of_range_arm_index_and_a_diverging_arm_are_refused(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    persist(repository, [njr_variant(plan.arms[2].njr, job_id="index-nine", variant_index=9)])
    with pytest.raises(ReviewGroupError, match="valid arms are 0 to 3"):
        build_review_group(repository, ids[0])

    diverging_repo = new_repository(tmp_path, "diverging.sqlite3")
    plan2 = build_plan(tmp_path / "second")
    # Same experiment, but the stored seed differs outside the tested control: provenance disagrees.
    arms = [plan2.arms[0].njr, njr_variant(plan2.arms[1].njr, seed=7)]
    ids2 = persist(diverging_repo, arms)
    with pytest.raises(ReviewGroupError) as refused:
        build_review_group(diverging_repo, ids2[0])
    assert refused.value.code == "conflict"
    assert "do not agree" in str(refused.value)


def test_a_single_found_arm_is_a_group_of_one_not_an_error(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    persist(repository, [plan.arms[0].njr])

    group = build_review_group(repository, plan.arms[0].njr.job_id)

    assert len(group.arms) == 1


def test_sibling_lookup_is_bounded_to_a_rowid_window(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    fillers = [make_test_njr(prompt=f"filler {n}") for n in range(EXPERIMENT_SIBLING_WINDOW + 4)]
    persist(repository, fillers)
    far = njr_variant(
        plan.arms[0].njr, job_id="far-away", source_kind=SourceKind.HISTORY_REPLAY.value
    )
    persist(repository, [far])

    near = repository.list_experiment_sibling_entries(ids[0], plan.experiment_id)
    assert [entry.job_id for entry in near] == ids  # adjacent rows only
    assert repository.list_experiment_sibling_entries("missing", plan.experiment_id) == []
    assert repository.list_experiment_sibling_entries(ids[0], "") == []
    assert build_review_group(repository, ids[0]).excluded_job_ids == ()  # beyond the window


def test_the_sibling_lookup_is_read_only(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)

    def dump() -> list[tuple]:
        with sqlite3.connect(tmp_path / "jobs.sqlite3") as db:
            return db.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()

    before = dump()
    build_review_group(repository, ids[1])
    assert dump() == before


def test_distinct_states_for_pending_running_failed_cancelled_missing_and_completed(tmp_path):
    plan = build_plan(tmp_path, candidates=("1.5", "2", "2.5"))
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    good = tmp_path / "good.mp4"
    good.write_bytes(b"x")
    # A stays queued; B runs; C fails; D completes with an output that has since vanished.
    job = repository.get_job_model(ids[1])
    repository.transition_job(job, JobStatus.RUNNING)
    finish(repository, ids[2], JobStatus.FAILED, error="CUDA out of memory")
    finish(repository, ids[3], JobStatus.COMPLETED, result=video_result(tmp_path / "gone.mp4"))

    states = _states(build_review_group(repository, ids[0]))

    assert states == {
        "A": ArmState.PENDING,
        "B": ArmState.RUNNING,
        "C": ArmState.FAILED,
        "D": ArmState.MISSING,
    }
    failed = build_review_group(repository, ids[0]).arms[2]
    assert "CUDA out of memory" in failed.state_text and failed.artifact_path is None
    cancelled_repo = new_repository(tmp_path, "c.sqlite3")
    plan_c = build_plan(tmp_path / "c")
    ids_c = persist_plan(cancelled_repo, plan_c)
    finish(cancelled_repo, ids_c[0], JobStatus.CANCELLED)
    assert build_review_group(cancelled_repo, ids_c[1]).arms[0].state is ArmState.CANCELLED


def test_interrupted_and_outputless_completions_are_not_playable(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    finish(repository, ids[0], JobStatus.COMPLETED, result={"success": True})
    frames_only = {"video_bundle": {"primary_path": None, "frame_paths": ["f0.png", "f1.png"]}}
    finish(repository, ids[1], JobStatus.COMPLETED, result=frames_only)
    wrong_type = tmp_path / "output.png"
    wrong_type.write_bytes(b"x")
    finish(repository, ids[2], JobStatus.COMPLETED, result=video_result(wrong_type))

    group = build_review_group(repository, ids[0])

    assert _states(group) == {
        "A": ArmState.NO_OUTPUT,
        "B": ArmState.UNSUPPORTED,
        "C": ArmState.UNSUPPORTED,
    }
    entry = repository.get_job(ids[0])
    entry.error_envelope = UnifiedErrorEnvelope(
        error_type="INTERRUPTED_RESTART_ACTION_REQUIRED",
        subsystem="queue",
        severity="error",
        message="restart",
        cause=None,
        stack="",
        job_id=ids[0],
        stage="video_workflow",
    )
    assert classify_entry(entry)[0] is ArmState.INTERRUPTED


def test_the_recorded_bundle_chooses_the_clip_never_a_directory_guess(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    chosen = tmp_path / "run" / "chosen.mp4"
    chosen.parent.mkdir()
    chosen.write_bytes(b"x")
    (chosen.parent / "decoy.mp4").write_bytes(b"y")  # a sibling file nobody recorded
    finish(repository, ids[0], JobStatus.COMPLETED, result=video_result(chosen))
    legacy = tmp_path / "legacy.mp4"
    legacy.write_bytes(b"x")
    finish(
        repository,
        ids[1],
        JobStatus.COMPLETED,
        result={"metadata": {"video_primary_artifact": {"primary_path": str(legacy)}}},
    )
    finish(repository, ids[2], JobStatus.COMPLETED, result={"output_dir": str(chosen.parent)})

    group = build_review_group(repository, ids[0])

    assert group.arms[0].artifact_path == str(chosen)
    assert group.arms[1].artifact_path == str(legacy) and group.arms[1].playable
    assert group.arms[2].state is ArmState.NO_OUTPUT  # a folder is never scanned for a clip


def test_snapshot_probe_recognises_only_experiment_arms(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    persist(repository, [make_test_njr(prompt="plain")])

    assert all(snapshot_is_experiment_arm(repository.get_job(job_id).snapshot) for job_id in ids)
    plain = repository.list_recent_jobs(limit=1)[0]
    assert not snapshot_is_experiment_arm(plain.snapshot)
    assert not snapshot_is_experiment_arm(None) and not snapshot_is_experiment_arm({})


@needs_ffmpeg
def test_real_clips_round_trip_through_the_group(tmp_path):
    plan = build_plan(tmp_path)
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    clip: Path = make_clip(tmp_path, "a.mp4")
    finish(repository, ids[0], JobStatus.COMPLETED, result=video_result(clip))

    group = build_review_group(repository, ids[2])

    assert group.arms[0].playable and group.arms[0].artifact_path == str(clip)
