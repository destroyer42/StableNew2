"""PR-IMG-MODELS-158: ordinary Learning keeps its model-scoped capability restrictions for the Z-Image profile."""

from __future__ import annotations

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.model_policy import resolve_model_policy
from src.learning.experiment_execution import thaw_snapshot
from src.learning.model_capabilities import project_learning_capabilities

ZIMAGE = ZP.transformer.filename


def zimage_config():
    return {"txt2img": {"model": ZIMAGE, "steps": 9, "cfg_scale": 1.0, "width": 1024, "height": 1024}}


def sdxl_config():
    return {
        "txt2img": {
            "model": "ordinary.safetensors", "steps": 20, "cfg_scale": 7.0, "sampler_name": "Euler a",
            "scheduler": "normal", "width": 512, "height": 512,
        }
    }


def controller(config):
    result = LearningController(learning_state=LearningState())
    result._get_baseline_config = lambda: config
    return result


def test_zimage_ordinary_learning_exposes_no_adjustable_controls_and_says_why():
    policy = resolve_model_policy(ZIMAGE)
    caps = project_learning_capabilities(policy, ZIMAGE, "txt2img")
    assert caps.stage_supported and caps.variables == () and caps.parameters == ()
    reasons = dict(caps.unavailable)
    for name in ("steps", "cfg_scale", "sampler", "scheduler", "vae"):
        assert reasons[name] == "fixed"
    assert reasons["lora_strength"] == "lora_unsupported"
    assert reasons["model"] == "model_policy_comparison_unavailable"
    assert "Z-Image" in caps.target and "profile v1" in caps.target


@pytest.mark.parametrize("stage", ["img2img", "adetailer", "upscale"])
def test_zimage_unsupported_stages_are_unavailable(stage):
    caps = project_learning_capabilities(resolve_model_policy(ZIMAGE), ZIMAGE, stage)
    assert not caps.stage_supported and caps.variables == ()


@pytest.mark.parametrize("variable", ["CFG Scale", "Steps", "Sampler", "Scheduler", "VAE", "LoRA Strength", "Model"])
def test_the_capability_gate_refuses_every_variable_with_its_reason(variable):
    caps = project_learning_capabilities(resolve_model_policy(ZIMAGE), ZIMAGE, "txt2img")
    with pytest.raises(ValueError, match="unavailable"):
        caps.require(variable)


@pytest.mark.parametrize("variable", ["CFG Scale", "Steps"])
@pytest.mark.parametrize("source", ["custom", "current"])
def test_ordinary_prompt_sources_are_refused_before_any_plan_and_never_translated(variable, source):
    subject = controller(zimage_config())
    experiment = LearningExperiment(
        name="fixed",
        stage="txt2img",
        variable_under_test=variable,
        prompt_text="(weighted:1.2) <lora:adapter:0.8> BREAK prose",
        metadata={"prompt_source": source, "start_value": 2, "end_value": 3, "step_value": 1},
    )
    original_prompt = experiment.prompt_text
    with pytest.raises(ValueError, match="fixed|unavailable"):
        subject.build_plan(experiment)
    assert not experiment.execution_snapshot_json  # no preview exists, so nothing can be admitted
    assert experiment.prompt_text == original_prompt  # never silently adapted through another contract
    assert subject.learning_state.plan == []


def test_a_model_switch_never_rewrites_a_frozen_experiment_or_executed_njr():
    subject = controller(sdxl_config())
    experiment = LearningExperiment(
        name="ordinary",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="a quiet harbor",
        metadata={"start_value": 5.0, "end_value": 7.0, "step_value": 2.0},
    )
    subject.build_plan(experiment)
    frozen = experiment.execution_snapshot_json
    context = thaw_snapshot(frozen)["model_policy_context"]
    assert context["family"] != "z_image" and not context.get("profile_ref")

    subject._get_baseline_config = lambda: zimage_config()  # the operator selects Z-Image after Preview
    record = subject._build_variant_njr(subject.learning_state.plan[0], experiment)

    assert experiment.execution_snapshot_json == frozen
    assert record.base_model == "ordinary.safetensors"
    assert "model_profile" not in record.workload.backend_options.get("image", {})
    assert record.workload.config["txt2img"]["steps"] == 20  # the frozen baseline, not Z-Image's fixed values
