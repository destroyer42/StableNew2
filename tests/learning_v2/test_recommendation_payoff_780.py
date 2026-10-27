"""Recommendation provenance describes the existing tiers and refuses stale application."""

import json
import os
from types import SimpleNamespace

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.learning.recommendation_summary import build_recommendation_summary
from tests.integration.test_learning_review_recommendation_e2e import _DummyVar
from tests.learning_v2.test_model_comparison_140 import policy
from tests.learning_v2.test_profile_publication_660 import make_publication, records


def test_real_counts_and_changed_records_require_revalidation(tmp_path):
    path = tmp_path / "records.jsonl"
    rows = records(make_publication(tmp_path))
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    engine = RecommendationEngine(path, policy_resolver=policy)
    recs = engine.recommend("portrait", "txt2img", model="test.safetensors")
    assert recs.controlled_rating_count == 3
    assert recs.controlled_experiment_count == recs.qualifying_experiment_count == 1
    summary = build_recommendation_summary(recs, mode="apply_with_confirm")
    assert "3 usable controlled ratings" in summary.progress
    assert "test.safetensors" in summary.applies_to
    assert "Revalidate" in summary.apply_note
    var = _DummyVar(12)
    cards = SimpleNamespace(
        txt2img_card=SimpleNamespace(
            steps_var=var, model_var=_DummyVar("test.safetensors"), vae_var=_DummyVar("")
        )
    )
    controller = LearningController(
        LearningState(),
        learning_record_writer=LearningRecordWriter(path),
        pipeline_controller=SimpleNamespace(stage_cards_panel=cards),
    )
    controller._learning_policy_resolver = policy
    controller._get_baseline_config = lambda: {"txt2img": {"model": "test.safetensors"}}
    controller.set_automation_mode("apply_with_confirm")
    assert controller.apply_recommendations_to_pipeline(recs)
    assert var.get() == 30
    var.set(12)
    # Even a timestamp moved backwards invalidates the cache and the accepted patch.
    stamp = path.stat()
    path.write_text("", encoding="utf-8")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns - 1_000_000_000))
    assert not controller.apply_recommendations_to_pipeline(recs)
    assert var.get() == 12
    assert not engine.recommend("portrait", "txt2img", model="test.safetensors").recommendations


@pytest.mark.parametrize("count", [0, 1, 2])
def test_insufficient_evidence_summary_never_claims_automatic_or_profile_payoff(tmp_path, count):
    path = tmp_path / "records.jsonl"
    rows = records(make_publication(tmp_path))[:count]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = RecommendationEngine(path, policy_resolver=policy).recommend("portrait", "txt2img")
    assert not result.automation_eligible
    assert result.qualifying_experiment_count == 0
    summary = build_recommendation_summary(result, mode="auto_micro_experiment")
    assert not summary.apply_enabled
    if count:
        assert "Insufficient for automatic application or profile publication" in summary.apply_note
    else:
        assert "No recommendation yet" in summary.headline
