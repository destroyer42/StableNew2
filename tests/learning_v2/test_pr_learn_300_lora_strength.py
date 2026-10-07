from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.experiment_naming import build_learning_filename_prefix
from src.learning.lora_variant import extract_lora_tokens, validate_executed_lora
from src.prompting.prompt_optimizer_service import optimize_with_config

BASE_LORAS = "<lora:BetterThanWords:0.55> <lora:Heroes:0.43> <lora:WeaponPoseHelper:0.53>"
PROMPT = f"battle scene, {BASE_LORAS} <lora:add-detail-xl:0.8>, cinematic"
LORA = "add-detail-xl"


def _controller(prompt: str = PROMPT):
    state = LearningState()
    experiment = LearningExperiment(
        name="lora",
        stage="txt2img",
        variable_under_test="LoRA Strength",
        prompt_text=prompt,
    )
    state.current_experiment = experiment
    app = Mock()
    card = Mock()
    card.to_config_dict.return_value = {
        "txt2img": {
            "model": "m.safetensors",
            "vae": "",
            "sampler_name": "Euler a",
            "scheduler": "normal",
            "steps": 20,
            "cfg_scale": 7.0,
            "width": 512,
            "height": 512,
            "seed": 12345,
            "clip_skip": 2,
        },
        "pipeline": {"txt2img_enabled": True},
    }
    app._get_stage_cards_panel.return_value = Mock(
        txt2img_card=card, img2img_card=Mock(), adetailer_card=Mock(), upscale_card=Mock()
    )
    controller = LearningController(
        learning_state=state, pipeline_controller=Mock(), app_controller=app
    )
    from types import SimpleNamespace

    from src.image_backends.model_policy import resolve_model_policy

    controller._learning_policy_resolver = lambda name: resolve_model_policy(name, family_lookup=lambda _: SimpleNamespace(
        status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")))
    return controller, experiment


def _variant(weight: float) -> LearningVariant:
    return LearningVariant(
        experiment_id="e",
        variant_id=f"e:{weight}",
        param_value={"name": LORA, "weight": weight},
    )


@pytest.mark.parametrize("weight", [0.0, 0.25, 0.5, 0.8, 1.0, 2.0])
def test_variant_njr_executes_requested_lora_weight(weight: float) -> None:
    controller, experiment = _controller()
    njr = controller._build_variant_njr(_variant(weight), experiment)
    prompt = njr.positive_prompt
    tokens = extract_lora_tokens(prompt)
    selected = [w for n, w in tokens if n == LORA]
    assert BASE_LORAS in prompt
    if weight == 0.0:
        assert selected == []
        assert LORA not in [t.name for t in njr.provenance.lora_tags]
    else:
        assert selected == [str(weight)]
        assert (LORA, weight) in [(t.name, t.weight) for t in njr.provenance.lora_tags]
    if weight != 0.8:
        assert "add-detail-xl:0.8" not in prompt
    assert njr.workload.config["learning_variant_value"] == {"name": LORA, "weight": weight}
    assert experiment.prompt_text == PROMPT  # shared frozen baseline is untouched


def test_optimizer_output_keeps_exact_controlled_weight() -> None:
    controller, experiment = _controller()
    prompt = controller._build_variant_njr(_variant(0.25), experiment).positive_prompt
    result = optimize_with_config(prompt, "", config_payload={"enabled": True}, pipeline_name=None)
    assert validate_executed_lora({"lora_override": {"name": LORA, "weight": 0.25}}, result.positive.optimized_prompt) == ""


def _complete(controller, experiment, weight, final_prompt, profile="guarded"):
    variant = _variant(weight)
    variant.executed_config = {"lora_override": {"name": LORA, "weight": weight}}
    controller.learning_state.plan = [variant]
    result = {
        "images": ["a.png"],
        "variants": [
            {"final_prompt": final_prompt, "runtime_admission": {"launch_profile": profile}}
        ],
    }
    controller._on_variant_job_completed(variant, result)
    return variant


def test_executed_prompt_disagreeing_with_intended_weight_is_uncontrolled() -> None:
    controller, experiment = _controller()
    variant = _complete(controller, experiment, 2.0, f"x {BASE_LORAS} <lora:add-detail-xl:0.8>")
    assert variant.status == "uncontrolled"
    assert variant.execution_metadata["controlled_evidence_valid"] is False
    assert variant.execution_metadata["variable_validation_reason"] == "lora_strength_mismatch"


def test_missing_prompt_readback_and_duplicate_token_are_invalid() -> None:
    assert validate_executed_lora({"lora_override": {"name": LORA, "weight": 0.5}}, "") == "lora_readback_unavailable"
    dup = "<lora:add-detail-xl:0.5> <lora:add-detail-xl:0.5>"
    assert validate_executed_lora({"lora_override": {"name": LORA, "weight": 0.5}}, dup) == "lora_strength_mismatch"


def test_matching_executed_prompt_is_valid_and_restart_boundary_is_flagged() -> None:
    controller, experiment = _controller()
    ok = _complete(controller, experiment, 0.5, f"{BASE_LORAS} <lora:add-detail-xl:0.5>")
    assert ok.execution_metadata["variable_validation_reason"] == "valid"
    later = _complete(
        controller, experiment, 1.0, f"{BASE_LORAS} <lora:add-detail-xl:1.0>", profile="other"
    )
    assert later.status == "uncontrolled"
    assert later.execution_metadata["variable_validation_reason"] == "backend_restart_boundary"


def test_composite_lora_filename_label() -> None:
    prefix = build_learning_filename_prefix(
        stage="txt2img",
        variable="LoRA Strength",
        value={"name": LORA, "weight": 0.25},
        variant_index=1,
    )
    assert "add-detail-xl-0p25" in prefix
    assert "Frozen" not in prefix and "{" not in prefix


def test_historical_lora_record_without_executed_proof_is_not_recommendation_evidence() -> None:
    from src.learning.recommendation_engine import RecommendationEngine

    def record(reason):
        frozen = {
            "snapshot": {},
            "executed_config": {"lora_override": {"name": LORA, "weight": 2.0}},
            "controlled_evidence_valid": True,
        }
        if reason:
            frozen["variable_validation_reason"] = reason
        return {
            "metadata": {
                "record_kind": "learning_experiment_rating",
                "experiment_id": "21571ab0d0a04cbc8d4c0986755628a0",
                "variable_under_test": "LoRA Strength",
                "variant_value": {"name": LORA, "weight": 2.0},
                "user_rating": 5,
                "frozen_experiment": frozen,
            }
        }

    engine = RecommendationEngine.__new__(RecommendationEngine)
    assert engine._score_records([record(None)]) == []
    assert len(engine._score_records([record("valid")])) == 1
