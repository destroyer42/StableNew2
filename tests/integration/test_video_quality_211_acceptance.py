"""PR-VID-QUALITY-211 acceptance path, end to end, with real FFmpeg decoding and a real repository.

1. persisted canonical jobs form an experiment; 2. the GUI session is gone and the review opens from one id;
3. real clips decode into a bounded preview; 4. arms carry the right job/value/artifact; 5. two clips are
rated; 6. a rebuilt service recovers them; 7. image Learning ignores them; 8. no job row, artifact byte or
other file changed.  CPU only; no Comfy, WebUI, model or GPU.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.gui.view_contracts.video_review_contract import VideoReviewSession
from src.learning.learning_analytics import LearningAnalytics
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.learning.video_review_service import VideoReviewService
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from src.video.review_preview import prepare_review_preview
from tests.helpers.video_review_211 import (
    FFMPEG_AVAILABLE,
    build_plan,
    finish,
    make_clip,
    new_repository,
    persist_plan,
    video_result,
)

pytestmark = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg/FFprobe are not installed")


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".mp4", ".png"}
    }


def _rows(db: Path) -> list[tuple]:
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()


def _session(service: VideoReviewService) -> VideoReviewSession:
    return VideoReviewSession(
        load=lambda job_id, cancel: service.load(job_id, cancel=cancel),
        prepare_preview=lambda path, cancel: prepare_review_preview(path, cancel=cancel),
        save_clip=service.save_clip_review,
        save_preference=service.save_preference,
        file_exists=lambda path: Path(path).is_file(),
    )


def _load(session: VideoReviewSession, job_id: str) -> None:
    work = session.begin_load(job_id)
    assert work is not None and session.finish_load(work, session.run_load(work))


def test_a_persisted_experiment_is_reviewed_rated_and_recovered_without_touching_execution(
    tmp_path,
):
    plan = build_plan(tmp_path, candidates=("1.5", "2"))
    repository = new_repository(tmp_path)
    ids = persist_plan(repository, plan)
    clips = [
        make_clip(tmp_path, "arm_a.mp4", frames=12, rate=12, size="96x64"),
        make_clip(tmp_path, "arm_b.mp4", frames=8, rate=12, size="96x64"),
    ]
    finish(repository, ids[0], JobStatus.COMPLETED, result=video_result(clips[0]))
    finish(repository, ids[1], JobStatus.COMPLETED, result=video_result(clips[1]))
    finish(repository, ids[2], JobStatus.FAILED, error="out of memory")
    records = tmp_path / "data" / "learning" / "learning_records.jsonl"
    db = tmp_path / "jobs.sqlite3"
    before_rows, before_files = _rows(db), _tree(tmp_path)

    # 2. "the GUI session is gone": a new repository connection and a service that remembers nothing.
    repository.close()
    reopened = JobRepository(db)
    session = _session(VideoReviewService(reopened, records))
    _load(session, ids[2])  # any arm id, even the failed one, reopens the whole study

    # 4. identities: right job, right tested value, right artifact; the failed arm is visible, not playable.
    arms = {arm.label: arm for arm in session.group.arms}
    assert [(a.label, a.job_id, a.value) for a in session.group.arms] == [
        ("A", ids[0], 1.0),
        ("B", ids[1], 1.5),
        ("C", ids[2], 2.0),
    ]
    assert arms["A"].artifact_path == str(clips[0]) and arms["B"].artifact_path == str(clips[1])
    assert arms["C"].state.value == "failed" and "out of memory" in arms["C"].state_text
    assert arms["A"].artifact_sha256 == hashlib.sha256(clips[0].read_bytes()).hexdigest()

    # 3. a real, bounded, playable preview for the selected pair (or an explicit bounded failure).
    works = session.select_pair(ids[0], ids[1])
    for work in works:
        assert session.finish_preview(work, session.run_preview(work))
    assert [session.slot(job).state for job in (ids[0], ids[1])] == ["ready", "ready"]
    assert session.clock.steps == 12
    session.clock.seek(11)
    assert session.clock.is_held(session.timing_for(ids[1])) and not session.clock.is_held(
        session.timing_for(ids[0])
    )
    assert any("B is shorter" in note for note in session.clock.notes())

    # 5. assessments for two clips, saved through the session exactly as the window does.
    for job_id, overall, outcome, note in (
        (ids[0], 5, "not_achieved", "arm never lifted"),
        (ids[1], 2, "achieved", "hand deformed"),
    ):
        session.set_field(job_id, "overall", str(overall))
        session.set_field(job_id, "outcome", outcome)
        session.set_field(job_id, "notes", note)
        save = session.begin_save(job_id)
        assert session.finish_save(save, session.run_save(save))
        assert session.messages[job_id] == "Saved (revision 1)."
    session.set_preference(ids[1], "reaches the pose")
    preference = session.begin_save_preference()
    assert session.finish_save(preference, session.run_save(preference))
    session.close()
    reopened.close()

    # 6. a rebuilt service over a fresh connection recovers every review.
    final_repo = JobRepository(db)
    recovered = _session(VideoReviewService(final_repo, records))
    _load(recovered, ids[0])
    assert (
        recovered.forms[ids[0]].overall == "5" and recovered.forms[ids[0]].outcome == "not_achieved"
    )
    assert (
        recovered.forms[ids[1]].notes == "hand deformed"
        and recovered.forms[ids[1]].outcome == "achieved"
    )
    assert recovered.messages[ids[0]] == "Saved review, revision 1."
    assert not recovered.is_dirty(ids[0]) and not recovered.is_dirty(ids[1])
    assert recovered.preference_job == ids[1] and recovered.preference_reason == "reaches the pose"
    recovered.close()
    final_repo.close()

    # 7. isolation from image Learning.
    writer = LearningRecordWriter(records)
    assert RecommendationEngine(records).recommend("portrait", "txt2img").recommendations == []
    assert LearningAnalytics(writer).get_overall_summary().total_ratings == 0
    assert writer.get_ratings_for_experiment(plan.experiment_id) == {}

    # 8. no execution authority or generated artifact changed.
    assert _rows(db) == before_rows
    assert _tree(tmp_path) == before_files
