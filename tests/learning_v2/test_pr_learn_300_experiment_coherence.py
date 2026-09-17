"""Focused PR-LEARN-300 experiment integrity coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.experiment_execution import ExperimentAdmissionService
from src.learning.recommendation_engine import (
    EVIDENCE_TIER_EXPERIMENT_STRONG,
    RecommendationEngine,
)


def _controlled_record(value: float, rating: int) -> dict[str, object]:
    config = {"txt2img": {"model": "model-a", "steps": 20, "cfg_scale": value}}
    return {
        "timestamp": "2026-09-16T12:00:00",
        "primary_model": "model-a",
        "primary_sampler": "Euler a",
        "primary_scheduler": "normal",
        "primary_steps": 20,
        "primary_cfg_scale": value,
        "base_config": {"prompt": "portrait", "stage": "txt2img"},
        "metadata": {
            "record_kind": "learning_experiment_rating",
            "experiment_id": "exp-stable",
            "variable_under_test": "CFG Scale",
            "variant_value": value,
            "user_rating": rating,
            "frozen_experiment": {
                "snapshot": {"experiment_id": "exp-stable"},
                "executed_config": config,
            },
        },
    }


def test_admission_compiles_every_record_before_one_submit() -> None:
    service = ExperimentAdmissionService()
    variants = ["a", "b"]
    compiled: list[str] = []
    admission = service.compile_all(
        variants,
        lambda value: compiled.append(value) or SimpleNamespace(job_id=value),
    )
    job_service = SimpleNamespace(calls=[])
    job_service.submit_njrs = lambda records, policy: job_service.calls.append((records, policy)) or [
        record.job_id for record in records
    ]

    assert service.submit(admission, job_service) == ["a", "b"]
    assert compiled == ["a", "b"]
    assert len(job_service.calls) == 1
    assert [record.job_id for record in job_service.calls[0][0]] == ["a", "b"]


def test_admission_does_not_submit_when_any_compile_fails() -> None:
    service = ExperimentAdmissionService()
    job_service = SimpleNamespace(calls=[])
    job_service.submit_njrs = lambda records, policy: job_service.calls.append(records)

    with pytest.raises(ValueError, match="invalid variant"):
        service.compile_all(
            ["first", "bad"],
            lambda value: (_ for _ in ()).throw(ValueError("invalid variant"))
            if value == "bad"
            else SimpleNamespace(job_id=value),
        )
    assert job_service.calls == []


def test_preview_snapshot_is_stable_and_background_completion_keeps_selection() -> None:
    state = LearningState()
    experiment = LearningExperiment(
        name="My experiment",
        experiment_id="exp-stable",
        variable_under_test="CFG Scale",
        prompt_text="portrait",
        values=[6.0, 7.0],
    )
    state.current_experiment = experiment
    controller = LearningController(state)
    controller._get_baseline_config = lambda: {"txt2img": {"cfg_scale": 7.0}}  # type: ignore[method-assign]
    controller.build_plan(experiment)
    preview = experiment.execution_snapshot_json
    controller._get_baseline_config = lambda: {"txt2img": {"cfg_scale": 99.0}}  # type: ignore[method-assign]

    selected, background = state.plan[0], state.plan[-1]
    state.selected_variant = selected
    calls: list[LearningVariant] = []
    controller._review_panel = SimpleNamespace(display_variant_results=lambda variant, *_: calls.append(variant))
    controller._on_variant_job_completed(background, {"images": ["background.png"]})

    assert experiment.execution_snapshot_json == preview
    assert calls == []
    assert selected.experiment_id == "exp-stable"
    assert background.variant_id.startswith("exp-stable:")


def test_controlled_evidence_only_recommends_the_variable_under_test(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    records = [_controlled_record(6.0, 3), _controlled_record(7.0, 5), _controlled_record(7.0, 5)]
    records_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    result = RecommendationEngine(records_path).recommend(
        "portrait", "txt2img", model="model-a", width=768, height=1024
    )

    assert result.evidence_tier == EVIDENCE_TIER_EXPERIMENT_STRONG
    assert result.automation_eligible is True
    assert [rec.parameter_name for rec in result.recommendations] == ["cfg_scale"]
    assert result.recommendations[0].recommended_value == 7.0


def test_incomplete_historical_experiment_cannot_claim_controlled_evidence(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    historical = _controlled_record(7.0, 5)
    historical["metadata"].pop("frozen_experiment")  # type: ignore[index]
    records_path.write_text(json.dumps(historical) + "\n", encoding="utf-8")

    result = RecommendationEngine(records_path).recommend("portrait", "txt2img")

    assert not result.recommendations
    assert result.evidence_tier == "no_evidence"
    assert result.automation_eligible is False
