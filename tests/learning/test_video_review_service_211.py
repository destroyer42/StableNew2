"""PR-VID-QUALITY-211: the review service over a real experiment, repository and evidence file.

Covers the acceptance path without any generation: persisted canonical jobs -> reopen after the session is
gone -> rate clips -> a rebuilt service recovers the ratings -> image Learning ignores them -> no execution
authority, job row or artifact changed.  Clips are plain files here (hashing needs bytes, not a decoder).
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest

from src.learning.video_quality_review import (
    ClipReviewDraft,
    ReviewSaveError,
    ReviewValidationError,
)
from src.learning.video_review_service import (
    ArtifactTooLarge,
    ReviewCancelled,
    VideoReviewService,
    file_sha256,
)
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.video.video_review_group import ArmState, ReviewGroupError
from tests.helpers.video_review_211 import (
    build_plan,
    finish,
    new_repository,
    persist_plan,
    video_result,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Env:
    def __init__(self, tmp_path: Path, *, complete: tuple[int, ...] = (0, 1, 2)) -> None:
        self.tmp = tmp_path
        self.plan = build_plan(tmp_path)
        self.repository = new_repository(tmp_path)
        self.ids = persist_plan(self.repository, self.plan)
        self.records = tmp_path / "data" / "learning" / "learning_records.jsonl"
        self.clips: dict[int, Path] = {}
        for index in complete:
            clip = tmp_path / "out" / f"arm{index}.mp4"
            clip.parent.mkdir(exist_ok=True)
            clip.write_bytes(f"synthetic clip bytes {index}".encode() * 50)
            self.clips[index] = clip
            finish(self.repository, self.ids[index], JobStatus.COMPLETED, result=video_result(clip))

    def service(self, repository=None) -> VideoReviewService:
        return VideoReviewService(repository or self.repository, self.records)

    def reopened_service(self) -> VideoReviewService:
        """A brand-new repository connection and service: what a restarted application has."""

        self.repository.close()
        self.repository = JobRepository(self.tmp / "jobs.sqlite3")
        return self.service(self.repository)

    def db_dump(self) -> list[tuple]:
        with sqlite3.connect(self.tmp / "jobs.sqlite3") as db:
            return db.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()

    def tree(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.tmp)): _sha(path)
            for path in sorted(self.tmp.rglob("*"))
            if path.is_file()
            and path.suffix not in {".sqlite3", ".jsonl"}
            and "-wal" not in path.name
            and "-shm" not in path.name
        }


def test_load_identifies_each_playable_clip_by_content_and_leaves_the_rest_visible(tmp_path):
    env = _Env(tmp_path)

    loaded = env.service().load(env.ids[1])

    a, b, c = loaded.group.arms
    assert a.playable and a.artifact_sha256 == _sha(env.clips[0]) and a.artifact_bytes > 0
    assert b.artifact_sha256 == _sha(env.clips[1]) and c.artifact_sha256 == _sha(env.clips[2])
    assert loaded.stored.clips == {}


def test_two_clips_rated_then_recovered_by_a_rebuilt_service_and_isolated_from_images(tmp_path):
    env = _Env(tmp_path)
    before_db, before_files = env.db_dump(), env.tree()
    loaded = env.service().load(env.ids[0])
    group = loaded.group
    service = env.service()

    first = service.save_clip_review(
        group,
        env.ids[0],
        ClipReviewDraft(5, "not_achieved", {"temporal_continuity": 5}, "arm never rose"),
    )
    second = service.save_clip_review(
        group,
        env.ids[2],
        ClipReviewDraft(2, "achieved", {"anatomy_object_integrity": 1}, "hand deformed"),
    )
    pref = service.save_preference(group, env.ids[2], "reaches the pose")
    assert (first.status, first.revision, second.revision, pref.status) == ("saved", 1, 1, "saved")

    restarted = (
        env.reopened_service()
    )  # nothing survives but the repository file and the evidence file
    recovered = restarted.load(env.ids[1])
    stored = recovered.stored
    a = recovered.group.arms[0]
    c = recovered.group.arms[2]
    assert stored.clip_for(a.job_id, a.artifact_sha256).draft.overall_rating == 5
    assert stored.clip_for(a.job_id, a.artifact_sha256).draft.action_outcome == "not_achieved"
    assert stored.clip_for(c.job_id, c.artifact_sha256).draft.notes == "hand deformed"
    assert (
        stored.clip_for(recovered.group.arms[1].job_id, recovered.group.arms[1].artifact_sha256)
        is None
    )
    assert (
        stored.preference.preferred_job_id == env.ids[2]
        and stored.preference.reason == "reaches the pose"
    )

    # Review authority only: no job row, no artifact byte and no new file other than the evidence.
    assert env.db_dump() == before_db
    assert env.tree() == before_files
    assert env.records.exists()


def test_saved_reviews_never_reach_image_learning(tmp_path):
    from src.learning.learning_analytics import LearningAnalytics
    from src.learning.learning_record import LearningRecordWriter
    from src.learning.recommendation_engine import RecommendationEngine

    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group
    service.save_clip_review(group, env.ids[0], ClipReviewDraft(5, "achieved"))
    service.save_clip_review(group, env.ids[1], ClipReviewDraft(5, "achieved"))

    writer = LearningRecordWriter(env.records)
    assert RecommendationEngine(env.records).recommend("portrait", "txt2img").recommendations == []
    assert LearningAnalytics(writer).get_overall_summary().total_ratings == 0
    assert writer.get_ratings_for_experiment(group.experiment_id) == {}


def test_an_unchanged_resave_appends_no_second_record(tmp_path):
    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group
    draft = ClipReviewDraft(4, "partially_achieved", {}, "late")

    service.save_clip_review(group, env.ids[0], draft)
    lines = env.records.read_text(encoding="utf-8").count("\n")
    again = service.save_clip_review(group, env.ids[0], draft)

    assert again.status == "unchanged"
    assert env.records.read_text(encoding="utf-8").count("\n") == lines


def test_a_replaced_artifact_does_not_inherit_a_rating(tmp_path):
    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group
    service.save_clip_review(group, env.ids[0], ClipReviewDraft(5, "achieved", {}, "great take"))

    env.clips[0].write_bytes(b"a different render written over the same path")

    reloaded = service.load(env.ids[0])
    arm = reloaded.group.arms[0]
    assert arm.playable and arm.artifact_sha256 != group.arms[0].artifact_sha256
    assert reloaded.stored.clip_for(arm.job_id, arm.artifact_sha256) is None
    # The earlier evidence is preserved on disk, attached to the bytes it was about.
    assert (
        reloaded.stored.clip_for(arm.job_id, group.arms[0].artifact_sha256).draft.notes
        == "great take"
    )


def test_saving_after_the_file_changed_under_an_open_review_is_refused(tmp_path):
    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group
    env.clips[0].write_bytes(b"swapped while the review window was open")

    with pytest.raises(ReviewSaveError, match="changed after this review opened"):
        service.save_clip_review(group, env.ids[0], ClipReviewDraft(3, "achieved"))
    with pytest.raises(ReviewSaveError, match="changed after this review opened"):
        service.save_preference(group, env.ids[0], "why")
    assert not env.records.exists() or env.records.read_text(encoding="utf-8") == ""


def test_a_deleted_or_unplayable_arm_cannot_be_rated(tmp_path):
    env = _Env(tmp_path, complete=(0,))
    service = env.service()
    group = service.load(env.ids[0]).group

    with pytest.raises(ReviewSaveError, match="no completed, identified video"):
        service.save_clip_review(group, env.ids[1], ClipReviewDraft(3, "achieved"))
    with pytest.raises(ReviewSaveError, match="not an arm"):
        service.save_clip_review(group, "someone-elses-job", ClipReviewDraft(3, "achieved"))
    env.clips[0].unlink()
    with pytest.raises(ReviewSaveError, match="can no longer be read"):
        service.save_clip_review(group, env.ids[0], ClipReviewDraft(3, "achieved"))
    assert service.load(env.ids[0]).group.arms[0].state is ArmState.MISSING


def test_a_rejected_draft_writes_nothing(tmp_path):
    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group

    with pytest.raises(ReviewValidationError):
        service.save_clip_review(group, env.ids[0], ClipReviewDraft(7, "achieved"))
    assert not env.records.exists() or env.records.read_text(encoding="utf-8") == ""


def test_a_failed_evidence_write_surfaces_and_changes_nothing(tmp_path, monkeypatch):
    from src.learning.learning_record import LearningRecordWriter

    env = _Env(tmp_path)
    service = env.service()
    group = service.load(env.ids[0]).group
    monkeypatch.setattr(LearningRecordWriter, "append_record", lambda self, record: False)

    with pytest.raises(ReviewSaveError, match="Your edits are kept"):
        service.save_clip_review(group, env.ids[0], ClipReviewDraft(3, "achieved"))
    assert service.load(env.ids[0]).stored.clips == {}


def test_a_group_error_is_actionable_for_a_non_experiment_job(tmp_path):
    env = _Env(tmp_path)
    with pytest.raises(ReviewGroupError, match="Enter or select a job id"):
        env.service().load("  ")
    with pytest.raises(ReviewGroupError, match="exists in the job history"):
        env.service().load("nope")


def test_loading_can_be_cancelled_between_arms_and_while_hashing(tmp_path):
    env = _Env(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ReviewCancelled):
        env.service().load(env.ids[0], cancel=cancel)
    with pytest.raises(ReviewCancelled):
        file_sha256(env.clips[0], cancel=cancel)


def test_hashing_is_bounded_by_size_and_matches_hashlib(tmp_path, monkeypatch):
    path = tmp_path / "x.bin"
    path.write_bytes(b"abc" * 1000)
    assert file_sha256(path) == hashlib.sha256(b"abc" * 1000).hexdigest()
    monkeypatch.setattr("src.learning.video_review_service.MAX_HASH_BYTES", 10)
    with pytest.raises(ArtifactTooLarge):
        file_sha256(path)


def test_an_oversized_output_is_shown_as_unreviewable_not_hashed(tmp_path, monkeypatch):
    env = _Env(tmp_path)
    monkeypatch.setattr("src.learning.video_review_service.MAX_HASH_BYTES", 10)

    group = env.service().load(env.ids[0]).group

    assert group.arms[0].state is ArmState.UNSUPPORTED and "Too large" in group.arms[0].state_text


def test_a_locked_or_unreadable_job_history_is_an_actionable_group_error(tmp_path):
    class _Locked:
        def get_job(self, job_id):
            raise sqlite3.OperationalError("database is locked")

        def list_experiment_sibling_entries(self, job_id, experiment_id):  # pragma: no cover
            return []

    service = VideoReviewService(_Locked(), tmp_path / "r.jsonl")

    with pytest.raises(ReviewGroupError) as refused:
        service.load("any-job")

    assert refused.value.code == "storage" and "database is locked" in str(refused.value)
