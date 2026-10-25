"""PR-LEARN-STAGE-650: Learning authors, freezes and compiles its own experiment baseline.

S-numbers refer to the work package's deterministic test matrix.  No WebUI, GPU, model load or image generation:
the Pipeline is a plain dict the tests mutate, JobService is a recording fake and resources are stubbed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.learning import baseline_authoring as authoring
from src.learning import baseline_draft as draft
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.model_policy_service import live_capabilities
from tests.learning_v2.test_model_comparison_140 import SDXL, baseline, policy

PEER = "peer.safetensors"
IMAGE_STAGES = ("img2img", "adetailer", "upscale")


def pipeline_config() -> dict:
    """A complete Pipeline snapshot: every stage section is populated, as the four stage cards would be."""
    config = baseline()
    config["prompt_optimizer"] = {"enabled": False}
    common = {
        "model": SDXL,
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
        "steps": 25,
        "cfg_scale": 6.5,
    }
    config["img2img"] = {**common, "denoising_strength": 0.4, "width": 768, "height": 1024}
    config["adetailer"] = {
        **common,
        "adetailer_model": "face_yolov8n.pt",
        "denoising_strength": 0.3,
        "adetailer_confidence": 0.35,
    }
    config["upscale"] = {"upscaler": "R-ESRGAN 4x+", "upscale_factor": 2.0}
    return config


class Bench:
    """A real LearningController over a mutable fake Pipeline and a recording JobService."""

    def __init__(self, tmp_path: Path, *, resources: dict | None = None) -> None:
        self.tmp_path = tmp_path
        self.pipeline = pipeline_config()
        self.state = LearningState()
        self.controller = LearningController(learning_state=self.state)
        self.controller._get_baseline_config = lambda: copy.deepcopy(self.pipeline)  # type: ignore[method-assign]
        self.controller._learning_policy_resolver = policy
        self.controller._learning_lora_resolver = lambda name: KleinLoraDecision(
            name, KleinLoraStatus.COMPATIBLE, "fixture"
        )
        if resources is not None:
            self.controller.app_state = SimpleNamespace(resources=resources)
        self.service = SimpleNamespace(
            submit_njrs=Mock(
                side_effect=lambda records, policy_: [record.job_id for record in records]
            )
        )
        self.controller.pipeline_controller = object()
        self.controller.execution_controller = LearningExecutionController(self.state, self.service)

    def image(self, name: str = "source.png") -> str:
        from PIL import Image

        path = self.tmp_path / name
        Image.new("RGB", (16, 16)).save(path)
        return str(path)

    def design(
        self,
        *,
        stage: str = "txt2img",
        variable: str = "CFG Scale",
        values=(4, 8, 2),
        images: int = 2,
        prompt: str = "a lighthouse at dusk",
        **extra,
    ) -> LearningExperiment:
        start, end, step = values
        data = {
            "name": "baseline study",
            "stage": stage,
            "variable_under_test": variable,
            "prompt_source": "custom",
            "custom_prompt": prompt,
            "start_value": start,
            "end_value": end,
            "step_value": step,
            "images_per_value": images,
            "input_image_path": self.image() if stage in IMAGE_STAGES else "",
        }
        data.update(extra)
        self.controller.update_experiment_design(data)
        return self.state.current_experiment

    def preview(self, **kwargs) -> LearningExperiment:
        if not self.controller.authoring_baseline():
            self.controller.copy_pipeline_settings(kwargs.get("stage", "txt2img"))
        experiment = self.design(**kwargs)
        self.controller.build_plan(experiment)
        return experiment

    def preview_or_error(self, **kwargs):
        """Build Preview, returning the refusal instead of raising it."""
        try:
            return self.preview(**kwargs)
        except ValueError as exc:
            return exc

    def run(self) -> list:
        self.controller.run_plan()
        return list(self.service.submit_njrs.call_args.args[0])


@pytest.fixture
def bench(tmp_path) -> Bench:
    return Bench(tmp_path)


def frozen(experiment: LearningExperiment) -> dict:
    return thaw_snapshot(experiment.execution_snapshot_json)


# -- S01-S05: the baseline is Learning's own ---------------------------------------------------------------------


def test_s01_new_experiment_gets_an_editable_learning_baseline(bench):
    assert bench.controller.authoring_baseline() == {}
    assert bench.controller.ensure_baseline("txt2img") is True
    assert bench.controller.authoring_baseline()["txt2img"]["model"] == SDXL
    bench.controller.update_baseline_field("txt2img", "steps", "31")
    assert bench.controller.authoring_baseline()["txt2img"]["steps"] == 31
    assert (
        bench.controller.ensure_baseline("txt2img") is False
    )  # never re-seeds a baseline the operator owns


def test_s02_explicit_copy_is_one_time_with_visible_origin(bench):
    record = bench.controller.copy_pipeline_settings("txt2img")
    assert record["origin"] == authoring.ORIGIN_PIPELINE_COPY
    assert authoring.origin_text(record).startswith("Copied from Pipeline")
    copied = bench.controller.authoring_baseline()
    assert copied["txt2img"] == bench.pipeline["txt2img"]
    bench.controller.update_baseline_field("txt2img", "steps", 12)
    assert authoring.origin_text(bench.controller.baseline_authoring_record()).endswith(
        "1 setting changed in Learning"
    )
    assert bench.controller.baseline_authoring_record()["origin"] == authoring.ORIGIN_LEARNING


def test_s03_pipeline_changes_after_copy_never_reach_the_draft(bench):
    bench.controller.copy_pipeline_settings("txt2img")
    before = bench.controller.authoring_baseline()
    bench.pipeline["txt2img"].update(steps=99, sampler_name="Euler", model=PEER)
    bench.pipeline["adetailer"]["adetailer_model"] = "hand_yolov8n.pt"
    assert bench.controller.authoring_baseline() == before
    assert bench.controller.ensure_baseline("txt2img") is False


def test_s04_learning_edits_never_reach_the_pipeline(bench):
    bench.controller.copy_pipeline_settings("txt2img")
    pipeline_before = copy.deepcopy(bench.pipeline)
    bench.controller.update_baseline_field("txt2img", "steps", 7)
    bench.controller.update_baseline_field("txt2img", "model", PEER)
    assert bench.pipeline == pipeline_before
    assert (
        bench.controller._get_baseline_config()["txt2img"]["steps"]
        == pipeline_before["txt2img"]["steps"]
    )


def test_s05_each_experiment_keeps_its_own_baseline(bench):
    first = bench.preview(values=(4, 8, 2))
    bench.controller.update_baseline_field("txt2img", "steps", 33)
    second = bench.controller.clone_current_experiment_as_new()
    assert second is not None and second.experiment_id != first.experiment_id
    assert second.baseline_authoring["origin"] == authoring.ORIGIN_CLONE
    bench.controller.update_baseline_field("txt2img", "steps", 5)
    second.baseline_config = bench.controller.authoring_baseline()
    assert (
        first.baseline_config["txt2img"]["steps"] == bench.pipeline["txt2img"]["steps"]
    )  # its own, untouched
    assert second.baseline_config["txt2img"]["steps"] == 5
    bench.controller.new_experiment_draft()
    assert (
        bench.controller.authoring_baseline() == {}
    )  # a new experiment starts empty, not inheriting either


def test_s05_restore_returns_the_experiments_own_baseline(bench):
    experiment = bench.preview()
    bench.controller.update_baseline_field("txt2img", "steps", 41)
    payload = bench.state.to_dict()
    other = Bench(bench.tmp_path)
    other.pipeline["txt2img"]["steps"] = 2  # a different Pipeline at restore time
    assert other.controller.restore_resume_state(json.loads(json.dumps(payload)))
    assert other.controller.authoring_baseline()["txt2img"]["steps"] == 41
    assert (
        other.state.current_experiment.baseline_config["txt2img"]["steps"]
        == bench.pipeline["txt2img"]["steps"]
    )
    assert experiment.experiment_id == other.state.current_experiment.experiment_id


# -- S06-S10: resources, model policy, refusals ------------------------------------------------------------------


def test_s06_resource_refresh_preserves_selection_or_reports_it(tmp_path):
    bench = Bench(
        tmp_path,
        resources={"models": [SDXL, PEER], "samplers": ["DPM++ 2M"], "schedulers": ["Karras"]},
    )
    bench.controller.copy_pipeline_settings("txt2img")
    assert bench.controller.baseline_blockers("txt2img") == []
    bench.controller.app_state = SimpleNamespace(
        resources={"models": [PEER], "samplers": ["DPM++ 2M"], "schedulers": ["Karras"]}
    )
    assert (
        bench.controller.authoring_baseline()["txt2img"]["model"] == SDXL
    )  # never silently replaced
    problems = bench.controller.baseline_blockers("txt2img")
    assert any(SDXL in problem and "not available" in problem for problem in problems)


def test_s07_learning_model_not_pipeline_projects_capabilities(bench):
    from src.image_backends.model_policy import resolve_model_policy
    from tests.learning_v2.test_model_capabilities_130d import klein_config

    klein = klein_config()["txt2img"]["model"]
    bench.controller._learning_policy_resolver = lambda name: (
        resolve_model_policy(klein) if name == klein else policy(name)
    )
    bench.controller.copy_pipeline_settings("txt2img")
    bench.pipeline["txt2img"]["model"] = klein  # the Pipeline moves to an exact-profile model
    kept = live_capabilities(
        bench.controller, "txt2img", baseline=bench.controller.authoring_baseline()
    )
    assert "CFG Scale" in kept.variables  # Learning's own (SDXL) baseline still decides
    bench.controller.update_baseline_field("txt2img", "model", klein)
    changed = live_capabilities(
        bench.controller, "txt2img", baseline=bench.controller.authoring_baseline()
    )
    assert "CFG Scale" not in changed.variables
    bench.controller.update_baseline_field("txt2img", "model", SDXL)
    bench.pipeline["txt2img"]["model"] = SDXL
    assert (
        "CFG Scale"
        in live_capabilities(
            bench.controller, "txt2img", baseline=bench.controller.authoring_baseline()
        ).variables
    )


def test_s08_profile_fixed_control_cannot_be_the_variable(bench):
    from tests.learning_v2.test_model_capabilities_130d import klein_config

    klein = klein_config()["txt2img"]["model"]
    bench.pipeline = {**bench.pipeline, "txt2img": {**bench.pipeline["txt2img"], "model": klein}}
    bench.controller._learning_policy_resolver = None
    bench.controller.copy_pipeline_settings("txt2img")
    experiment = bench.design(variable="CFG Scale")
    with pytest.raises(ValueError, match="(?i)cfg|fixed|profile|not supported"):
        bench.controller.build_plan(experiment)
    assert experiment.execution_snapshot_json == ""
    bench.service.submit_njrs.assert_not_called()


def test_s09_unsupported_stage_refused_before_admission(bench):
    bench.controller.copy_pipeline_settings("txt2img")
    experiment = bench.design(stage="txt2img")
    experiment.stage = "inpaint"
    with pytest.raises(ValueError, match="Unsupported Learning stage"):
        bench.controller.build_plan(experiment)
    bench.service.submit_njrs.assert_not_called()
    with pytest.raises(ValueError, match="Unsupported Learning stage"):
        authoring.require_stage("video")


@pytest.mark.parametrize(
    "missing", ["model", "sampler_name", "scheduler", "steps", "cfg_scale", "width", "height"]
)
def test_s10_missing_required_field_refuses_without_guessing(bench, missing):
    bench.pipeline["txt2img"].pop(missing)
    bench.pipeline["txt2img"].pop("model_name", None)
    experiment = bench.preview_or_error()
    assert isinstance(experiment, ValueError)
    assert "required" in str(experiment) or "incomplete" in str(experiment)
    assert bench.state.current_experiment.execution_snapshot_json == ""
    bench.service.submit_njrs.assert_not_called()


# -- S11-S21: txt2img Preview, freeze, compile and admit -------------------------------------------------------------


def test_s11_prompts_frozen_once_without_duplication(bench):
    experiment = bench.preview(prompt="a lighthouse at dusk")
    snapshot = frozen(experiment)
    assert snapshot["prompt_text"] == "a lighthouse at dusk"
    assert snapshot["negative_prompt_text"] == ""
    for record in bench.run():
        assert record.positive_prompt == "a lighthouse at dusk"
        assert (
            record.negative_prompt == ""
        )  # the global negative stays executor-owned, never pre-applied
        assert record.config["prompt"] == record.positive_prompt


def test_s12_global_prompt_policy_is_frozen_at_preview(bench):
    live = {
        "positive_enabled": False,
        "positive_text": "",
        "negative_enabled": True,
        "negative_text": "NEG-ONE",
    }
    bench.controller.app_controller = SimpleNamespace(
        get_current_global_prompt_policy=lambda: dict(live)
    )
    bench.preview()
    live.update(negative_text="NEG-TWO", positive_enabled=True, positive_text="POS-TWO")
    bench.pipeline["global_negative_prompt"] = "NEG-THREE"
    for record in bench.run():
        assert record.config["global_negative_prompt"] == "NEG-ONE"
        assert not record.config.get("global_positive_prompt")


def test_s13_one_variable_sweep_changes_only_the_tested_value(bench):
    bench.preview(values=(4, 8, 2))
    records = bench.run()
    assert [record.cfg_scale for record in records] == [4.0, 6.0, 8.0]
    reference = copy.deepcopy(records[0].config["txt2img"])
    for record in records:
        section = copy.deepcopy(record.config["txt2img"])
        assert section.pop("cfg_scale") in (4.0, 6.0, 8.0)
        reference_copy = copy.deepcopy(reference)
        reference_copy.pop("cfg_scale")
        assert section == reference_copy
        assert record.seed == records[0].seed and record.steps == records[0].steps
        assert record.sampler_name == "DPM++ 2M" and record.scheduler == "Karras"


def test_s14_preview_effective_settings_match_the_compiled_njr(bench):
    experiment = bench.preview()
    snapshot = frozen(experiment)
    records = bench.run()
    assert len(records) == len(snapshot["variant_effective_settings"]) == 3
    for entry, record in zip(snapshot["variant_effective_settings"], records, strict=True):
        compiled = authoring.stage_values_from_record(record, "txt2img")
        assert authoring.parity_mismatches(entry["settings"], compiled) == []
        assert compiled["cfg_scale"] == entry["value"]
    assert snapshot["stage_chain"] == ["txt2img"]
    assert snapshot["effective_settings"][0]["label"] == "Model"


def test_s15_build_preview_admits_nothing(bench):
    experiment = bench.preview()
    bench.service.submit_njrs.assert_not_called()
    assert all(variant.status == "pending" and not variant.job_id for variant in bench.state.plan)
    assert experiment.execution_snapshot_json


def test_s16_editing_the_baseline_after_preview_makes_the_preview_stale(bench):
    experiment = bench.preview()
    frozen_signature = frozen(experiment)["baseline_authoring"]["draft_signature"]
    assert authoring.signature(bench.controller.authoring_baseline(), "txt2img") == frozen_signature
    bench.controller.update_baseline_field("txt2img", "steps", 11)
    assert authoring.signature(bench.controller.authoring_baseline(), "txt2img") != frozen_signature


def test_s17_pipeline_changes_after_preview_do_not_reach_run(bench):
    bench.preview()
    bench.pipeline["txt2img"].update(
        steps=9, sampler_name="Euler", scheduler="normal", model=PEER, cfg_scale=1.5
    )
    bench.controller._get_baseline_config = lambda: pytest.fail("Run read the live Pipeline")  # type: ignore[method-assign]
    for record in bench.run():
        assert (
            record.steps == 30
            and record.sampler_name == "DPM++ 2M"
            and record.scheduler == "Karras"
        )
        assert record.config["txt2img"]["model"] == SDXL


def test_s18_run_admits_the_accepted_preview_in_one_all_or_none_call(bench):
    bench.preview()
    records = bench.run()
    assert bench.service.submit_njrs.call_count == 1
    assert len(records) == 3 and len({record.job_id for record in records}) == 3
    assert all(variant.job_id and variant.status == "queued" for variant in bench.state.plan)


def test_s19_a_second_run_does_not_admit_again(bench):
    bench.preview()
    bench.run()
    bench.controller.run_plan()
    assert bench.service.submit_njrs.call_count == 1


def test_s20_one_failing_variant_admits_nothing(bench):
    bench.preview()
    bench.state.plan[1].param_value = 99.0  # outside the frozen values: this one cannot compile
    with pytest.raises(ValueError, match="outside the frozen experiment values"):
        bench.controller.run_plan()
    bench.service.submit_njrs.assert_not_called()
    assert all(not variant.job_id and variant.status == "pending" for variant in bench.state.plan)


def test_s21_compile_normalization_overwriting_the_tested_value_refuses_everything(
    bench, monkeypatch
):
    def overwrite(config):
        config["txt2img"]["cfg_scale"] = 1.0

    monkeypatch.setattr("src.learning.model_policy_service.apply_model_compile_policy", overwrite)
    bench.controller.copy_pipeline_settings("txt2img")
    experiment = bench.design()
    with pytest.raises(ValueError, match="overwritten by model compile normalization"):
        bench.controller.build_plan(experiment)
    assert experiment.execution_snapshot_json == ""
    bench.service.submit_njrs.assert_not_called()


# -- golden: independent edits survive every Pipeline change -----------------------------------------------------


def test_golden_txt2img_baseline_is_frozen_independently_of_the_pipeline(bench):
    bench.controller.copy_pipeline_settings("txt2img")
    for name, value in {
        "sampler_name": "Euler a",
        "scheduler": "normal",
        "steps": 17,
        "width": 640,
        "height": 896,
    }.items():
        bench.controller.update_baseline_field("txt2img", name, value)
    experiment = bench.design(values=(4, 10, 3))
    bench.controller.build_plan(experiment)
    snapshot = frozen(experiment)
    expected = {
        "model": SDXL,
        "sampler_name": "Euler a",
        "scheduler": "normal",
        "steps": 17,
        "width": 640,
        "height": 896,
    }

    for section in ("txt2img", "img2img", "adetailer", "upscale"):
        bench.pipeline[section] = {
            key: ("changed" if isinstance(value, str) else 3)
            for key, value in bench.pipeline[section].items()
        }
    bench.pipeline["pipeline"].update(adetailer_enabled=True, upscale_enabled=True)
    bench.controller._get_baseline_config = lambda: pytest.fail("Run read the live Pipeline")  # type: ignore[method-assign]
    records = bench.run()

    assert bench.service.submit_njrs.call_count == 1
    assert [record.cfg_scale for record in records] == [4.0, 7.0, 10.0]
    for record in records:
        assert {key: record.config["txt2img"][key] for key in expected} == expected
        assert [stage.stage_type for stage in record.stages] == ["txt2img"]
        assert record.seed == snapshot["seed_policy"]["requested_base_seed"]
        assert record.images_per_prompt == 2
        assert record.provenance.learning_context.variant_value == record.cfg_scale
    assert {record.config["txt2img"]["cfg_scale"] for record in records} == {4.0, 7.0, 10.0}


# -- S22-S30: img2img, ADetailer and Upscale experiments -----------------------------------------------------------

STAGE_SWEEP = {
    "img2img": ("Denoise Strength", (0.2, 0.6, 0.2), "denoising_strength"),
    "adetailer": ("Steps", (10, 30, 10), "steps"),
    "upscale": ("Upscale Factor", (1.5, 2.5, 0.5), "upscale_factor"),
}


@pytest.mark.parametrize("stage", IMAGE_STAGES)
def test_s22_s25_s28_valid_input_compiles_single_stage_reprocess_jobs(bench, stage):
    variable, values, field = STAGE_SWEEP[stage]
    experiment = bench.preview(stage=stage, variable=variable, values=values)
    snapshot = frozen(experiment)
    assert snapshot["stage_chain"] == [stage]
    assert snapshot["input_image"]["path"] == experiment.input_image_path
    records = bench.run()
    assert bench.service.submit_njrs.call_count == 1
    assert len(records) == len(snapshot["variant_values"]) == 3
    for entry, record in zip(snapshot["variant_effective_settings"], records, strict=True):
        assert [item.stage_type for item in record.stages] == [stage]
        assert set(record.input_image_paths) == {experiment.input_image_path}
        compiled = authoring.stage_values_from_record(record, stage)
        assert authoring.parity_mismatches(entry["settings"], compiled) == []
        assert float(compiled[field]) == float(entry["value"]) == float(entry["settings"][field])


@pytest.mark.parametrize("stage", IMAGE_STAGES)
def test_s23_image_stage_without_source_is_refused(bench, stage):
    variable, values, _ = STAGE_SWEEP[stage]
    bench.controller.copy_pipeline_settings(stage)
    experiment = bench.design(stage=stage, variable=variable, values=values, input_image_path="")
    with pytest.raises(ValueError, match="source image"):
        bench.controller.build_plan(experiment)
    assert experiment.execution_snapshot_json == ""
    bench.service.submit_njrs.assert_not_called()


def test_s24_img2img_denoise_sweep_uses_each_value_in_the_submitted_stage(bench):
    bench.preview(stage="img2img", variable="Denoise Strength", values=(0.2, 0.6, 0.2))
    records = bench.run()
    denoise = [
        authoring.stage_values_from_record(record, "img2img")["denoising_strength"]
        for record in records
    ]
    assert denoise == pytest.approx([0.2, 0.4, 0.6])
    fixed = {
        key: authoring.stage_values_from_record(records[0], "img2img")[key]
        for key in ("model", "sampler_name", "scheduler", "steps", "cfg_scale")
    }
    for record in records:
        values = authoring.stage_values_from_record(record, "img2img")
        assert {key: values[key] for key in fixed} == fixed


def test_s26_stale_pipeline_stage_flags_cannot_change_the_requested_stage(bench):
    bench.pipeline["pipeline"].update(
        txt2img_enabled=True, adetailer_enabled=False, upscale_enabled=True
    )
    bench.pipeline["adetailer"]["enabled"] = False
    experiment = bench.preview(stage="adetailer", variable="Steps", values=(10, 30, 10))
    baseline_ = frozen(experiment)["baseline_config"]
    assert baseline_["pipeline"]["adetailer_enabled"] is True
    assert not any(
        baseline_["pipeline"][flag]
        for flag in ("txt2img_enabled", "img2img_enabled", "upscale_enabled")
    )
    assert baseline_["adetailer"]["enabled"] is True
    for record in bench.run():
        assert [item.stage_type for item in record.stages] == ["adetailer"]
        assert [item.stage_type for item in record.stage_chain] == ["adetailer"]


def test_s27_unavailable_adetailer_resource_is_refused(tmp_path):
    bench = Bench(tmp_path, resources={"adetailer_models": ["hand_yolov8n.pt"]})
    bench.controller.copy_pipeline_settings("adetailer")
    experiment = bench.design(stage="adetailer", variable="Steps", values=(10, 30, 10))
    with pytest.raises(ValueError, match="face_yolov8n.pt.*not available"):
        bench.controller.build_plan(experiment)
    bench.service.submit_njrs.assert_not_called()


def test_s29_unsupported_upscale_value_or_variable_is_refused(bench):
    bench.pipeline["upscale"]["upscale_factor"] = 40.0
    outcome = bench.preview_or_error(
        stage="upscale", variable="Upscale Factor", values=(1.5, 2.5, 0.5)
    )
    assert isinstance(outcome, ValueError) and "at most" in str(outcome)
    bench.service.submit_njrs.assert_not_called()
    other = Bench(bench.tmp_path)
    outcome = other.preview_or_error(
        stage="upscale", variable="Denoise Strength", values=(0.2, 0.6, 0.2)
    )
    assert isinstance(outcome, ValueError)
    other.service.submit_njrs.assert_not_called()


@pytest.mark.parametrize("stage", IMAGE_STAGES)
def test_s30_source_that_disappears_after_preview_is_refused_at_run(bench, stage):
    variable, values, _ = STAGE_SWEEP[stage]
    experiment = bench.preview(stage=stage, variable=variable, values=values)
    Path(experiment.input_image_path).unlink()
    with pytest.raises(ValueError, match="(?i)source image"):
        bench.controller.run_plan()
    bench.service.submit_njrs.assert_not_called()
    assert all(not variant.job_id for variant in bench.state.plan)


@pytest.mark.parametrize("stage", IMAGE_STAGES)
def test_golden_reprocess_baseline_is_frozen_independently_of_the_pipeline(bench, stage):
    variable, values, field = STAGE_SWEEP[stage]
    bench.controller.copy_pipeline_settings(stage)
    authored = {
        "img2img": ("steps", 14),
        "adetailer": ("detector", "hand_yolov8n.pt"),
        "upscale": ("upscaler", "4x-UltraSharp"),
    }[stage]
    bench.controller.update_baseline_field(stage, *authored)
    experiment = bench.design(stage=stage, variable=variable, values=values)
    bench.controller.build_plan(experiment)
    snapshot = frozen(experiment)
    for section in ("txt2img", "img2img", "adetailer", "upscale"):
        bench.pipeline[section] = {
            key: ("changed" if isinstance(value, str) else 3)
            for key, value in bench.pipeline[section].items()
        }
    bench.controller._get_baseline_config = lambda: pytest.fail("Run read the live Pipeline")  # type: ignore[method-assign]
    records = bench.run()
    assert bench.service.submit_njrs.call_count == 1
    spec = authoring.field_for(stage, authored[0])
    for record, entry in zip(records, snapshot["variant_effective_settings"], strict=True):
        assert [item.stage_type for item in record.stages] == [stage]
        assert authoring.read_field(snapshot["baseline_config"], spec) == authored[1]
        assert (
            authoring.parity_mismatches(
                entry["settings"], authoring.stage_values_from_record(record, stage)
            )
            == []
        )
        if stage == "adetailer":
            assert record.config["adetailer"]["adetailer_model"] == "hand_yolov8n.pt"
        if stage == "upscale":
            assert record.stages[0].extra["upscaler"] == "4x-UltraSharp"
        if stage == "img2img":
            assert record.stages[0].steps == 14


# -- S31-S33: stage-specific model policy and resources ------------------------------------------------------------


def test_s31_exact_profile_model_in_the_learning_baseline_restricts_the_experiment(bench):
    from src.image_backends.model_policy import resolve_model_policy
    from tests.learning_v2.test_model_capabilities_130d import klein_config

    klein = klein_config()["txt2img"]["model"]
    bench.controller._learning_policy_resolver = lambda name: (
        resolve_model_policy(klein) if name == klein else policy(name)
    )
    bench.controller.copy_pipeline_settings("txt2img")
    bench.controller.update_baseline_field("txt2img", "model", klein)
    capability = live_capabilities(
        bench.controller, "txt2img", baseline=bench.controller.authoring_baseline()
    )
    assert "CFG Scale" not in capability.variables and "Steps" not in capability.variables
    experiment = bench.design(variable="Steps", values=(10, 30, 10))
    with pytest.raises(ValueError):
        bench.controller.build_plan(experiment)
    bench.service.submit_njrs.assert_not_called()


def test_s33_source_specific_model_variable_offers_only_the_selected_candidates(tmp_path):
    bench = Bench(tmp_path, resources={"models": [SDXL, PEER, "sd1"]})
    experiment = bench.preview(
        stage="img2img",
        variable="Model",
        selected_items=[SDXL, PEER],
        values=(0, 0, 1),
    )
    snapshot = frozen(experiment)
    assert snapshot["variant_values"] == [SDXL, PEER]
    records = bench.run()
    assert [
        authoring.stage_values_from_record(record, "img2img")["model"] for record in records
    ] == [SDXL, PEER]
    assert {record.stages[0].steps for record in records} == {25}  # everything else held fixed


def test_s43_missing_backend_resource_is_an_actionable_refusal_without_backend_traffic(
    tmp_path, monkeypatch
):
    import requests

    from src.assets import AssetRegistry

    def forbidden(*args, **kwargs):
        raise AssertionError("A refusal reached the backend or scanned assets")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(AssetRegistry, "snapshot", forbidden)
    bench = Bench(
        tmp_path, resources={"models": [PEER], "samplers": ["DPM++ 2M"], "schedulers": ["Karras"]}
    )
    bench.controller.copy_pipeline_settings("txt2img")
    experiment = bench.design()
    with pytest.raises(
        ValueError, match=f"Model '{SDXL}' is not available in the current resources"
    ):
        bench.controller.build_plan(experiment)
    assert experiment.execution_snapshot_json == ""
    bench.service.submit_njrs.assert_not_called()


# -- S36-S40: restore -----------------------------------------------------------------------------------------------


def test_s38_a_restored_independent_draft_keeps_its_authored_settings_and_selections(bench):
    bench.controller.copy_pipeline_settings("txt2img")
    bench.controller.update_baseline_field("txt2img", "steps", 41)
    bench.controller.update_baseline_field("txt2img", "sampler_name", "Euler a")
    bench.design(values=(3, 9, 3), images=3)
    payload = json.loads(json.dumps(bench.state.to_dict()))

    other = Bench(bench.tmp_path / "other")
    other.tmp_path.mkdir()
    other.pipeline["txt2img"].update(steps=2, sampler_name="Euler")
    assert other.controller.restore_resume_state(payload)
    restored = other.state.current_experiment
    assert other.controller.authoring_baseline()["txt2img"]["steps"] == 41
    assert other.controller.authoring_baseline()["txt2img"]["sampler_name"] == "Euler a"
    assert other.controller.baseline_authoring_record()["edited"] == [
        "txt2img.steps",
        "txt2img.sampler_name",
    ]
    assert (restored.stage, restored.variable_under_test, restored.images_per_value) == (
        "txt2img",
        "CFG Scale",
        3,
    )


def test_s39_a_restored_queued_experiment_is_not_resubmitted(bench):
    bench.preview()
    admitted = [record.job_id for record in bench.run()]
    payload = json.loads(json.dumps(bench.state.to_dict()))
    other = Bench(bench.tmp_path / "other")
    other.tmp_path.mkdir()
    assert other.controller.restore_resume_state(payload)
    assert [variant.job_id for variant in other.state.plan] == admitted
    other.controller.run_plan()
    other.service.submit_njrs.assert_not_called()


# -- range generation (Example B needs 0.2, 0.4, 0.6) -----------------------------------------------------------------


def test_stepped_range_keeps_its_end_value_despite_float_error():
    from src.learning.design_estimate import count_range_values, range_values

    assert range_values(0.2, 0.6, 0.2) == [0.2, 0.4, 0.6]
    assert range_values(0.1, 0.5, 0.1) == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert range_values(4, 10, 3) == [4, 7, 10]
    assert range_values(6, 5, 1) is None and range_values(1, 2, 0) is None
    assert count_range_values(0.2, 0.6, 0.2) == 3


def test_img2img_example_b_yields_three_denoise_variants(bench):
    experiment = bench.preview(stage="img2img", variable="Denoise Strength", values=(0.2, 0.6, 0.2))
    assert frozen(experiment)["variant_values"] == [0.2, 0.4, 0.6]


# -- S46: nothing but the canonical path -----------------------------------------------------------------------------


NEW_MODULES = (
    "src/learning/baseline_authoring.py",
    "src/learning/baseline_draft.py",
    "src/learning/ordinary_njr.py",
    "src/learning/ordinary_snapshot.py",
    "src/gui/views/learning_baseline_editor.py",
)
FORBIDDEN_IMPORTS = (
    "src.queue",
    "src.controller",
    "src.pipeline.pipeline_runner",
    "src.pipeline.executor",
    "src.api",
    "requests",
    "subprocess",
    "src.image_backends.forge",
)


@pytest.mark.parametrize("module", NEW_MODULES)
def test_s46_new_modules_add_no_queue_runner_backend_or_second_authority(module):
    import ast

    root = Path(__file__).resolve().parents[2]
    source = (root / module).read_text(encoding="utf-8")
    imported: list[str] = []
    identifiers: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
    offending = [name for name in imported if name.startswith(FORBIDDEN_IMPORTS)]
    assert offending == []
    # Code, not prose: no admission call and no Pipeline read live in these modules.
    assert not identifiers & {
        "submit_njrs",
        "JobService",
        "_get_baseline_config",
        "run_njr",
        "PipelineRunner",
    }
    if module.startswith("src/learning/"):
        assert "tkinter" not in imported


# -- pure rules ------------------------------------------------------------------------------------------------------


def test_every_spelling_of_a_stage_setting_is_kept_equal():
    config = {
        "adetailer": {"adetailer_steps": 12, "ad_steps": 30, "steps": 20},
        "upscale": {"upscaling_resize": 3},
    }
    authoring.align_aliases(config, "adetailer")
    assert {config["adetailer"][key] for key in ("steps", "adetailer_steps", "ad_steps")} == {20}
    authoring.align_aliases(config, "upscale")
    assert config["upscale"]["upscale_factor"] == config["upscale"]["upscaling_resize"] == 3.0


def test_finalize_for_stage_makes_the_requested_stage_the_only_enabled_one():
    config = {
        "pipeline": {
            "txt2img_enabled": True,
            "img2img_enabled": True,
            "adetailer_enabled": False,
            "upscale_enabled": True,
        },
        "adetailer": {"enabled": False, "adetailer_enabled": False},
    }
    authoring.finalize_for_stage(config, "adetailer")
    assert config["pipeline"] == {
        "txt2img_enabled": False,
        "img2img_enabled": False,
        "adetailer_enabled": True,
        "upscale_enabled": False,
    }
    assert (
        config["adetailer"]["enabled"] is True and config["adetailer"]["adetailer_enabled"] is True
    )
    with pytest.raises(ValueError, match="Unsupported Learning stage"):
        authoring.finalize_for_stage(config, "refine")


def test_editing_validates_and_never_invents_a_value():
    state = LearningState()
    assert draft.signature(state, "txt2img") == ""
    with pytest.raises(ValueError, match="must be a number"):
        draft.edit_field(state, "txt2img", "steps", "many")
    assert draft.edit_field(state, "txt2img", "steps", "31") == 31
    assert (
        draft.edit_field(state, "txt2img", "vae", "") is None
    )  # an optional setting cleared is unset, not zero
    assert draft.edit_field(state, "txt2img", "cfg_scale", "7") == 7.0
    assert draft.edit_field(state, "txt2img", "steps", "") is None
    problems = authoring.baseline_problems(draft.config_of(state), "txt2img")
    assert "Steps is required for a txt2img experiment" in problems
    assert authoring.baseline_problems({}, "txt2img")[0].startswith(
        "The Learning baseline is empty"
    )
    assert any(
        "at most" in item
        for item in authoring.baseline_problems(
            {"txt2img": {**pipeline_config()["txt2img"], "steps": 900}}, "txt2img"
        )
    )


def test_copying_nothing_is_refused_and_replacing_keeps_the_experiment_untouched():
    state = LearningState()
    with pytest.raises(ValueError, match="no settings to copy"):
        draft.copy_from_pipeline(state, {}, "txt2img")
    draft.copy_from_pipeline(state, pipeline_config(), "txt2img")
    first = draft.signature(state, "txt2img")
    draft.edit_field(state, "txt2img", "steps", 5)
    assert draft.signature(state, "txt2img") != first
    draft.copy_from_pipeline(state, pipeline_config(), "txt2img")
    assert draft.signature(state, "txt2img") == first
    assert draft.authoring_of(state)["edited"] == []


def test_parity_compares_numbers_not_text_and_ignores_unreported_settings():
    expected = {"stage": "txt2img", "steps": 30, "cfg_scale": 7.0, "sampler_name": "Euler a"}
    assert (
        authoring.parity_mismatches(
            expected, {"steps": 30.0, "cfg_scale": "7", "sampler_name": "Euler a"}
        )
        == []
    )
    assert authoring.parity_mismatches(expected, {"steps": 31}) == [
        "steps: Preview promised 30 but the job carries 31"
    ]
    assert authoring.parity_mismatches(expected, {}) == []


def test_baseline_authoring_persists_additively_and_old_payloads_still_load():
    experiment = LearningExperiment(
        name="n", baseline_authoring={"origin": "pipeline_copy", "edited": []}
    )
    payload = experiment.to_dict()
    assert payload["baseline_authoring"]["origin"] == "pipeline_copy"
    payload.pop("baseline_authoring")
    assert LearningExperiment.from_dict(payload).baseline_authoring == {}
    state = LearningState()
    assert (
        LearningState.from_dict(
            {k: v for k, v in state.to_dict().items() if k != "baseline_draft"}
        ).baseline_draft
        is None
    )
