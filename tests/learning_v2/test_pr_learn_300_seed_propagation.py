from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.image_backends import A1111WebUIImageBackend, ImageExecutionRequest
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import freeze_snapshot
from src.pipeline.executor import Pipeline
from src.pipeline.pipeline_runner import PipelineRunner
from src.utils import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr


def _learning_controller(sample_count: int = 1, subseed_strength: float = 0.0):
    state = LearningState()
    experiment = LearningExperiment(
        name="20260919_txt2img_Steps_model_vae",
        experiment_id="seed-exp",
        variable_under_test="Model",
        images_per_value=sample_count,
        execution_snapshot_json=freeze_snapshot(
            {
                "seed_policy": {
                    "requested_base_seed": 12345,
                    "requested_sample_count": sample_count,
                    "subseed_strength": subseed_strength,
                    "requested_subseed": 67890,
                }
            }
        ),
    )
    state.current_experiment = experiment
    controller = LearningController(state)
    return controller, state, experiment


def _complete(controller: LearningController, state: LearningState, vector, *, subseeds=None):
    variant = LearningVariant(
        experiment_id="seed-exp", variant_id="seed-exp:0", param_value="model-a"
    )
    state.plan = [variant]
    result = {
        "images": ["output/model-a.png"],
        "all_seeds": vector,
        "all_subseeds": subseeds,
    }
    controller._on_variant_job_completed(variant, result)
    return variant


def test_runner_uses_njr_seed_for_neutral_request(tmp_path: Path) -> None:
    backend = Mock()
    backend.backend_id = "fake"
    backend.execute.return_value = None
    registry = Mock()
    registry.get.return_value = backend
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path), image_backend_registry=registry)
    record = make_pipeline_njr(
        seed=12345,
        config={"txt2img": {"seed": 12345}},
        backend_options={"image": {"backend_id": "fake"}},
    )

    runner._execute_image_backend(
        backend_id="fake",
        stage_name="txt2img",
        njr=record,
        stage_config={"extra": {}},
        run_dir=tmp_path,
        input_image_path=None,
        image_name="seed",
        prompt="prompt",
        negative_prompt="",
        cancel_token=None,
        selected_model="model-a",
        selected_vae=None,
    )

    request = backend.execute.call_args.args[1]
    assert request.seed == 12345


def test_a1111_adapter_sends_requested_seed_and_preserves_readback(tmp_path: Path) -> None:
    pipeline = Mock()
    output = tmp_path / "image.png"
    pipeline.run_txt2img_stage.return_value = {
        "path": str(output),
        "all_seeds": [12345, 67890],
        "all_subseeds": [222, 333],
        "requested_seed": 12345,
        "actual_seed": 12345,
    }
    request = ImageExecutionRequest(
        backend_id="a1111_webui",
        stage_name="txt2img",
        stage_config={},
        output_dir=tmp_path,
        image_name="image",
        prompt="prompt",
        seed=12345,
        image_count=2,
        execution_config={"txt2img": {"seed": 12345}},
    )

    result = A1111WebUIImageBackend().execute(pipeline, request)

    config = pipeline.run_txt2img_stage.call_args.args[2]
    assert config["seed"] == 12345
    assert result is not None
    assert result.to_variant_payload()["all_seeds"] == [12345, 67890]
    assert result.to_variant_payload()["all_subseeds"] == [222, 333]


def test_pipeline_runner_variant_result_keeps_seed_vector(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path))
    runner._pipeline = Mock()
    output = tmp_path / "image.png"
    runner._pipeline.run_txt2img_stage.return_value = {
        "path": str(output),
        "all_seeds": [12345, 67890],
        "all_subseeds": [222, 333],
    }
    record = make_pipeline_njr(seed=12345, config={"txt2img": {"seed": 12345}})

    result = runner._execute_image_backend(
        backend_id="a1111_webui",
        stage_name="txt2img",
        njr=record,
        stage_config={"extra": {}},
        run_dir=tmp_path,
        input_image_path=None,
        image_name="image",
        prompt="prompt",
        negative_prompt="",
        cancel_token=None,
        selected_model="model-a",
        selected_vae=None,
        image_count=2,
    )

    assert result is not None
    assert result["all_seeds"] == [12345, 67890]
    assert result["all_subseeds"] == [222, 333]


def test_learning_completion_controller_exposes_variant_seed_vector() -> None:
    controller = LearningExecutionController(LearningState())
    variant = LearningVariant(param_value="model-a")
    controller._job_to_variant["job-1"] = variant
    captured = []
    controller.set_completion_callback(lambda _variant, result: captured.append(result))
    job = SimpleNamespace(
        job_id="job-1",
        result={
            "variants": [
                {
                    "path": "output/model-a.png",
                    "all_seeds": [12345, 67890],
                    "all_subseeds": [222, 333],
                }
            ]
        },
    )

    controller._handle_job_finished(job)

    assert captured[0]["all_seeds"] == [12345, 67890]
    assert captured[0]["all_subseeds"] == [222, 333]


def test_txt2img_stage_preserves_webui_seed_vector(tmp_path: Path, monkeypatch) -> None:
    pipeline = Pipeline(Mock(), StructuredLogger())
    pipeline.client.get_current_model = lambda: "model-a"
    pipeline.client.get_current_vae = lambda: "Automatic"
    monkeypatch.setattr(pipeline, "_ensure_runtime_admissible", lambda **_: {"status": "healthy"})
    monkeypatch.setattr(pipeline, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_generate_images_with_progress",
        lambda *_args, **_kwargs: {
            "images": ["ignored", "ignored-2"],
            "info": {
                "seed": 12345,
                "subseed": 222,
                "all_seeds": [12345, 67890],
                "all_subseeds": [222, 333],
            },
        },
    )
    def fake_save(_data, path, metadata_builder=None):
        path.write_text("image")
        return path

    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", fake_save)

    result = pipeline.run_txt2img_stage(
        "prompt",
        "",
        {
            "txt2img": {
                "seed": 12345,
                "subseed": 222,
                "subseed_strength": 0.5,
                "steps": 1,
                "cfg_scale": 1.0,
                "width": 64,
                "height": 64,
            },
            "pipeline": {
                "apply_global_positive_txt2img": False,
                "apply_global_negative_txt2img": False,
            },
        },
        tmp_path,
        "seed",
    )

    assert result is not None
    assert result["all_seeds"] == [12345, 67890]
    assert result["all_subseeds"] == [222, 333]
    assert result["requested_seed"] == 12345
    assert result["requested_subseed"] == 222


def test_learning_seed_validation_one_and_multi_sample() -> None:
    controller, state, _ = _learning_controller(1)
    first = _complete(controller, state, [12345])
    assert first.execution_metadata["controlled_evidence_valid"] is True
    assert first.execution_metadata["seed_validation_reason"] == "valid"

    controller, state, experiment = _learning_controller(2)
    first = _complete(controller, state, [12345, 67890])
    assert first.execution_metadata["controlled_evidence_valid"] is True
    second = LearningVariant(
        experiment_id=experiment.experiment_id, variant_id="seed-exp:1", param_value="model-b"
    )
    state.plan.append(second)
    controller._on_variant_job_completed(second, {"images": ["b.png"], "all_seeds": [12345, 67890]})
    assert second.execution_metadata["controlled_evidence_valid"] is True


def test_learning_seed_validation_mismatch_and_missing_are_distinct() -> None:
    controller, state, _ = _learning_controller(1)
    first = _complete(controller, state, [12345])
    assert first.execution_metadata["controlled_evidence_valid"] is True
    mismatch = LearningVariant(experiment_id="seed-exp", variant_id="seed-exp:1", param_value="b")
    state.plan.append(mismatch)
    controller._on_variant_job_completed(mismatch, {"images": ["b.png"], "all_seeds": [99999]})
    assert mismatch.execution_metadata["seed_validation_reason"] == "seed_vector_mismatch"
    assert mismatch.execution_metadata["controlled_evidence_valid"] is False

    controller, state, _ = _learning_controller(1)
    missing = _complete(controller, state, None)
    assert missing.execution_metadata["seed_validation_reason"] == "seed_readback_unavailable"
    assert missing.execution_metadata["controlled_evidence_valid"] is False


def test_learning_subseed_zero_ignores_missing_readback_and_nonzero_requires_it() -> None:
    controller, state, _ = _learning_controller(1, subseed_strength=0.0)
    ignored = _complete(controller, state, [12345])
    assert ignored.execution_metadata["controlled_evidence_valid"] is True

    controller, state, _ = _learning_controller(1, subseed_strength=0.5)
    missing = _complete(controller, state, [12345])
    assert missing.execution_metadata["seed_validation_reason"] == "seed_readback_unavailable"

    controller, state, _ = _learning_controller(1, subseed_strength=0.5)
    valid = _complete(controller, state, [12345], subseeds=[67890])
    assert valid.execution_metadata["controlled_evidence_valid"] is True


def test_model_experiment_folder_label_uses_admitted_variable() -> None:
    from src.learning.experiment_naming import build_learning_folder_label

    folder = build_learning_folder_label(
        "20260919_txt2img_Steps_model_vae", "seed-exp-abcdef", "Model"
    )
    assert folder == "learning_Model_seed_exp"
    assert "Steps" not in folder
