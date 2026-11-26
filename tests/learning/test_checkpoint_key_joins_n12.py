"""N12: Learning joins old and new records on the canonical checkpoint key, without rewriting a record."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.controller.pipeline_controller_services.queue_submission_service import (
    QueueSubmissionService,
)
from src.curation.learning_bridge import CurationLearningBridge, CurationLearningContext
from src.learning import prompt_model_matrix as pmm
from src.learning.learning_record import LearningRecord
from src.learning.recommendation_engine import RecommendationEngine
from src.utils.checkpoint_identity import checkpoint_key

FORGE_TITLE = "sdxl\\juggernautXL_v9.safetensors [a1b2c3d4e5]"
PICKER_COLLISION_LABEL = "juggernautXL_v9 [sdxl\\juggernautXL_v9.safetensors [a1b2c3d4e5]]"
DISPLAY = "JuggernautXL_v9.safetensors"
A1111_NAME = "juggernautXL_v9"


def _record(model: str, *, rating: int = 5) -> dict:
    return {
        "run_id": f"run-{model}-{rating}",
        "timestamp": "2026-11-01T12:00:00",
        "base_config": {"prompt": "portrait studio", "stage": "txt2img", "model": model},
        "variant_configs": [],
        "randomizer_mode": "",
        "randomizer_plan_size": 0,
        "primary_model": model,
        "primary_sampler": "Euler a",
        "primary_scheduler": "karras",
        "primary_steps": 20,
        "primary_cfg_scale": 7.0,
        "metadata": {"user_rating": rating, "stage": "txt2img"},
    }


@pytest.mark.parametrize("stored", [FORGE_TITLE, DISPLAY, A1111_NAME, PICKER_COLLISION_LABEL])
@pytest.mark.parametrize(
    "queried", [FORGE_TITLE, DISPLAY, "C:\\webui\\models\\sdxl\\juggernautXL_v9.safetensors"]
)
def test_recommendation_context_matches_every_spelling_of_one_checkpoint(tmp_path, stored, queried):
    engine = RecommendationEngine(tmp_path / "learning_records.jsonl")
    (scored,) = engine._score_records([_record(stored)])
    query = engine._build_query_context("portrait studio", "txt2img", model=queried)
    _weight, rationale = engine._compute_context_weight(scored, query, "portrait studio")
    assert "model-match" in rationale


def test_recommendation_context_still_separates_different_checkpoints(tmp_path):
    engine = RecommendationEngine(tmp_path / "learning_records.jsonl")
    (scored,) = engine._score_records([_record(FORGE_TITLE)])
    query = engine._build_query_context(
        "portrait studio", "txt2img", model="ponyDiffusion_v6.safetensors"
    )
    _weight, rationale = engine._compute_context_weight(scored, query, "portrait studio")
    assert "model-mismatch" in rationale


def test_old_records_join_at_read_time_and_are_never_rewritten(tmp_path):
    path = tmp_path / "learning_records.jsonl"
    lines = [json.dumps(_record(FORGE_TITLE)), json.dumps(_record(DISPLAY, rating=4))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = path.read_bytes()

    engine = RecommendationEngine(path)
    engine.recommend("portrait studio", "txt2img", model=A1111_NAME)
    records = [LearningRecord.from_json(line) for line in lines]

    assert path.read_bytes() == before
    assert {record.checkpoint_key for record in records} == {"juggernautxl_v9"}
    # The derived key is read-time only: a record serialises exactly the fields it always did.
    assert "checkpoint_key" not in json.loads(records[0].to_json())
    assert records[0].primary_model == FORGE_TITLE


def test_curation_records_carry_the_same_key_as_pipeline_records():
    item = SimpleNamespace(
        model=DISPLAY, sampler="Euler a", scheduler="", steps=20, cfg_scale=7.0, rating=0,
        positive_prompt="p", negative_prompt="", width=64, height=64, stage="txt2img", artifact_path="",
    )  # fmt: skip
    candidate = SimpleNamespace(
        candidate_id="c1", root_candidate_id="c1", parent_candidate_id=None, stage="scout", model_name="",
    )  # fmt: skip
    event = SimpleNamespace(decision="advanced_to_refine", reason_tags=[], notes="")
    context = CurationLearningContext(
        workflow_id="wf",
        candidate=candidate,
        experiment=SimpleNamespace(prompt_hash=""),
        item=item,
        event=event,
    )  # type: ignore[arg-type]
    record = CurationLearningBridge.build_learning_record(context)
    assert record.primary_model == DISPLAY  # written as the curation surface spelled it
    assert record.checkpoint_key == checkpoint_key(FORGE_TITLE)


def test_matrix_runtime_readback_is_the_canonical_key():
    snapshot = {"study_type": pmm.STUDY_TYPE}
    payload = {"config": {"override_settings": {"sd_model_checkpoint": PICKER_COLLISION_LABEL}}}
    assert pmm.execution_evidence(snapshot, payload, {}) == {
        "runtime_model_readback": "juggernautxl_v9"
    }
    assert pmm.execution_evidence(snapshot, {"model": "flux1-dev-Q8_0.gguf"}, {}) == {
        "runtime_model_readback": "flux1-dev-q8_0"
    }


def test_queue_groups_every_spelling_of_one_checkpoint_together():
    def job(model: str, tag: str) -> SimpleNamespace:
        return SimpleNamespace(config={"txt2img": {"model": model}}, tag=tag)

    records = [
        job(FORGE_TITLE, "a"),
        job("ponyDiffusion_v6.safetensors", "b"),
        job(DISPLAY, "c"),
        job("aaa_first.safetensors", "d"),
        job(A1111_NAME, "e"),
    ]
    ordered = [r.tag for r in QueueSubmissionService(job_service=None).sort_jobs_by_model(records)]  # type: ignore[arg-type]
    assert ordered == ["d", "a", "c", "e", "b"]


def test_a_warning_the_picker_showed_is_found_for_every_spelling_the_njr_records():
    from src.image_backends import model_policy_warnings as mpw
    from src.pipeline.policy_warnings import CODE_IMAGE_MODEL_UNQUALIFIED, PolicyWarning

    warning = PolicyWarning(
        CODE_IMAGE_MODEL_UNQUALIFIED, "juggernautXL_v9", "Unqualified", "why", "fix"
    )
    mpw.publish_shown_warnings({FORGE_TITLE: warning})
    try:
        for spelling in (FORGE_TITLE, DISPLAY, A1111_NAME, PICKER_COLLISION_LABEL):
            assert mpw.shown_warning_for(spelling) is warning
        assert mpw.shown_warning_for("ponyDiffusion_v6.safetensors") is None
    finally:
        mpw.publish_shown_warnings({})
