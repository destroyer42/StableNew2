"""Preview-to-dispatch global prompt ownership through the real txt2img executor."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.learning.experiment_execution import thaw_snapshot
from src.learning.model_comparison import (
    digest,
    frozen_arm,
    rating_classification,
    runtime_prompt_readback,
)
from src.pipeline.executor import Pipeline
from tests.learning_v2.test_model_comparison_140 import (
    KLEIN,
    SDXL,
    baseline,
    controller_for,
    experiment,
)


def preview(tmp_path, *, negative="bad", enabled=True, positive=False):
    exp = experiment(tmp_path)
    path = tmp_path / "pack.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = document["pack_data"]["slots"][0]
    row.update(text="cat", negative=negative, positive_embeddings=[], negative_embeddings=[])
    path.write_text(json.dumps(document), encoding="utf-8")
    config = baseline()
    config["global_negative_prompt"] = "GLOBAL"
    config["global_positive_prompt"] = "POSITIVE"
    config["pipeline"].update(
        apply_global_negative_txt2img=enabled, apply_global_positive_txt2img=positive
    )
    config["prompt_optimizer"] = {"enabled": False}
    controller = controller_for(exp, config)
    return exp, controller, config


def dispatch(record, tmp_path, monkeypatch, *, readback=False):
    # Only external runtime/IO boundaries are stubbed. Prompt policy, merges,
    # payload construction and the disabled optimizer remain production code.
    manager = Mock()
    manager.get_global_positive_prompt.side_effect = AssertionError("mutable global read")
    manager.get_global_negative_prompt.side_effect = AssertionError("mutable global read")
    monkeypatch.setattr("src.pipeline.executor.ConfigManager", lambda: manager)
    executor = Pipeline(Mock(), Mock())
    for name in (
        "_apply_webui_defaults_once",
        "_ensure_model_and_vae",
        "_ensure_hypernetwork",
        "_check_model_drift",
        "_mitigate_stage_pressure",
        "_maybe_apply_workload_launch_policy",
    ):
        monkeypatch.setattr(executor, name, Mock())
    monkeypatch.setattr(executor, "_assess_stage_pressure", Mock(return_value={}))
    monkeypatch.setattr(
        executor, "_ensure_runtime_admissible", Mock(return_value={"status": "healthy"})
    )
    sent = []

    def backend(stage, payload, **kwargs):
        assert stage == "txt2img"
        sent.append(copy.deepcopy(payload))
        return {"images": ["fake-image"] if readback else [], "info": "{}"}

    monkeypatch.setattr(executor, "_generate_images_with_progress", backend)
    monkeypatch.setattr(executor, "_build_image_metadata_builder", Mock(return_value=None))
    monkeypatch.setattr(
        "src.pipeline.executor.save_image_from_base64", lambda image, path, **kw: path
    )
    result = executor.run_txt2img_stage(
        record.positive_prompt, record.negative_prompt, record.config, tmp_path / "output", "arm"
    )
    assert len(sent) == 1, "real executor did not reach backend dispatch"
    if readback:
        assert result is not None, "executor did not return runtime prompt readback"
        return sent[0], result
    return sent[0]


@pytest.mark.parametrize(
    "negative,enabled,expected",
    [("bad", True, "bad, GLOBAL"), ("", True, "GLOBAL"), ("bad", False, "bad")],
)
def test_sdxl_global_negative_once_at_dispatch(tmp_path, monkeypatch, negative, enabled, expected):
    exp, controller, _ = preview(tmp_path, negative=negative, enabled=enabled)
    record = controller._build_variant_njr(controller.learning_state.plan[0], exp)
    assert record.config["pipeline"]["apply_global_negative_txt2img"] is enabled
    payload = dispatch(record, tmp_path, monkeypatch)
    assert payload["negative_prompt"] == expected, (
        f"Preview/NJR negative={record.negative_prompt!r}; frozen apply={enabled}; "
        f"backend negative={payload['negative_prompt']!r}"
    )
    assert record.negative_prompt == negative


@pytest.mark.parametrize("model", [SDXL, KLEIN])
def test_global_positive_executor_owned_and_klein_policy(tmp_path, monkeypatch, model):
    exp, controller, _ = preview(tmp_path, positive=True)
    variant = next(v for v in controller.learning_state.plan if v.param_value == model)
    record = controller._build_variant_njr(variant, exp)
    assert record.positive_prompt == "cat"
    payload = dispatch(record, tmp_path, monkeypatch)
    assert payload["prompt"] == ("POSITIVE, cat" if model == SDXL else "cat")
    if model == KLEIN:
        assert payload["negative_prompt"] == ""
        assert not record.config["pipeline"]["apply_global_negative_txt2img"]
        assert not record.config["pipeline"]["apply_global_positive_txt2img"]


def test_preview_globals_source_and_atomic_run_remain_frozen(tmp_path, monkeypatch):
    exp, controller, config = preview(tmp_path, positive=True)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    (tmp_path / "pack.json").write_text("changed after Preview", encoding="utf-8")
    config.update(global_positive_prompt="NEW", global_negative_prompt="NEW")
    config["pipeline"].update(
        apply_global_positive_txt2img=False, apply_global_negative_txt2img=False
    )
    for target in (
        "src.learning.experiment_freeze.load_prompt_pack_document",
        "src.pipeline.resolution_layer.adapt_pack_intent",
        "src.pipeline.resolution_layer.adapt_structured_prompt",
    ):
        monkeypatch.setattr(target, lambda *a, **kw: pytest.fail("Run reinterpreted source"))
    controller._get_baseline_config = lambda: pytest.fail("Run read mutable GUI")
    controller.pipeline_controller = object()
    submit = Mock()
    controller.execution_controller = SimpleNamespace(submit_experiment_jobs=submit)
    controller.run_plan()
    assert submit.call_count == 1
    records = submit.call_args.args[0]
    assert len(records) == 2
    for record in records:
        arm = record.provenance.metadata["model_comparison"]
        assert arm["source_intent_sha256"] == snapshot["model_comparison"]["source_intent_sha256"]
        assert arm["prompt_adaptation"]["complete"] is True
        assert arm["prompt_semantics"] == "executor_base_before_globals_and_optimizer"
        payload = dispatch(record, tmp_path, monkeypatch)
        if record.stages[0].model == SDXL:
            assert record.config["global_negative_prompt"] == "GLOBAL"
            assert record.config["global_positive_prompt"] == "POSITIVE"
            assert record.negative_prompt == "bad"
            assert arm["adapted_negative_prompt"] == "GLOBAL, bad"
            assert payload["negative_prompt"] == "bad, GLOBAL"
            assert payload["prompt"] == "POSITIVE, cat"
        else:
            assert record.config["global_negative_prompt"] == ""
            assert record.config["global_positive_prompt"] == ""
            assert payload["negative_prompt"] == ""
            assert payload["prompt"] == "cat"


@pytest.mark.parametrize("model", [SDXL, KLEIN])
def test_runtime_readback_and_rating_distinguish_executor_base(tmp_path, monkeypatch, model):
    from src.learning.learning_record import LearningRecordWriter

    exp, controller, _ = preview(tmp_path, positive=True)
    variant = next(v for v in controller.learning_state.plan if v.param_value == model)
    record = controller._build_variant_njr(variant, exp)
    payload, result = dispatch(record, tmp_path, monkeypatch, readback=True)
    # Actual executor metadata, including the deliberately empty Klein negative,
    # is retained without pretending base prompts are final runtime strings.
    controller._on_variant_job_completed(variant, {"metadata": result})
    readback = variant.execution_metadata["runtime_prompt_readback"]
    assert readback == {
        "final_prompt": payload["prompt"],
        "final_negative_prompt": payload["negative_prompt"],
    }
    controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    variant.image_refs = ["image.png"]
    controller.record_rating("image.png", 5)
    metadata = json.loads((tmp_path / "ratings.jsonl").read_text())["metadata"]
    assert metadata["runtime_prompt_readback"] == readback
    assert metadata["prompt_semantics"] == "executor_base_before_globals_and_optimizer"
    assert metadata["model_comparison"]["executor_base_positive_prompt"] == "cat"
    assert runtime_prompt_readback(
        {"final_negative_prompt": ""}, {"final_negative_prompt": "wrong"}
    ) == {"final_negative_prompt": ""}
    assert (
        rating_classification(thaw_snapshot(exp.execution_snapshot_json), model)[
            "runtime_prompt_readback"
        ]
        == {}
    )


@pytest.mark.parametrize(
    "field",
    [
        "adapted_negative_prompt",
        "executor_base_negative_prompt",
        "executor_global_prompt_policy",
        "prompt_semantics",
    ],
)
def test_resealed_prompt_ownership_mismatch_is_rejected(tmp_path, field):
    exp, _, _ = preview(tmp_path, positive=True)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    arm = snapshot["model_comparison"]["arms"][0]
    arm[field] = "wrong"
    arm["arm_sha256"] = digest({key: value for key, value in arm.items() if key != "arm_sha256"})
    with pytest.raises(ValueError, match="prompt"):
        frozen_arm(snapshot, SDXL)
