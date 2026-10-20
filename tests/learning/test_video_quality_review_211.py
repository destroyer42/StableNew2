"""PR-VID-QUALITY-211: the video quality rubric, its append-only evidence and its isolation from image Learning.

Temporary record files only; the repository's real ``data/learning`` is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.learning.learning_analytics import LearningAnalytics
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_NO_EVIDENCE,
    RecommendationEngine,
)
from src.learning.video_quality_review import (
    ACTION_OUTCOMES,
    DIMENSION_KEYS,
    ENTRY_CLIP,
    RECORD_KIND,
    REVIEW_KEY,
    SAVED,
    UNCHANGED,
    ClipReviewDraft,
    ReviewSaveError,
    ReviewTarget,
    ReviewValidationError,
    VideoReviewStore,
    build_clip_record,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
EXPERIMENT = "exp-0123456789"


def _target(job: str = "job-a", sha: str = SHA_A, **overrides) -> ReviewTarget:
    values = {
        "experiment_id": EXPERIMENT,
        "experiment_name": "Video experiment: Pose Strength",
        "job_id": job,
        "arm_index": 0,
        "arm_label": "A",
        "variable_name": "pose_strength",
        "tested_value": 1.0,
        "workflow_id": "wan_animate2_drive_i2v_v1",
        "workflow_version": "1.1.0",
        "backend_id": "comfy",
        "artifact_path": "C:/out/a.mp4",
        "artifact_sha256": sha,
        "identities": {"njr_fingerprint": "f" * 64, "seed": 1},
    }
    values.update(overrides)
    return ReviewTarget(**values)


def _draft(overall=4, outcome="achieved", notes="", **dimensions) -> ClipReviewDraft:
    return ClipReviewDraft(
        overall_rating=overall, action_outcome=outcome, dimensions=dimensions, notes=notes
    )


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ rubric validation


@pytest.mark.parametrize("bad", [0, 6, -1, 3.5, True, "x", "", None, "4.0", [4]])
def test_overall_rating_must_be_a_whole_number_one_to_five(bad):
    with pytest.raises(ReviewValidationError):
        _draft(overall=bad).validate()


@pytest.mark.parametrize("good", [1, 2, 3, 4, 5, "3", 4.0, " 5 "])
def test_overall_rating_accepts_whole_numbers_one_to_five(good):
    assert _draft(overall=good).validate().overall_rating in {1, 2, 3, 4, 5}


@pytest.mark.parametrize("bad", ["", None, "great", "ACHIEVED", "partially"])
def test_action_outcome_must_be_one_of_the_four_values(bad):
    with pytest.raises(ReviewValidationError, match="requested action"):
        _draft(outcome=bad).validate()
    assert {value for value, _label in ACTION_OUTCOMES} == {
        "achieved",
        "partially_achieved",
        "not_achieved",
        "cannot_assess",
    }


def test_dimensions_are_optional_validated_and_closed():
    ok = _draft(**{DIMENSION_KEYS[0]: "5", DIMENSION_KEYS[1]: ""}).validate()
    assert dict(ok.dimensions) == {DIMENSION_KEYS[0]: 5}
    with pytest.raises(ReviewValidationError, match="Directed-motion fidelity"):
        _draft(**{DIMENSION_KEYS[0]: 9}).validate()
    with pytest.raises(ReviewValidationError, match="Unknown rating dimension"):
        _draft(sharpness=3).validate()


def test_notes_are_bounded_and_control_characters_are_removed():
    assert _draft(notes="feet stayed planted\n\x00hand deformed\x07").validate().notes == (
        "feet stayed planted\nhand deformed"
    )
    with pytest.raises(ReviewValidationError, match="2000 characters"):
        _draft(notes="x" * 2001).validate()
    with pytest.raises(ReviewValidationError):
        ClipReviewDraft(overall_rating=3, action_outcome="achieved", notes=["not text"]).validate()


def test_a_review_needs_the_artifact_content_hash():
    with pytest.raises(ReviewValidationError, match="content hash"):
        _target(sha="").check()
    with pytest.raises(ReviewValidationError, match="content hash"):
        _target(sha="G" * 64).check()


# ------------------------------------------------------------------ record shape


def test_the_record_is_compact_namespaced_and_carries_no_image_rating_keys():
    record = build_clip_record(
        _target(),
        _draft(5, "not_achieved", "arm stayed down"),
        revision=1,
        review_id="r1",
        reviewed_at="2026-10-19T00:00:00",
    )
    payload = json.loads(record.to_json())

    assert payload["metadata"]["record_kind"] == RECORD_KIND == "video_workflow_quality_rating"
    assert set(payload["metadata"]) == {"record_kind", REVIEW_KEY}
    for forbidden in (
        "user_rating", "image_path", "experiment_id", "experiment_name", "learning_context",
        "variant_value", "variable_under_test", "frozen_experiment", "advancement_decision",
    ):  # fmt: skip
        assert forbidden not in payload["metadata"]
    review = payload["metadata"][REVIEW_KEY]
    assert review["schema"] == "stablenew.video-quality-review.v1" and review["schema_version"] == 1
    assert review["entry_type"] == ENTRY_CLIP and review["revision"] == 1
    assert review["experiment_id"] == EXPERIMENT and review["job_id"] == "job-a"
    assert review["arm_index"] == 0 and review["tested_value"] == 1.0
    assert review["workflow"] == {
        "id": "wan_animate2_drive_i2v_v1",
        "version": "1.1.0",
        "backend_id": "comfy",
    }
    assert review["artifact"] == {"path": "C:/out/a.mp4", "sha256": SHA_A}
    assert review["overall_rating"] == 5 and review["action_outcome"] == "not_achieved"
    assert review["notes"] == "arm stayed down" and review["identities"]["seed"] == 1
    assert payload["outputs"] == [] and payload["base_config"] == {}  # no bytes, no snapshots
    assert len(record.to_json()) < 2500


# ------------------------------------------------------------------ persistence


def test_save_reopen_edit_and_reload_resolve_the_latest_revision(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    store = VideoReviewStore(path)

    first = store.save_clip(_target(), _draft(2, "not_achieved", "legs frozen"))
    assert (first.status, first.revision) == (SAVED, 1)
    reopened = VideoReviewStore(path)  # a restart: nothing but the file survives
    saved = reopened.load(EXPERIMENT).clip_for("job-a", SHA_A)
    assert saved is not None and saved.revision == 1
    assert saved.draft.overall_rating == 2 and saved.draft.notes == "legs frozen"

    second = reopened.save_clip(
        _target(), _draft(4, "partially_achieved", "legs move late", temporal_continuity=3)
    )
    assert (second.status, second.revision) == (SAVED, 2)
    latest = VideoReviewStore(path).load(EXPERIMENT).clip_for("job-a", SHA_A)
    assert latest.revision == 2 and latest.draft.action_outcome == "partially_achieved"
    assert dict(latest.draft.dimensions) == {"temporal_continuity": 3}
    assert len(_lines(path)) == 2  # append-only: the first revision is still on disk
    assert json.loads(_lines(path)[0])["metadata"][REVIEW_KEY]["overall_rating"] == 2


def test_an_unchanged_save_appends_nothing(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    store = VideoReviewStore(path)
    store.save_clip(_target(), _draft(3, "achieved", "fine", scene_stability=4))

    again = store.save_clip(_target(), _draft("3", "achieved", "  fine  ", scene_stability="4"))

    assert (again.status, again.revision) == (UNCHANGED, 1)
    assert len(_lines(path)) == 1


def test_achieved_and_not_achieved_stay_distinguishable_at_any_overall_rating(tmp_path):
    store = VideoReviewStore(tmp_path / "r.jsonl")
    store.save_clip(
        _target("job-a", SHA_A), _draft(5, "not_achieved")
    )  # beautiful but wrong motion
    store.save_clip(
        _target("job-b", SHA_B, arm_label="B"), _draft(1, "achieved")
    )  # ugly but did it

    stored = VideoReviewStore(tmp_path / "r.jsonl").load(EXPERIMENT)

    a, b = stored.clip_for("job-a", SHA_A).draft, stored.clip_for("job-b", SHA_B).draft
    assert (a.overall_rating, a.action_outcome) == (5, "not_achieved")
    assert (b.overall_rating, b.action_outcome) == (1, "achieved")


def test_a_review_belongs_to_the_job_and_the_artifact_bytes(tmp_path):
    store = VideoReviewStore(tmp_path / "r.jsonl")
    store.save_clip(_target("job-a", SHA_A), _draft(4, "achieved"))
    stored = store.load(EXPERIMENT)

    assert stored.clip_for("job-a", SHA_A) is not None
    assert stored.clip_for("job-a", SHA_B) is None  # a replaced file inherits nothing
    assert (
        stored.clip_for("job-b", SHA_A) is None
    )  # another job with identical bytes inherits nothing
    assert store.load("another-experiment").clips == {}


def test_a_replaced_artifact_gets_its_own_revision_history(tmp_path):
    store = VideoReviewStore(tmp_path / "r.jsonl")
    store.save_clip(_target(sha=SHA_A), _draft(4, "achieved"))
    outcome = store.save_clip(_target(sha=SHA_B), _draft(2, "not_achieved"))

    assert outcome.revision == 1  # new bytes start a new history; the old one is preserved
    stored = store.load(EXPERIMENT)
    assert stored.clip_for("job-a", SHA_A).draft.overall_rating == 4
    assert stored.clip_for("job-a", SHA_B).draft.overall_rating == 2


def test_invalid_torn_or_foreign_lines_never_hide_a_valid_revision(tmp_path):
    path = tmp_path / "r.jsonl"
    store = VideoReviewStore(path)
    store.save_clip(_target(), _draft(3, "achieved"))
    store.save_clip(_target(), _draft(4, "achieved"))
    broken = json.loads(_lines(path)[-1])
    broken["metadata"][REVIEW_KEY]["revision"] = 3
    broken["metadata"][REVIEW_KEY]["overall_rating"] = 9  # outside the rubric
    future = json.loads(_lines(path)[-1])
    future["metadata"][REVIEW_KEY]["revision"] = 4
    future["metadata"][REVIEW_KEY]["schema_version"] = 2  # a format this reader does not know
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(broken) + "\n" + json.dumps(future) + "\n")
        handle.write(
            '{"metadata": {"record_kind": "video_workflow_quality_rating", "video_quality_re'
        )  # torn

    latest = VideoReviewStore(path).load(EXPERIMENT).clip_for("job-a", SHA_A)

    assert latest.revision == 2 and latest.draft.overall_rating == 4


def test_a_failed_write_raises_and_leaves_no_trace(tmp_path, monkeypatch):
    path = tmp_path / "r.jsonl"
    store = VideoReviewStore(path)
    monkeypatch.setattr(LearningRecordWriter, "append_record", lambda self, record: False)

    with pytest.raises(ReviewSaveError, match="could not be written"):
        store.save_clip(_target(), _draft())

    assert not path.exists() or _lines(path) == []
    assert store.load(EXPERIMENT).clips == {}


def test_a_writer_exception_is_a_save_error_not_a_crash(tmp_path, monkeypatch):
    def boom(self, record):
        raise OSError("disk full")

    store = VideoReviewStore(tmp_path / "r.jsonl")
    monkeypatch.setattr(LearningRecordWriter, "append_record", boom)

    with pytest.raises(ReviewSaveError, match="disk full"):
        store.save_clip(_target(), _draft())


def test_a_write_that_cannot_be_read_back_is_not_a_success(tmp_path, monkeypatch):
    store = VideoReviewStore(tmp_path / "r.jsonl")
    monkeypatch.setattr(VideoReviewStore, "_confirm_tail", lambda self, review_id: False)

    with pytest.raises(ReviewSaveError, match="read back"):
        store.save_clip(_target(), _draft())


def test_the_write_goes_through_the_canonical_record_writer(tmp_path, monkeypatch):
    seen: list[LearningRecord] = []
    original = LearningRecordWriter.append_record

    def spy(self, record):
        seen.append(record)
        return original(self, record)

    monkeypatch.setattr(LearningRecordWriter, "append_record", spy)
    VideoReviewStore(tmp_path / "r.jsonl").save_clip(_target(), _draft())

    assert len(seen) == 1 and seen[0].metadata["record_kind"] == RECORD_KIND


# ------------------------------------------------------------------ manual preference


def test_a_manual_preference_is_recorded_replaced_and_cleared(tmp_path):
    path = tmp_path / "r.jsonl"
    store = VideoReviewStore(path)

    assert (
        store.save_preference(experiment_id=EXPERIMENT, preferred_job_id=None).status == UNCHANGED
    )
    saved = store.save_preference(
        experiment_id=EXPERIMENT,
        preferred_job_id="job-b",
        preferred_arm_label="B",
        preferred_artifact_sha256=SHA_B,
        reason="  keeps the shoulder level  ",
    )
    assert (saved.status, saved.revision) == (SAVED, 1)
    same = store.save_preference(
        experiment_id=EXPERIMENT,
        preferred_job_id="job-b",
        preferred_arm_label="B",
        preferred_artifact_sha256=SHA_B,
        reason="keeps the shoulder level",
    )
    assert same.status == UNCHANGED and len(_lines(path)) == 1
    cleared = store.save_preference(experiment_id=EXPERIMENT, preferred_job_id=None)
    assert (cleared.status, cleared.revision) == (SAVED, 2)

    stored = VideoReviewStore(path).load(EXPERIMENT)
    assert stored.preference.preferred_job_id is None and stored.preference.revision == 2
    first = json.loads(_lines(path)[0])["metadata"][REVIEW_KEY]
    assert first["preferred_job_id"] == "job-b" and first["reason"] == "keeps the shoulder level"
    with pytest.raises(ReviewValidationError, match="content hash"):
        store.save_preference(experiment_id=EXPERIMENT, preferred_job_id="job-a", reason="x")


# ------------------------------------------------------------------ isolation from image Learning


def _image_rows() -> list[dict]:
    rows = []
    for index, (cfg, rating) in enumerate(((5.0, 2), (7.0, 4), (9.0, 3))):
        for repeat in range(2):
            rows.append(
                {
                    "run_id": f"img-{index}-{repeat}",
                    "timestamp": "2026-03-10T21:00:00",
                    "primary_sampler": "Euler a",
                    "primary_scheduler": "normal",
                    "primary_steps": 20,
                    "primary_cfg_scale": cfg,
                    "base_config": {"prompt": "portrait", "stage": "txt2img"},
                    "metadata": {
                        "record_kind": "learning_experiment_rating",
                        "experiment_id": "image-exp",
                        "experiment_name": "image-exp",
                        "variable_under_test": "CFG Scale",
                        "variant_value": cfg,
                        "user_rating": rating,
                        "image_path": f"img_{index}_{repeat}.png",
                        "stage": "txt2img",
                        "frozen_experiment": {
                            "snapshot": {"experiment_id": "image-exp"},
                            "executed_config": {
                                "txt2img": {"model": "m", "steps": 20, "cfg_scale": cfg}
                            },
                        },
                    },
                }
            )
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _add_video_reviews(path: Path) -> None:
    store = VideoReviewStore(path)
    for job, sha, label in (("job-a", SHA_A, "A"), ("job-b", SHA_B, "B")):
        store.save_clip(
            _target(job, sha, arm_label=label), _draft(5, "achieved", "perfect", scene_stability=5)
        )
    store.save_preference(
        experiment_id=EXPERIMENT,
        preferred_job_id="job-b",
        preferred_arm_label="B",
        preferred_artifact_sha256=SHA_B,
        reason="best",
    )


def test_image_recommendations_ignore_video_records_even_with_five_star_scores(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    _write(path, _image_rows())
    before = RecommendationEngine(path).recommend("portrait", "txt2img")
    _add_video_reviews(path)

    after = RecommendationEngine(path).recommend("portrait", "txt2img")

    assert before.recommendations, "the image-only fixture must produce a recommendation"
    assert after.to_ui_format() == before.to_ui_format()
    assert (after.evidence_tier, after.automation_eligible) == (
        before.evidence_tier,
        before.automation_eligible,
    )


def test_video_records_alone_produce_no_recommendation_evidence(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    _add_video_reviews(path)

    result = RecommendationEngine(path).recommend("portrait", "txt2img")

    assert result.recommendations == [] and result.evidence_tier == EVIDENCE_TIER_NO_EVIDENCE


def test_existing_image_rating_readers_and_analytics_do_not_see_video_records(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    _write(path, _image_rows())
    writer = LearningRecordWriter(path)
    before = (
        writer.get_ratings_for_experiment("image-exp"),
        writer.get_rating_details_for_experiment("image-exp"),
        writer.get_average_rating_for_variant("image-exp", 7.0),
        LearningAnalytics(writer).get_overall_summary(),
    )
    _add_video_reviews(path)
    writer = LearningRecordWriter(path)

    after = (
        writer.get_ratings_for_experiment("image-exp"),
        writer.get_rating_details_for_experiment("image-exp"),
        writer.get_average_rating_for_variant("image-exp", 7.0),
        LearningAnalytics(writer).get_overall_summary(),
    )

    assert after == before
    # ...and the video experiment id itself is invisible to every per-experiment image reader.
    assert writer.get_ratings_for_experiment(EXPERIMENT) == {}
    assert writer.get_rating_details_for_experiment(EXPERIMENT) == {}
    assert writer.get_average_rating_for_variant(EXPERIMENT, 1.0) is None
    assert not writer.is_image_rated(EXPERIMENT, "C:/out/a.mp4")
    assert LearningAnalytics(writer).get_experiment_summary(EXPERIMENT) is None
    assert LearningAnalytics(writer).get_overall_summary().total_ratings == 6  # only the image rows


def test_the_legacy_adapter_lists_video_rows_as_plain_records_without_a_rating(tmp_path):
    from src.gui_v2.adapters.learning_adapter_v2 import list_recent_learning_records

    path = tmp_path / "learning_records.jsonl"
    _add_video_reviews(path)

    rows = list_recent_learning_records(path, limit=10)

    assert len(rows) == 3 and all(row.metadata["record_kind"] == RECORD_KIND for row in rows)
    assert all("user_rating" not in row.metadata for row in rows)
