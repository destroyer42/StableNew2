import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.model_policy import (
    ControlMode,
    ControlPolicy,
    FeaturePolicy,
    Support,
    resolve_model_policy,
)
from src.learning.experiment_execution import ExperimentAdmissionService, thaw_snapshot
from src.learning.model_capabilities import (
    compatible_context,
    policy_context,
    project_learning_capabilities,
)
from src.learning.model_policy_service import compile_variant, validate_experiment
from src.learning.recommendation_engine import RecommendationEngine


def sdxl(model="ordinary.safetensors"):
    return resolve_model_policy(
        model,
        family_lookup=lambda _: SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
        ),
    )


def exact_resolver(name):
    return KleinLoraDecision(name, KleinLoraStatus.COMPATIBLE, "fixture exact metadata")


def make_controller(config=None):
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: config or klein_config()
    controller._learning_lora_resolver = exact_resolver
    return controller


@pytest.mark.parametrize(
    "stage,expected",
    [("txt2img", ("LoRA Strength",)), ("img2img", ()), ("adetailer", ()), ("upscale", ())],
)
def test_exact_stage_intersection(stage, expected):
    policy = resolve_model_policy(klein_config()["txt2img"]["model"])
    result = project_learning_capabilities(
        policy, "klein", stage, selected_loras=(("adapter", 0.8),), lora_resolver=exact_resolver
    )
    assert result.variables == expected
    assert result.stage_supported == (stage in {"txt2img", "img2img"})
    if stage == "img2img":
        assert dict(result.unavailable)["denoise_strength"] == "fixed"


@pytest.mark.parametrize("stage", ["txt2img", "img2img", "adetailer", "upscale"])
def test_sdxl_stage_contract_preserved(stage):
    from src.learning.stage_capabilities import get_variables_for_stage

    result = project_learning_capabilities(sdxl(), "ordinary", stage)
    assert list(result.variables) == get_variables_for_stage(stage)
    assert all(
        variable.replace(" ", "_").lower() in result.parameters for variable in result.variables
    )


@pytest.mark.parametrize("evidence", [None, "conflicting"])
def test_unknown_never_promotes_optional_features(evidence):
    policy = resolve_model_policy(
        "unknown",
        family_lookup=lambda _: SimpleNamespace(status=SimpleNamespace(value=evidence), family=None)
        if evidence
        else None,
    )
    result = project_learning_capabilities(policy, "unknown", "img2img", selected_loras=(("a", 1),))
    assert "CFG Scale" in result.variables and "Denoise Strength" in result.variables
    assert "LoRA Strength" not in result.variables and "Model" not in result.variables
    assert result.target.startswith("Learning Target: Unclassified")
    assert not project_learning_capabilities(policy, "unknown", "upscale").stage_supported


def test_future_policy_is_generic_and_immutable():
    policy = replace(
        sdxl(),
        policy_id="future",
        controls={"steps": ControlPolicy(ControlMode.FIXED, 9)},
        features={"lora": FeaturePolicy(Support.UNVERIFIED)},
        stage_controls={"img2img": {"denoise_strength": ControlPolicy(ControlMode.FIXED, 0.7)}},
    )
    result = project_learning_capabilities(policy, "future", "img2img")
    assert "Steps" not in result.variables and "Denoise Strength" not in result.variables
    with pytest.raises(AttributeError):
        result.variables = ()
    fixed_lora = replace(sdxl(), controls={"lora_strength": ControlPolicy(ControlMode.FIXED, 0.8)})
    assert (
        "LoRA Strength"
        not in project_learning_capabilities(fixed_lora, "future", "txt2img").variables
    )


def test_model_candidates_must_have_the_same_evidenced_contract():
    baseline = {"txt2img": {"model": "ordinary"}}
    controller = make_controller(baseline)
    controller._learning_policy_resolver = (
        lambda name: sdxl(name) if name in {"ordinary", "peer"} else resolve_model_policy(name)
    )
    experiment = LearningExperiment(stage="txt2img", variable_under_test="Model")
    validate_experiment(controller, experiment, baseline, ["peer"])
    for candidate in ("unknown", klein_config()["txt2img"]["model"]):
        with pytest.raises(ValueError, match="incompatible policy"):
            validate_experiment(controller, experiment, baseline, [candidate])
    assert not compatible_context(
        policy_context(resolve_model_policy("x"), "x", "txt2img"),
        policy_context(resolve_model_policy("y"), "y", "txt2img"),
    )


@pytest.mark.parametrize(
    "variable,stage",
    [
        ("CFG Scale", "txt2img"),
        ("Steps", "txt2img"),
        ("Sampler", "txt2img"),
        ("Scheduler", "txt2img"),
        ("VAE", "txt2img"),
        ("Denoise Strength", "img2img"),
        ("LoRA Strength", "img2img"),
        ("Steps", "adetailer"),
        ("Upscale Factor", "upscale"),
    ],
)
def test_api_bypass_rejects_before_njr_or_admission(variable, stage):
    controller = make_controller()
    experiment = LearningExperiment(
        name="old", stage=stage, variable_under_test=variable, baseline_config=klein_config()
    )
    restored = LearningExperiment.from_dict(experiment.to_dict())
    value = {"name": "adapter", "weight": 0.8} if variable == "LoRA Strength" else 7
    with pytest.raises(ValueError, match="unavailable"):
        ExperimentAdmissionService().compile_all(
            [value],
            lambda v: controller._build_variant_njr(LearningVariant(param_value=v), restored),
        )
    assert restored.variable_under_test == variable


def lora_experiment():
    return LearningExperiment(
        name="qualified",
        stage="txt2img",
        prompt_text="portrait <lora:adapter:0.8>",
        variable_under_test="LoRA Strength",
        metadata={
            "lora_name": "adapter",
            "strength_start": 0.4,
            "strength_end": 0.8,
            "strength_step": 0.4,
        },
    )


def test_frozen_klein_lora_compiles_canonical_settings_and_ignores_live_model():
    config = klein_config()
    config["txt2img"].update(
        steps=20, cfg_scale=7, sampler_name="wrong", scheduler="wrong", vae="wrong"
    )
    controller = make_controller(config)
    experiment = lora_experiment()
    controller.build_plan(experiment)
    frozen = thaw_snapshot(experiment.execution_snapshot_json)
    context = frozen["model_policy_context"]
    assert context["profile_ref"] == latest_klein_profile().reference()
    assert context["selected_model"] == latest_klein_profile().transformer.filename
    controller._get_baseline_config = lambda: {"txt2img": {"model": "changed"}}
    experiment.variable_under_test = "Steps"
    experiment.stage = "img2img"
    record = controller._build_variant_njr(controller.learning_state.plan[0], experiment)
    assert record.workload.config["learning_variable"] == "LoRA Strength"
    assert record.workload.backend_options["image"]["model_profile"] == context["profile_ref"]
    assert record.workload.config["txt2img"]["steps"] == 4
    assert record.workload.config["txt2img"]["cfg_scale"] == 1
    assert record.workload.config["txt2img"]["sampler_name"] == "Euler"
    assert record.workload.config["txt2img"]["scheduler"] == "Beta"
    assert record.workload.config["txt2img"]["vae"] == ""
    assert "<lora:adapter:0.4>" in record.positive_prompt
    from src.learning.value_identity import plain_value

    assert (
        plain_value(
            record.workload.metadata["frozen_experiment"]["snapshot"]["model_policy_context"]
        )
        == context
    )


@pytest.mark.parametrize(
    "status",
    [KleinLoraStatus.UNVERIFIED, KleinLoraStatus.INCOMPATIBLE, KleinLoraStatus.CONFLICTING],
)
def test_non_admissible_lora_is_never_offered_or_compiled(status):
    controller = make_controller()
    controller._learning_lora_resolver = lambda name: KleinLoraDecision(
        name, status, "rejected evidence"
    )
    policy = resolve_model_policy(klein_config()["txt2img"]["model"])
    result = project_learning_capabilities(
        policy,
        "klein",
        "txt2img",
        selected_loras=(("adapter", 0.8),),
        lora_resolver=controller._learning_lora_resolver,
    )
    assert not result.variables
    with pytest.raises(ValueError, match="unavailable"):
        controller.build_plan(lora_experiment())


def test_lora_count_and_pending_style_block_projection_and_preview():
    policy = resolve_model_policy(klein_config()["txt2img"]["model"])
    for selection, pending in [((("a", 0.8), ("style", 0.8)), False), ((("a", 0.8),), True)]:
        assert not project_learning_capabilities(
            policy,
            "klein",
            "txt2img",
            selected_loras=selection,
            lora_resolver=exact_resolver,
            style_lora_pending=pending,
        ).variables
    controller = make_controller()
    controller._learning_prompt_snapshot = lambda: SimpleNamespace(
        loras=(("adapter", 0.8),), style_lora=("style", 0.8), style_lora_pending=False
    )
    with pytest.raises(ValueError, match="unavailable"):
        controller.build_plan(lora_experiment())


def test_compile_normalization_cannot_erase_variable(monkeypatch):
    from src.learning import model_policy_service as service

    config = {"txt2img": {"steps": 10}}
    experiment = LearningExperiment(variable_under_test="Steps")
    monkeypatch.setattr(
        service, "apply_model_compile_policy", lambda cfg: cfg["txt2img"].update(steps=4)
    )
    with pytest.raises(ValueError, match="overwritten"):
        compile_variant(config, experiment)


def test_ordinary_compile_is_noop():
    config = {"txt2img": {"model": "ordinary", "steps": 10}}
    compile_variant(config, LearningExperiment(variable_under_test="Steps"))
    assert config == {"txt2img": {"model": "ordinary", "steps": 10}}


def test_exact_recommendation_requires_frozen_profile_and_valid_parameter(tmp_path):
    from tests.learning_v2.test_recommendation_structured_values import _controlled

    policy = resolve_model_policy(klein_config()["txt2img"]["model"])
    capability = project_learning_capabilities(
        policy,
        klein_config()["txt2img"]["model"],
        "txt2img",
        selected_loras=(("adapter", 0.8),),
        lora_resolver=exact_resolver,
    )
    context = json.loads(capability.context_json)
    records = [_controlled({"name": "adapter", "weight": weight}, 5) for weight in (0.4, 0.8, 0.8)]
    engine = RecommendationEngine(tmp_path / "ratings.jsonl")
    engine._load_records = lambda: records
    result = engine.recommend("portrait", "txt2img", target_capabilities=capability)
    assert not result.recommendations and not result.automation_eligible
    for record in records:
        record["metadata"]["frozen_experiment"]["snapshot"]["model_policy_context"] = context
    engine._cache = None
    result = engine.recommend("portrait", "txt2img", target_capabilities=capability)
    assert [r.parameter_name for r in result.recommendations] == ["lora_strength"]
    assert result.automation_eligible
    bad = json.loads(json.dumps(context))
    bad["profile_ref"]["version"] = 1
    for record in records:
        record["metadata"]["frozen_experiment"]["snapshot"]["model_policy_context"] = bad
    engine._cache = None
    assert not engine.recommend(
        "portrait", "txt2img", target_capabilities=capability
    ).automation_eligible


def test_sdxl_apply_and_atomic_invalid_patch():
    controller = make_controller({"txt2img": {"model": "ordinary"}})
    controller._learning_policy_resolver = sdxl
    cfg = Mock()
    cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=cfg))
    controller.pipeline_controller = SimpleNamespace(stage_cards_panel=cards)
    controller.set_automation_mode("apply_with_confirm")
    assert controller.apply_recommendations_to_pipeline([{"parameter": "cfg_scale", "value": 8}])
    cfg.set.assert_called_once_with(8)
    cfg.reset_mock()
    assert not controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 8}, {"parameter": "denoise_strength", "value": 0.2}]
    )
    cfg.set.assert_not_called()


def klein_config():
    return {
        "txt2img": {
            "model": latest_klein_profile().transformer.filename,
            "steps": 4,
            "cfg_scale": 1.0,
            "width": 768,
            "height": 1024,
        }
    }


def test_programmatic_klein_cfg_preview_rejected():
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: klein_config()
    experiment = LearningExperiment(
        name="fixed",
        variable_under_test="CFG Scale",
        stage="txt2img",
        metadata={"start_value": 2, "end_value": 3, "step_value": 1},
    )
    with pytest.raises(ValueError, match="fixed|unavailable"):
        controller.build_plan(experiment)


@pytest.mark.parametrize("mode", ["apply_with_confirm", "auto_micro_experiment"])
def test_injected_klein_recommendation_does_not_mutate(mode):
    cfg = Mock()
    cards = SimpleNamespace(
        txt2img_card=SimpleNamespace(
            cfg_var=cfg, model_var=SimpleNamespace(get=lambda: klein_config()["txt2img"]["model"])
        )
    )
    controller = LearningController(
        learning_state=LearningState(), pipeline_controller=SimpleNamespace(stage_cards_panel=cards)
    )
    controller._get_baseline_config = lambda: klein_config()
    controller.set_automation_mode(mode)
    assert not controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 7}]
    )
    cfg.set.assert_not_called()


def test_klein_recommender_rejects_cross_model_fixed_evidence(tmp_path):
    engine = RecommendationEngine(tmp_path / "absent.jsonl")
    engine._should_reload_cache = lambda: False
    engine._cache = {
        "scored_records": [
            {
                "stage": "txt2img",
                "record_kind": "legacy",
                "rating": 5,
                "primary_cfg_scale": 7,
                "primary_steps": 20,
                "primary_sampler": "Euler",
                "primary_scheduler": "normal",
                "metadata": {},
                "model": "sdxl",
                "timestamp": 1,
            }
        ]
    }
    result = engine.recommend("portrait", "txt2img", model=klein_config()["txt2img"]["model"])
    assert not result.recommendations
