"""PR-IMG-MODELS-158: every Model Comparison arm is prepared independently and verified before any admission."""

from __future__ import annotations

import copy
import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.learning.model_comparison as comparison_module
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.image_backends.model_policy import prepare_candidate_baseline
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.model_comparison import build_comparison_snapshot, digest, frozen_arm
from src.pipeline.compile_evidence import CompileEvidence
from tests.learning_v2.test_model_comparison_140 import (
    KLEIN,
    SDXL,
    baseline,
    controller_for,
    experiment,
    family,
)

ZIMAGE = ZP.transformer.filename
PROSE = "(red dress:1.2) in [[place]] BREAK soft window light"


def shared_baseline(**pipeline):
    """An ordinary SDXL-authored shared baseline at a geometry every candidate qualifies for."""
    config = baseline()
    config["txt2img"].update(
        width=1024, height=1024, subseed=-1, subseed_strength=0.0, clip_skip=2, vae="sdxl_vae.safetensors"
    )
    config["pipeline"].update(apply_global_negative_txt2img=True, **pipeline)
    config["global_negative_prompt"] = "global negative"
    config["prompt_optimizer"] = {"enabled": True}
    return config


def study(tmp_path, *, models, text=PROSE, samples=1):
    exp = experiment(tmp_path, models=models)
    exp.images_per_value = samples
    path = tmp_path / "pack.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["pack_data"]["slots"][0].update(
        text=text, negative="bad", positive_embeddings=[], negative_embeddings=[]
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    return exp


def build(tmp_path, *, models, config=None, **kwargs):
    exp = study(tmp_path, models=models, **kwargs)
    evidence = CompileEvidence(family_lookup=family)
    return exp, build_comparison_snapshot(exp, config or shared_baseline(), evidence=evidence)


def test_sdxl_and_zimage_arms_are_prepared_independently_from_one_source(tmp_path):
    config = shared_baseline()
    original = copy.deepcopy(config)
    _, snapshot = build(tmp_path, models=[SDXL, ZIMAGE], config=config)
    assert config == original  # the shared baseline is never normalized in place
    sdxl, zimage = snapshot["model_comparison"]["arms"]
    assert sdxl["source_intent_sha256"] == zimage["source_intent_sha256"]
    assert digest(snapshot["model_comparison"]["source_intent"]) == sdxl["source_intent_sha256"]
    assert sdxl["shared_geometry"] == zimage["shared_geometry"] == {"width": 1024, "height": 1024}

    # SDXL keeps the operator's baseline (and the executor still owns its global negative).
    section = sdxl["effective_config"]["txt2img"]
    assert (section["sampler_name"], section["scheduler"], section["steps"], section["cfg_scale"]) == (
        "DPM++ 2M", "Karras", 30, 7.0,
    )
    assert sdxl["effective_config"]["pipeline"]["apply_global_negative_txt2img"] is True
    assert "(red dress:1.2)" in sdxl["executor_base_positive_prompt"]

    # Z-Image gets only its own immutable values; nothing from the SDXL baseline is a "requirement".
    section = zimage["effective_config"]["txt2img"]
    assert (section["sampler_name"], section["scheduler"], section["steps"], section["cfg_scale"]) == (
        ZP.sampler, ZP.scheduler, ZP.steps, ZP.cfg_scale,
    )
    assert section["distilled_cfg_scale"] == ZP.distilled_cfg_scale
    assert section["vae"] == "" and section["clip_skip"] == 1
    assert (section["width"], section["height"]) == (1024, 1024)
    assert zimage["effective_config"]["global_negative_prompt"] == ""
    assert zimage["effective_config"]["pipeline"]["apply_global_negative_txt2img"] is False
    assert zimage["effective_config"]["prompt_optimizer"] == {"enabled": False}
    assert zimage["effective_backend_options"]["image"]["model_profile"] == ZP.reference()
    assert zimage["model_policy_context"]["profile_ref"] == ZP.reference()
    assert ":1.2" not in zimage["executor_base_positive_prompt"]
    assert "BREAK" not in zimage["executor_base_positive_prompt"]
    assert zimage["executor_base_negative_prompt"] == ""
    assert zimage["prompt_adaptation"]["changed"] and zimage["prompt_adaptation"]["complete"]
    # Evidence stays noncausal and shares requested seed policy.
    for arm in (sdxl, zimage):
        assert arm["causal_one_variable"] is False
        assert arm["effective_config"]["txt2img"]["seed"] == 42
        assert arm["comparison_claim"] == "target_envelope_preference"


def test_klein_and_zimage_keep_independent_fixed_model_settings(tmp_path):
    _, snapshot = build(tmp_path, models=[KLEIN, ZIMAGE])
    klein, zimage = snapshot["model_comparison"]["arms"]
    assert klein["effective_backend_options"]["image"]["model_profile"]["id"] == "flux2_klein_4b_fp8"
    assert zimage["effective_backend_options"]["image"]["model_profile"] == ZP.reference()
    assert klein["effective_config"]["txt2img"]["steps"] == 4
    assert zimage["effective_config"]["txt2img"]["steps"] == ZP.steps
    assert klein["effective_config"]["txt2img"]["steps"] != zimage["effective_config"]["txt2img"]["steps"]
    for arm in (klein, zimage):
        assert arm["executor_base_negative_prompt"] == ""
        assert arm["effective_config"]["prompt_optimizer"] == {"enabled": False}
    assert klein["source_intent_sha256"] == zimage["source_intent_sha256"]


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda c: c["txt2img"].update(width=768, height=1024), "geometry"),
        (lambda c: c["backend_options"]["image"].update(backend_id="a1111_webui"), "backend"),
        (lambda c: c["txt2img"].update(enable_hr=True), "hires"),
        (lambda c: c["txt2img"].update(refiner_enabled=True), "refiner"),
        (lambda c: c["txt2img"].update(controlnet={"enabled": True}), "controlnet"),
        (lambda c: c["pipeline"].update(adetailer_enabled=True), "stage chain"),
        (lambda c: c["pipeline"].update(upscale_enabled=True), "stage chain"),
        (lambda c: c["txt2img"].update(batch_size=2), "batch_size"),
        (lambda c: c["txt2img"].update(subseed=5, subseed_strength=0.4), "subseed_strength"),
    ],
)
def test_genuinely_incompatible_shared_constraints_fail_the_whole_study(tmp_path, change, match):
    config = shared_baseline()
    change(config)
    original = copy.deepcopy(config)
    with pytest.raises(ValueError, match=match):
        build(tmp_path, models=[SDXL, ZIMAGE], config=config)
    assert config == original  # nothing was normalized to force qualification


def test_shared_sample_count_is_not_normalized_for_a_single_image_profile(tmp_path):
    with pytest.raises(ValueError, match=r"arm 2.*images_per_prompt.*No arm was queued"):
        build(tmp_path, models=[SDXL, ZIMAGE], samples=2)


def test_unresolved_inline_adapter_token_refuses_instead_of_guessing(tmp_path):
    with pytest.raises(ValueError, match="natural-language positive prompt"):
        build(tmp_path, models=[SDXL, ZIMAGE], text="a portrait <lora:style:1> in [[place]]")


def test_a_refusal_leaves_no_partial_snapshot_or_plan_at_the_controller(tmp_path):
    exp = study(tmp_path, models=[SDXL, "peer.safetensors", ZIMAGE], samples=2)
    with pytest.raises(ValueError, match="arm 3"):
        controller_for(exp, shared_baseline())  # Build Preview through the real Learning controller
    assert not exp.execution_snapshot_json and not exp.values


def test_tamper_detection_covers_the_zimage_arm(tmp_path):
    _, snapshot = build(tmp_path, models=[SDXL, ZIMAGE])
    frozen_arm(snapshot, ZIMAGE)
    arm = snapshot["model_comparison"]["arms"][1]
    arm["effective_config"]["txt2img"]["steps"] = 30  # stale integrity digest
    with pytest.raises(ValueError, match="integrity"):
        frozen_arm(snapshot, ZIMAGE)
    arm["arm_sha256"] = digest({k: v for k, v in arm.items() if k != "arm_sha256"})
    with pytest.raises(ValueError, match="fixed policy"):  # resealed but still not the immutable value
        frozen_arm(snapshot, ZIMAGE)


def test_run_admits_all_arms_once_after_independent_exact_profile_validation(tmp_path):
    exp = study(tmp_path, models=[SDXL, ZIMAGE])
    controller = controller_for(exp, shared_baseline())
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(controller.learning_state, service)
    controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    assert [r.base_model for r in records] == [SDXL, ZIMAGE]
    backend = ForgeWebUIImageBackend()
    for record in records:
        backend.validate_njr_intent(record, ["txt2img"])  # final authority accepts the admitted arms
    zimage = records[1]
    assert zimage.images_per_prompt == 1 and not zimage.lora_tags and zimage.negative_prompt == ""


def test_a_tampered_arm_admits_nothing(tmp_path):
    exp = study(tmp_path, models=[SDXL, ZIMAGE])
    controller = controller_for(exp, shared_baseline())
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    snapshot["model_comparison"]["arms"][1]["effective_config"]["txt2img"]["width"] = 576
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    submit = Mock()
    controller.pipeline_controller = object()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    with pytest.raises(ValueError):
        controller.run_plan()
    submit.assert_not_called()
    assert all(v.status == "pending" for v in controller.learning_state.plan)


def test_candidate_preparation_touches_only_exact_profile_owned_values():
    config = shared_baseline()
    for model in (SDXL, KLEIN):
        config["txt2img"]["model"] = model
        before = copy.deepcopy(config)
        assert prepare_candidate_baseline(config) == before  # ordinary and Klein: the compile policy owns them
    config["txt2img"]["model"] = ZIMAGE
    config["txt2img"].update(enable_hr=True, batch_size=2, subseed_strength=0.3, width=576, height=1024)
    prepare_candidate_baseline(config)
    section = config["txt2img"]
    assert section["steps"] == ZP.steps and section["vae"] == "" and section["clip_skip"] == 1
    # Geometry, counts, seed policy and requested features are left to the fail-closed validators.
    assert (section["width"], section["height"], section["batch_size"]) == (576, 1024, 2)
    assert section["subseed_strength"] == 0.3 and section["enable_hr"] is True


def test_projection_covers_every_profile_owned_value_the_validator_checks():
    from src.image_backends.forge_zimage_profile import validate_zimage_config

    config = {
        "model": ZIMAGE, "sampler": "DPM++", "sampler_name": "DPM++", "scheduler": "Karras", "steps": 30,
        "cfg_scale": 7.0, "shift": 3.0, "distilled_cfg_scale": 3.0, "clip_skip": 2, "vae": "sdxl_vae.safetensors",
        "negative_prompt": "bad", "global_positive_prompt": "g", "global_negative_prompt": "n",
        "apply_global_positive_txt2img": True, "apply_global_negative_txt2img": True,
        "prompt_optimizer": {"enabled": True}, "width": 1024, "height": 1024,
        "txt2img": {"model": ZIMAGE, "sampler_name": "DPM++", "steps": 30, "cfg_scale": 7.0, "clip_skip": 2,
                    "vae": "x.safetensors", "negative_prompt": "bad", "width": 1024, "height": 1024,
                    "prompt_optimizer": {"enabled": True}},
        "pipeline": {"apply_global_positive_txt2img": True, "apply_global_negative_txt2img": True},
    }
    with pytest.raises(ValueError):
        validate_zimage_config(config)
    prepare_candidate_baseline(config)
    validate_zimage_config(config)  # every sampling/VAE/prompt-channel conflict the validator knows is covered


def test_comparison_module_has_no_model_family_table_or_conditional():
    source = inspect.getsource(comparison_module).lower()
    for token in ("z_image", "zimage", "z-image", "klein", "flux2", "distilled_cfg"):
        assert token not in source
