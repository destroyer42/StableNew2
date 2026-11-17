"""PR-REVIEW-LEARN-622: Retain / Discard as observational Learning evidence.

A Review decision records the image's generation settings (read from its embedded metadata, from the bytes) and a soft
score. The recommendation engine counts it as observational evidence only: once per image, by its rating when it has
one, by its latest decision otherwise, and never as controlled-experiment evidence. Nothing on disk is rewritten.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.gui.view_contracts.review_workspace_contract import ReviewWorkspaceSession, item_key
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    EVIDENCE_TIER_NO_EVIDENCE,
    EVIDENCE_TIER_REVIEW_ONLY,
    EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    RecommendationEngine,
)
from src.review import archive as arc
from src.review import review_evidence as evidence
from src.utils.image_metadata import build_contract_kv, write_image_metadata


def _png(
    path: Path,
    *,
    color: tuple[int, int, int],
    sampler: str | None = "Euler a",
    scheduler: str = "karras",
    steps: int = 28,
    cfg: float = 6.5,
    model: str = "m.safetensors",
    stage: str = "txt2img",
    embed: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path)
    if embed:
        config = {
            "sampler_name": sampler,
            "scheduler": scheduler,
            "steps": steps,
            "cfg_scale": cfg,
            "model": model,
        }
        payload = {"stage": stage, "stage_manifest": {"stage": stage, "config": config}}
        assert write_image_metadata(
            path, build_contract_kv(payload, job_id="job", run_id="run", stage=stage)
        )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _writer(tmp_path: Path) -> LearningRecordWriter:
    return LearningRecordWriter(tmp_path / "learning_records.jsonl")


def _decide(writer: LearningRecordWriter, path: Path, disposition: str, **extra):
    return evidence.save_disposition(writer, image_path=path, disposition=disposition, **extra)


def _rate(writer: LearningRecordWriter, path: Path, rating: int = 5, **extra):
    record = evidence.build_review_rating_record(
        {
            "image_path": str(path),
            "rating": rating,
            "base_prompt": "portrait",
            "stage": "txt2img",
            "sampler": "Euler a",
            "scheduler": "karras",
            "steps": 28,
            "cfg_scale": 6.5,
            **extra,
        }
    )
    assert writer.append_record(record) is not False
    return record


def _scored(writer: LearningRecordWriter) -> list[dict]:
    engine = RecommendationEngine(writer.records_path)
    return engine._score_records(engine._load_records())  # noqa: SLF001


def _recommend(writer: LearningRecordWriter):
    return RecommendationEngine(writer.records_path).recommend("portrait", "txt2img")


def _by_name(result) -> dict:
    return {rec.parameter_name: rec for rec in result.recommendations}


# --- the record -------------------------------------------------------------------------------------


def test_retain_and_discard_record_the_settings_read_from_the_image_and_a_soft_score(tmp_path):
    writer = _writer(tmp_path)
    kept = _png(tmp_path / "kept.png", color=(1, 1, 1), sampler="DPM++ 2M", steps=30, cfg=7.5)
    dropped = _png(tmp_path / "dropped.png", color=(2, 2, 2))
    before = (kept.read_bytes(), dropped.read_bytes())

    retain = _decide(writer, kept, "retain", source_job_id="job-1")
    discard = _decide(writer, dropped, "discard")

    assert (kept.read_bytes(), dropped.read_bytes()) == before
    assert (retain.primary_model, retain.primary_sampler, retain.primary_scheduler) == (
        "m.safetensors",
        "DPM++ 2M",
        "karras",
    )
    assert (retain.primary_steps, retain.primary_cfg_scale) == (30, 7.5)
    assert retain.metadata["user_rating"] == evidence.DISPOSITION_SOFT_SCORES["retain"] == 4.0
    assert discard.metadata["user_rating"] == evidence.DISPOSITION_SOFT_SCORES["discard"] == 2.0
    assert retain.metadata["record_kind"] == evidence.DISPOSITION_KIND
    assert retain.metadata["source"] == evidence.DISPOSITION_SOURCE
    assert retain.metadata["stage"] == "txt2img"
    assert retain.metadata["artifact_sha256"] == _sha(kept)


@pytest.mark.parametrize("disposition", ["rework", "cleared"])
def test_rework_and_cleared_are_not_scored(tmp_path, disposition):
    path = _png(tmp_path / "a.png", color=(3, 3, 3))
    record = evidence.build_disposition_record(image_path=path, disposition=disposition)
    assert "user_rating" not in record.metadata
    assert record.primary_sampler == "" and record.primary_steps == 0


def test_an_image_without_readable_settings_is_stored_without_them(tmp_path):
    writer = _writer(tmp_path)
    plain = _png(tmp_path / "plain.png", color=(4, 4, 4), embed=False)

    record = _decide(writer, plain, "retain")

    assert record.metadata["artifact_sha256"] == _sha(plain)
    assert (record.primary_model, record.primary_sampler, record.primary_steps) == ("", "", 0)
    assert len(writer.records_path.read_text().splitlines()) == 1


def test_settings_are_not_read_from_a_file_whose_bytes_are_not_the_reviewed_ones(tmp_path):
    reviewed = _png(tmp_path / "reviewed.png", color=(5, 5, 5), sampler="DDIM")
    digest = _sha(reviewed)
    _png(
        tmp_path / "reviewed.png", color=(6, 6, 6), sampler="Heun"
    )  # another file now holds the path

    record = evidence.build_disposition_record(
        image_path=reviewed, disposition="retain", artifact_sha256=digest
    )

    assert record.metadata["artifact_sha256"] == digest
    assert record.primary_sampler == ""


def test_a_decision_after_the_file_moved_keeps_the_settings_recorded_for_those_bytes(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "out" / "a.png", color=(7, 7, 7), sampler="Euler")
    digest = _sha(image)
    _decide(writer, image, "discard")
    archived = tmp_path / "elsewhere.png"
    image.replace(archived)

    later = _decide(
        writer, image, "retain", artifact_sha256=digest
    )  # the original path no longer exists

    assert (later.primary_sampler, later.primary_steps, later.primary_cfg_scale) == (
        "Euler",
        28,
        6.5,
    )
    assert later.metadata["user_rating"] == 4.0


# --- the engine -------------------------------------------------------------------------------------


def test_a_retain_and_a_discard_change_the_observational_evidence_for_their_settings(tmp_path):
    writer = _writer(tmp_path)
    _decide(
        writer, _png(tmp_path / "a.png", color=(1, 0, 0), sampler="DPM++ 2M", steps=30), "retain"
    )
    _decide(
        writer, _png(tmp_path / "b.png", color=(0, 1, 0), sampler="Euler a", steps=20), "discard"
    )

    result = _recommend(writer)
    found = _by_name(result)

    assert result.evidence_tier == EVIDENCE_TIER_REVIEW_ONLY
    assert result.automation_eligible is False
    assert found["sampler"].recommended_value == "DPM++ 2M"
    assert found["steps"].recommended_value == 30
    assert found["sampler"].mean_rating == 4.0
    assert [row["rating"] for row in _scored(writer)] == [4.0, 2.0]


def test_a_discard_alone_can_only_report_the_discarded_settings_with_their_low_score(tmp_path):
    writer = _writer(tmp_path)
    _decide(writer, _png(tmp_path / "a.png", color=(1, 0, 0)), "discard")

    scored = _scored(writer)

    assert [(row["record_kind"], row["rating"]) for row in scored] == [("review_disposition", 2.0)]


def test_an_image_with_a_rating_and_a_disposition_counts_once_by_its_rating(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "a.png", color=(1, 1, 0))
    _decide(writer, image, "discard")  # decided first
    _rate(writer, image, 5)
    other = _png(tmp_path / "b.png", color=(0, 1, 1))
    _rate(writer, other, 4)  # rated first
    _decide(writer, other, "retain")

    scored = _scored(writer)

    assert sorted((row["record_kind"], row["rating"]) for row in scored) == [
        ("review_tab_feedback", 4.0),
        ("review_tab_feedback", 5.0),
    ]
    assert _by_name(_recommend(writer))["sampler"].sample_count == 2


def test_a_legacy_rating_without_a_digest_is_matched_by_path(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "a.png", color=(9, 9, 0))
    legacy = _rate(writer, image, 5)
    rows = [json.loads(line) for line in writer.records_path.read_text().splitlines()]
    assert legacy.metadata["artifact_sha256"]
    del rows[0]["metadata"]["artifact_sha256"]
    writer.records_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    _decide(writer, image, "retain")

    assert [row["record_kind"] for row in _scored(writer)] == ["review_tab_feedback"]


def test_removing_the_rating_lets_the_decision_count_again(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "a.png", color=(1, 1, 0))
    _decide(writer, image, "retain")
    rated = _rate(writer, image, 5)
    assert [row["record_kind"] for row in _scored(writer)] == ["review_tab_feedback"]

    assert writer.remove_latest_review_feedback(run_id=rated.run_id) is True

    assert [row["record_kind"] for row in _scored(writer)] == ["review_disposition"]


def test_rework_contributes_nothing(tmp_path):
    writer = _writer(tmp_path)
    _decide(writer, _png(tmp_path / "a.png", color=(1, 0, 0)), "rework")

    assert _scored(writer) == []
    result = _recommend(writer)
    assert result.evidence_tier == EVIDENCE_TIER_NO_EVIDENCE and result.recommendations == []


def test_the_latest_disposition_per_image_wins(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "a.png", color=(1, 0, 0))
    _decide(writer, image, "retain")
    _decide(writer, image, "discard")
    assert [row["rating"] for row in _scored(writer)] == [2.0]
    _decide(writer, image, "retain")
    assert [row["rating"] for row in _scored(writer)] == [4.0]
    _decide(writer, image, "rework")
    assert (
        _scored(writer) == []
    )  # the operator's latest word is "not decided yet", so it is not evidence


def test_a_latest_cleared_row_removes_the_contribution_and_a_later_decision_restores_it(tmp_path):
    writer = _writer(tmp_path)
    image = _png(tmp_path / "a.png", color=(1, 0, 0))
    _decide(writer, image, "retain")
    _decide(writer, image, "cleared")
    assert _scored(writer) == []
    assert _recommend(writer).evidence_tier == EVIDENCE_TIER_NO_EVIDENCE

    _decide(writer, image, "discard")
    assert [row["rating"] for row in _scored(writer)] == [2.0]


def test_a_decision_is_keyed_by_the_bytes_not_the_path(tmp_path):
    writer = _writer(tmp_path)
    one = _png(tmp_path / "one.png", color=(1, 0, 0))
    copy = tmp_path / "copy.png"
    copy.write_bytes(one.read_bytes())
    _decide(writer, one, "retain")
    _decide(writer, copy, "discard")  # same bytes: one image, its latest decision

    assert [row["rating"] for row in _scored(writer)] == [2.0]


def test_dispositions_alone_never_reach_the_controlled_experiment_tier(tmp_path):
    writer = _writer(tmp_path)
    for index in range(6):
        _decide(
            writer,
            _png(tmp_path / f"{index}.png", color=(index, 9, 9), cfg=5.0 + index),
            "retain",
        )

    result = _recommend(writer)

    assert result.evidence_tier == EVIDENCE_TIER_REVIEW_ONLY
    assert result.evidence_tier not in (
        EVIDENCE_TIER_EXPERIMENT_STRONG,
        EVIDENCE_TIER_SPARSE_PLUS_REVIEW,
    )
    assert result.automation_eligible is False
    assert result.controlled_rating_count == 0 and result.qualifying_experiment_count == 0
    assert all(row["controlled_complete"] is False for row in _scored(writer))


def test_dispositions_next_to_controlled_evidence_stay_manual_only_or_are_left_out(tmp_path):
    writer = _writer(tmp_path)
    _decide(writer, _png(tmp_path / "a.png", color=(1, 0, 0)), "retain")

    def experiment(variant: float, rating: int) -> dict:
        frozen = {
            "snapshot": {"experiment_id": "exp"},
            "executed_config": {"txt2img": {"cfg_scale": variant}},
        }
        return {
            "timestamp": "2026-03-10T21:00:00",
            "primary_sampler": "Euler a",
            "primary_scheduler": "normal",
            "primary_steps": 20,
            "primary_cfg_scale": variant,
            "base_config": {"prompt": "portrait", "stage": "txt2img"},
            "metadata": {
                "record_kind": "learning_experiment_rating",
                "experiment_id": "exp",
                "variable_under_test": "CFG Scale",
                "variant_value": variant,
                "user_rating": rating,
                "stage": "txt2img",
                "frozen_experiment": frozen,
            },
        }

    with open(writer.records_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(experiment(6.0, 4)) + "\n")
    sparse = _recommend(writer)
    assert sparse.evidence_tier == EVIDENCE_TIER_SPARSE_PLUS_REVIEW
    assert sparse.automation_eligible is False

    with open(writer.records_path, "a", encoding="utf-8") as handle:
        for variant, rating in ((6.0, 4), (8.0, 5), (8.0, 5), (8.0, 4)):
            handle.write(json.dumps(experiment(variant, rating)) + "\n")
    strong = _recommend(writer)
    assert strong.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert strong.automation_eligible is True
    assert all(rec.sample_count > 0 for rec in strong.recommendations)
    # Strong evidence is the controlled rows alone: the decision's settings add nothing.
    assert _by_name(strong)["cfg_scale"].recommended_value == 8.0


def test_a_disposition_without_readable_settings_is_stored_and_ignored(tmp_path):
    writer = _writer(tmp_path)
    plain = _png(tmp_path / "plain.png", color=(4, 4, 4), embed=False)
    _decide(writer, plain, "retain")

    assert len(writer.records_path.read_text().splitlines()) == 1
    assert _scored(writer) == []
    assert _recommend(writer).evidence_tier == EVIDENCE_TIER_NO_EVIDENCE


def test_unset_settings_do_not_become_recommended_values(tmp_path):
    writer = _writer(tmp_path)
    _decide(
        writer,
        _png(tmp_path / "a.png", color=(1, 0, 0), sampler=None, scheduler="", cfg=0.0),
        "retain",
    )

    found = _by_name(_recommend(writer))

    assert set(found) == {"steps"}


def test_a_row_that_claims_a_score_but_is_a_rework_is_not_evidence(tmp_path):
    writer = _writer(tmp_path)
    record = _decide(writer, _png(tmp_path / "a.png", color=(1, 0, 0)), "retain")
    row = json.loads(writer.records_path.read_text().splitlines()[0])
    row["metadata"]["review_disposition"] = "rework"
    row["metadata"]["user_rating"] = 5.0
    row["run_id"] = record.run_id
    writer.records_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert _scored(writer) == []


# --- with the real Discard / Undo / Restore flow -----------------------------------------------------


def test_a_discard_moved_to_the_archive_keeps_its_settings_and_undo_removes_the_contribution(
    tmp_path,
):
    output = tmp_path / "output"
    writer = _writer(tmp_path)
    image = _png(output / "Pipeline" / "run" / "a.png", color=(8, 8, 8), sampler="Euler", steps=26)
    digest = _sha(image)

    def write(path, recorded_digest, job_id, disposition):
        evidence.save_disposition(
            writer,
            image_path=path,
            disposition=disposition,
            artifact_sha256=recorded_digest or None,
            source_job_id=job_id,
        )

    session = ReviewWorkspaceSession(
        runner=EditWorkRunner(BackgroundTaskCoordinator(run_inline=True), is_alive=lambda: True),
        records_path=lambda: writer.records_path,
        write_disposition=write,
        output_root=lambda: output,
        archive=lambda path, _digest: arc.archive_file(
            path, output_root=output, active_inputs=lambda: set(), protected_roots=()
        ),
        restore=lambda path, recorded, alternative: arc.restore_file(
            path, output_root=output, digest=recorded or None, use_alternative=alternative
        ),
    )
    session.set_items([image])

    assert session.decide(item_key(image), "discard")

    assert not image.exists() and _sha(arc.mirror_target(image, output)) == digest
    record = json.loads(writer.records_path.read_text().splitlines()[-1])
    assert (record["primary_sampler"], record["primary_steps"]) == ("Euler", 26)
    assert [row["rating"] for row in _scored(writer)] == [2.0]

    assert session.undo()  # restores the file, then appends a clearing row
    assert image.exists()
    assert (
        json.loads(writer.records_path.read_text().splitlines()[-1])["metadata"][
            "review_disposition"
        ]
        == "cleared"
    )
    assert _scored(writer) == []
