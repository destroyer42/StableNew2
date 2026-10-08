"""Ordinary Learning Preview-to-dispatch global prompt ownership."""

import copy
import json
from dataclasses import replace
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot
from src.learning.ordinary_prompt_freeze import BASE_CONTRACT
from src.pipeline.global_prompt_policy import apply_global_prompt_policy
from tests.learning_v2.test_model_comparison_140 import baseline, controller_for, experiment, policy
from tests.learning_v2.test_model_comparison_global_prompts_140 import dispatch


def selected_ui_plan(tmp_path, *, negative="bad", embeddings=(), enabled=True):
    """Real panel selection/Preview and controller; only Tk widgets are stand-ins."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState
    from src.gui.views.experiment_design_panel import ExperimentDesignPanel

    experiment(tmp_path)
    path = tmp_path / "pack.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pack_data"]["slots"][0].update(
        text="cat", negative=negative, positive_embeddings=[], negative_embeddings=list(embeddings)
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    authored = path.read_bytes()
    config = apply_global_prompt_policy(
        baseline(), positive_enabled=True, positive_text="POSITIVE",
        negative_enabled=enabled, negative_text="GLOBAL",
    )
    config["prompt_optimizer"] = {"enabled": False}
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: copy.deepcopy(config)
    controller._learning_policy_resolver = policy
    panel = SimpleNamespace(
        learning_controller=controller, _learning_capabilities=None, choice_vars={},
        _prompt_pack_paths={"study": path}, feedback_var=Mock(),
        _render_slot_positive_prompt=ExperimentDesignPanel._render_slot_positive_prompt,
        _render_slot_negative_prompt=ExperimentDesignPanel._render_slot_negative_prompt,
    )
    for name, value in {
        "study_type": "Controlled Variable", "name": "selected row", "desc": "",
        "stage": "txt2img", "input_image": "", "variable": "CFG Scale",
        "start": 6, "end": 7, "step": 1, "images": 1,
        "prompt_source": "pack", "prompt_pack": "study",
    }.items():
        setattr(panel, f"{name}_var", SimpleNamespace(get=lambda value=value: value))
    for name in (
        "_load_prompt_payloads_for_pack", "_get_selected_prompt_payload",
        "_on_build_preview", "_validate_experiment_data", "_is_model_comparison",
    ):
        setattr(panel, name, MethodType(getattr(ExperimentDesignPanel, name), panel))
    rows = panel._load_prompt_payloads_for_pack(path)
    panel._prompt_option_payloads = {rows[0]["label"]: rows[0]}
    panel.prompt_item_var = SimpleNamespace(get=lambda: rows[0]["label"])
    panel._on_build_preview()
    assert not panel.feedback_var.set.call_args.args[0].startswith(("Error", "Validation Error"))
    assert controller.learning_state.plan, "Real UI Preview did not build ordinary variants"
    assert path.read_bytes() == authored
    return controller.learning_state.current_experiment, controller, rows[0]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "negative,embeddings,base",
    [
        ("", [], ""),
        ("bad", [], "bad"),
        ("bad, ugly\nwrong", [], "bad, ugly, wrong"),
        ("bad, bad", [], "bad, bad"),
        ("", [["negative_embed", 0.7]], "(<embedding:negative_embed>:0.7)"),
        ("bad, wrong", [["negative_embed", 1]], "<embedding:negative_embed>, bad, wrong"),
    ],
)
def test_ui_selected_row_negative_owned_once_at_dispatch(
    tmp_path, monkeypatch, negative, embeddings, base, enabled
):
    exp, controller, selected = selected_ui_plan(
        tmp_path, negative=negative, embeddings=embeddings, enabled=enabled
    )
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    assert snapshot["prompt_source"]["selected_prompt_negative_text"] == selected["negative_prompt_text"]
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    payload = dispatch(record, tmp_path, monkeypatch)
    expected = ", ".join(part for part in (base, "GLOBAL" if enabled else "") if part)
    assert payload["negative_prompt"] == expected, (
        f"UI selected negative={selected['negative_prompt_text']!r}; "
        f"frozen base={record.negative_prompt!r}; backend={payload['negative_prompt']!r}"
    )
    assert snapshot["negative_prompt_text"] == record.negative_prompt == base
    assert record.config["negative_prompt"] == record.config["txt2img"]["negative_prompt"] == base
    assert payload["prompt"] == "POSITIVE, cat"


def test_independent_pack_negative_contribution_remains_distinct(tmp_path):
    from src.learning.experiment_freeze import freeze_prompt_pack_source

    exp, _, _ = selected_ui_plan(tmp_path)
    metadata = {**exp.metadata, "selected_prompt_negative_text": "independent"}
    before = copy.deepcopy(metadata)
    # The shared helper's default still supports an independently authored input.
    source = freeze_prompt_pack_source(metadata, apply_global_negative=False)
    assert source["rendered_negative_prompt"] == "independent, bad"
    assert metadata == before


def test_ui_frozen_source_and_atomic_run_use_preview_base(tmp_path, monkeypatch):
    from src.learning.execution_controller import LearningExecutionController

    exp, controller, _ = selected_ui_plan(tmp_path)
    before = exp.execution_snapshot_json
    (tmp_path / "pack.json").write_text("changed after preview", encoding="utf-8")
    exp.metadata["selected_prompt_negative_text"] = "changed display"
    for target in (
        "src.learning.experiment_freeze.load_prompt_pack_document",
        "src.gui.controllers.learning_controller.freeze_ordinary_prompt_source",
    ):
        monkeypatch.setattr(target, lambda *a, **kw: pytest.fail("Run reopened source"))
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(controller.learning_state, service)
    controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    assert len(records) == 2
    assert all(dispatch(r, tmp_path, monkeypatch)["negative_prompt"] == "bad, GLOBAL" for r in records)
    assert exp.execution_snapshot_json == before


def test_existing_frozen_row_duplication_is_not_reinterpreted(tmp_path, monkeypatch):
    exp, controller, _ = selected_ui_plan(tmp_path)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    snapshot["negative_prompt_text"] = "bad, bad"
    snapshot["prompt_source"]["rendered_negative_prompt"] = "bad, bad"
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    before = exp.execution_snapshot_json
    monkeypatch.setattr(
        "src.learning.experiment_freeze.load_prompt_pack_document",
        lambda *a: pytest.fail("Saved preview reopened source"),
    )
    restored = type(exp).from_dict(exp.to_dict())
    record = controller._build_variant_njr(controller.learning_state.plan[0], restored)
    assert dispatch(record, tmp_path, monkeypatch)["negative_prompt"] == "bad, bad, GLOBAL"
    assert restored.execution_snapshot_json == exp.execution_snapshot_json == before


def ordinary_plan(
    tmp_path,
    *,
    negative="bad",
    enabled=True,
    positive=False,
    variable="CFG Scale",
    stage="txt2img",
    stage_enabled=None,
):
    exp = experiment(tmp_path)
    exp.metadata.pop("study_type")
    exp.variable_under_test = variable
    exp.metadata.update(start_value=6, end_value=7, step_value=1)
    if variable == "Steps":
        exp.metadata.update(start_value=20, end_value=30, step_value=10)
    elif variable == "Model":
        exp.metadata["selected_items"] = ["ordinary.safetensors", "peer.safetensors"]
    elif variable == "LoRA Strength":
        exp.metadata.update(
            lora_name="adapter", strength_start=0.0, strength_end=0.8, strength_step=0.4
        )
    exp.stage = stage
    pack = tmp_path / "pack.json"
    data = json.loads(pack.read_text(encoding="utf-8"))
    data["pack_data"]["slots"][0].update(
        text="cat in [[place]]", negative=negative, positive_embeddings=[], negative_embeddings=[]
    )
    pack.write_text(json.dumps(data), encoding="utf-8")
    authored = pack.read_bytes()
    config = apply_global_prompt_policy(
        baseline(),
        positive_enabled=positive,
        positive_text="POSITIVE",
        negative_enabled=enabled,
        negative_text="GLOBAL",
    )
    config["prompt_optimizer"] = {"enabled": False}
    if stage != "txt2img":
        config[stage] = copy.deepcopy(config["txt2img"])
        if variable == "Upscale Factor":
            exp.metadata.update(start_value=1.5, end_value=2, step_value=0.5)
        from PIL import Image

        path = tmp_path / "input.png"
        Image.new("RGB", (16, 16)).save(path)
        exp.input_image_path = str(path)
        config["pipeline"][f"apply_global_negative_{stage}"] = stage_enabled
    if variable == "Model":
        from src.gui.controllers.learning_controller import LearningController
        from src.gui.learning_state import LearningState

        controller = LearningController(learning_state=LearningState())
        controller.app_state = SimpleNamespace(resources={"models": exp.metadata["selected_items"]})
        controller._get_baseline_config = lambda: copy.deepcopy(config)
        controller._learning_policy_resolver = policy
        controller.build_plan(exp)
    else:
        controller = controller_for(exp, config)
    assert pack.read_bytes() == authored
    return exp, controller, config


@pytest.mark.parametrize(
    "negative,enabled,expected",
    [("bad", True, "bad, GLOBAL"), ("", True, "GLOBAL"), ("bad", False, "bad")],
)
def test_ordinary_negative_applied_once_by_executor(
    tmp_path, monkeypatch, negative, enabled, expected
):
    exp, controller, _ = ordinary_plan(tmp_path, negative=negative, enabled=enabled)
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert record.config["pipeline"]["apply_global_negative_txt2img"] is enabled
    payload = dispatch(record, tmp_path, monkeypatch)
    assert payload["negative_prompt"] == expected, (
        f"frozen base={record.negative_prompt!r}; executor apply={enabled}; "
        f"actual backend={payload['negative_prompt']!r}"
    )
    assert record.negative_prompt == negative
    assert record.config["prompt"] == record.positive_prompt
    assert record.config["negative_prompt"] == record.negative_prompt
    assert record.config["txt2img"]["negative_prompt"] == record.negative_prompt


def test_ordinary_global_positive_remains_executor_owned(tmp_path, monkeypatch):
    exp, controller, _ = ordinary_plan(tmp_path, positive=True)
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert record.positive_prompt == "cat in forest"
    payload = dispatch(record, tmp_path, monkeypatch)
    assert payload["prompt"] == "POSITIVE, cat in forest"


@pytest.mark.parametrize("variable", ["CFG Scale", "Steps", "Model", "LoRA Strength"])
def test_frozen_source_policy_variants_and_one_jobservice_admission(
    tmp_path, monkeypatch, variable
):
    from src.learning.execution_controller import LearningExecutionController

    exp, controller, config = ordinary_plan(tmp_path, variable=variable, positive=True)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    assert snapshot["prompt_source"]["matrix_values"] == {"place": "forest"}
    assert snapshot["prompt_source"]["matrix_freeze_policy"] == "first_canonical_required_slots"
    assert snapshot["prompt_source"]["executor_base_contract"] == BASE_CONTRACT
    pack = tmp_path / "pack.json"
    pack.write_text("changed row and Matrix", encoding="utf-8")
    config.update(global_negative_prompt="NEW", global_positive_prompt="NEW")
    config["pipeline"].update(
        apply_global_negative_txt2img=False, apply_global_positive_txt2img=False
    )
    controller._get_baseline_config = lambda: pytest.fail("live stage card read at Run")
    controller.app_controller = SimpleNamespace(
        get_current_global_prompt_policy=lambda: pytest.fail("live global policy read")
    )
    monkeypatch.setattr(
        "src.learning.experiment_freeze.load_prompt_pack_document",
        lambda *a: pytest.fail("PromptPack reopened"),
    )
    exp.values = [999]
    service = SimpleNamespace(
        submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records])
    )
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.run_plan()
    assert service.submit_njrs.call_count == 1
    records = service.submit_njrs.call_args.args[0]
    assert len(records) == len(snapshot["variant_values"])
    for record in records:
        assert record.config["global_negative_prompt"] == "GLOBAL"
        assert record.config["global_positive_prompt"] == "POSITIVE"
        assert record.config["pipeline"]["apply_global_negative_txt2img"]
        assert record.negative_prompt == record.config["txt2img"]["negative_prompt"] == "bad"
        assert record.seed == snapshot["seed_policy"]["requested_base_seed"]
        assert record.config["prompt"] == record.positive_prompt
        assert dispatch(record, tmp_path, monkeypatch)["negative_prompt"] == "bad, GLOBAL"
        if variable == "LoRA Strength":
            weight = record.provenance.learning_context.variant_value["weight"]
            assert ("<lora:adapter:" in record.positive_prompt) is (weight > 0)
            if weight > 0:
                assert f"<lora:adapter:{weight:g}>" in record.positive_prompt
    assert exp.execution_snapshot_json == freeze_snapshot(snapshot)


@pytest.mark.parametrize(
    "stage,variable", [("img2img", "Steps"), ("adetailer", "Steps"), ("upscale", "Upscale Factor")]
)
@pytest.mark.parametrize("enabled", [False, True])
def test_non_txt2img_stage_policy_is_preserved(tmp_path, stage, variable, enabled):
    exp, controller, config = ordinary_plan(
        tmp_path, stage=stage, variable=variable, stage_enabled=enabled
    )
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert record.config["pipeline"][f"apply_global_negative_{stage}"] is enabled
    assert record.config["pipeline"]["apply_global_negative_txt2img"] is True
    assert record.negative_prompt == record.config[stage]["negative_prompt"] == "bad"
    assert record.source.kind.value == "learning"
    assert record.config["global_negative_prompt"] == "GLOBAL"
    assert record.config["global_prompt_policy_source"] == "frozen_njr"
    assert config["pipeline"][f"apply_global_negative_{stage}"] is enabled


@pytest.mark.parametrize("negative", ["GLOBAL, bad", "GLOBAL"])
def test_saved_pack_preapplication_refused_without_snapshot_rewrite(tmp_path, negative):
    exp, controller, _ = ordinary_plan(tmp_path)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    source = snapshot["prompt_source"]
    source.pop("executor_base_contract")
    source.pop("prompt_semantics")
    source["rendered_negative_prompt"] = snapshot["negative_prompt_text"] = negative
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    before = exp.execution_snapshot_json
    submit = Mock()
    controller.pipeline_controller = object()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    with pytest.raises(ValueError, match="Rebuild Preview"):
        controller.run_plan()
    submit.assert_not_called()
    assert exp.execution_snapshot_json == before
    restored = type(exp).from_dict(exp.to_dict())
    assert restored.execution_snapshot_json == before
    controller.build_plan(exp)
    controller.run_plan()
    assert submit.call_count == 1
    assert all(record.negative_prompt == "bad" for record in submit.call_args.args[0])


@pytest.mark.parametrize("pack,enabled", [(True, False), (False, True)])
def test_safe_legacy_previews_keep_their_semantics(tmp_path, pack, enabled):
    exp, controller, _ = ordinary_plan(tmp_path, enabled=enabled)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    source = snapshot["prompt_source"]
    source.pop("executor_base_contract")
    source.pop("prompt_semantics")
    source["prompt_source"] = "pack" if pack else "custom"
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    before = exp.execution_snapshot_json
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert record.negative_prompt == "bad"
    assert record.config["pipeline"]["apply_global_negative_txt2img"] is enabled
    assert exp.execution_snapshot_json == before


def test_one_bad_variant_admits_nothing(tmp_path):
    exp, controller, _ = ordinary_plan(tmp_path)
    original = controller._build_variant_njr
    calls = []

    def build(variant, experiment):
        calls.append(variant.param_value)
        if len(calls) == 2:
            raise ValueError("bad variant")
        return original(variant, experiment)

    controller._build_variant_njr = build
    controller.pipeline_controller = object()
    submit = Mock()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    with pytest.raises(ValueError, match="bad variant"):
        controller.run_plan()
    assert len(calls) == 2
    submit.assert_not_called()


def test_historical_njr_replay_never_uses_preview_admission(tmp_path, monkeypatch):
    from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent

    exp, controller, _ = ordinary_plan(tmp_path)
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    config = record.config
    config["negative_prompt"] = config["txt2img"]["negative_prompt"] = "GLOBAL, bad"
    historical = replace(
        record, workload=replace(record.workload, negative_prompt="GLOBAL, bad", config=config)
    )
    before = historical.to_dict()
    monkeypatch.setattr(
        "src.learning.ordinary_prompt_freeze.validate_ordinary_prompt_snapshot",
        lambda *a: pytest.fail("Replay reinterpreted preview"),
    )
    replay = compile_replay_intent(ReplayIntent(historical), id_fn=lambda: "replay")
    assert historical.to_dict() == before
    assert replay.to_dict()["workload"] == before["workload"]
    assert replay.source.parent_job_id == historical.job_id


def test_ordinary_rating_keeps_causal_kind_and_runtime_readback(tmp_path, monkeypatch):
    from src.learning.learning_record import LearningRecordWriter

    exp, controller, _ = ordinary_plan(tmp_path, positive=True)
    variant = controller.learning_state.plan[0]
    record = controller._build_variant_njr(variant, exp)
    payload, metadata = dispatch(record, tmp_path, monkeypatch, readback=True)
    controller._on_variant_job_completed(variant, {"metadata": metadata})
    variant.image_refs = ["image.png"]
    controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    controller.record_rating("image.png", 5)
    row = json.loads((tmp_path / "ratings.jsonl").read_text())
    assert row["metadata"]["record_kind"] == "learning_experiment_rating"
    assert row["metadata"]["prompt_semantics"] == "executor_base_before_globals_and_optimizer"
    assert row["base_config"]["prompt"] == "cat in forest"
    assert row["metadata"]["runtime_prompt_readback"] == {
        "final_prompt": payload["prompt"],
        "final_negative_prompt": "bad, GLOBAL",
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_img2img_payload_obeys_its_frozen_stage_flag(tmp_path, monkeypatch, enabled):
    from src.pipeline.executor import Pipeline

    exp, controller, _ = ordinary_plan(
        tmp_path, stage="img2img", variable="Steps", stage_enabled=enabled
    )
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    manager = Mock()
    manager.get_global_negative_prompt.side_effect = AssertionError("mutable global file read")
    monkeypatch.setattr("src.pipeline.executor.ConfigManager", lambda: manager)
    executor = Pipeline(Mock(), Mock())
    for name in ("_ensure_model_and_vae", "_ensure_hypernetwork"):
        monkeypatch.setattr(executor, name, Mock())
    monkeypatch.setattr(executor, "_load_image_base64", Mock(return_value="fake-image"))
    sent = []

    def backend(stage, payload, **kwargs):
        assert stage == "img2img"
        sent.append(payload)
        return {"images": []}

    monkeypatch.setattr(executor, "_generate_images_with_progress", backend)
    executor.run_img2img_stage(
        tmp_path / "input.png",
        record.positive_prompt,
        record.config["img2img"],
        tmp_path / "output",
        "arm",
        full_config=record.config,
    )
    assert len(sent) == 1
    assert sent[0]["negative_prompt"] == ("bad, GLOBAL" if enabled else "bad")


def test_legacy_without_frozen_policy_refuses_before_live_read(tmp_path):
    exp, controller, _ = ordinary_plan(tmp_path)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    snapshot["prompt_source"].pop("executor_base_contract")
    snapshot["baseline_config"].pop("global_prompt_policy_source")
    exp.execution_snapshot_json = freeze_snapshot(snapshot)
    before = exp.execution_snapshot_json
    controller.app_controller = SimpleNamespace(
        get_current_global_prompt_policy=lambda: pytest.fail("live globals read")
    )
    with pytest.raises(ValueError, match="Rebuild Preview"):
        controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert exp.execution_snapshot_json == before


def test_comparison_does_not_call_ordinary_freeze_and_rating_helpers_are_inert(
    tmp_path, monkeypatch
):
    from src.learning.ordinary_prompt_freeze import ordinary_rating_prompt_evidence

    for name in (
        "freeze_preview_global_policy",
        "freeze_ordinary_prompt_source",
        "validate_ordinary_prompt_snapshot",
        "apply_executor_base_prompts",
    ):
        monkeypatch.setattr(
            f"src.gui.controllers.learning_controller.{name}",
            lambda *a: pytest.fail("comparison reached ordinary helper"),
        )
    exp = experiment(tmp_path)
    controller = controller_for(exp, baseline())
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert (
        record.provenance.metadata["model_comparison"]["contract"] == "learning_model_comparison/1"
    )
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    # A mode switch can leave prior ordinary design metadata on the source.
    snapshot["prompt_source"]["executor_base_contract"] = BASE_CONTRACT
    assert (
        ordinary_rating_prompt_evidence(
            snapshot, {"runtime_prompt_readback": {"final_prompt": "x"}}
        )
        == {}
    )


def test_new_frozen_contract_rejects_mismatch_and_keeps_explicit_empty_base(tmp_path):
    from src.learning.ordinary_prompt_freeze import (
        frozen_negative_prompt,
        validate_ordinary_prompt_snapshot,
    )

    exp, _, _ = ordinary_plan(tmp_path, negative="")
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    exp.metadata["selected_prompt_negative_text"] = "mutable fallback"
    assert frozen_negative_prompt(snapshot, exp) == ""
    snapshot["negative_prompt_text"] = "changed"
    with pytest.raises(ValueError, match="Rebuild Preview"):
        validate_ordinary_prompt_snapshot(snapshot)
