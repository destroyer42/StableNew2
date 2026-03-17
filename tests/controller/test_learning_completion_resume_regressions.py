from __future__ import annotations

from types import SimpleNamespace

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.execution_controller import LearningExecutionController
from src.pipeline.job_models_v2 import NormalizedJobRecord


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def _make_controller(state: LearningState) -> LearningController:
    return LearningController(
        learning_state=state,
        pipeline_controller=_StubPipelineController(),
    )


def test_variant_completion_does_not_double_count_existing_images() -> None:
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="Resume Test",
        stage="txt2img",
        variable_under_test="Steps",
        prompt_text="portrait",
    )
    variant = LearningVariant(
        experiment_id="Resume Test",
        param_value=20,
        status="running",
        planned_images=2,
        completed_images=2,
        image_refs=["out/a.png", "out/b.png"],
    )
    state.plan = [variant]

    controller = _make_controller(state)
    controller._on_variant_job_completed(  # noqa: SLF001
        variant,
        {"output_paths": ["out/a.png", "out/b.png"]},
    )

    assert variant.completed_images == 2
    assert variant.image_refs == ["out/a.png", "out/b.png"]


def test_execution_controller_extract_image_refs_deduplicates() -> None:
    execution = LearningExecutionController(learning_state=LearningState(), job_service=None)

    refs = execution._extract_image_refs(  # noqa: SLF001
        {
            "images": ["out/a.png", "out/b.png"],
            "output_paths": ["out/a.png", "out/b.png"],
            "image_paths": ["out/b.png", "out/c.png"],
        }
    )

    assert refs == ["out/a.png", "out/b.png", "out/c.png"]


def test_execution_controller_submits_learning_variant_via_enqueue_njrs() -> None:
    submitted: list[tuple[list[NormalizedJobRecord], object]] = []

    def _enqueue_njrs(records, request):
        submitted.append((records, request))
        return [record.job_id for record in records]

    job_service = SimpleNamespace(
        enqueue_njrs=_enqueue_njrs,
        register_callback=lambda *_args, **_kwargs: None,
    )
    execution = LearningExecutionController(
        learning_state=LearningState(),
        job_service=job_service,
    )
    variant = LearningVariant(param_value=9.0, planned_images=1)
    record = NormalizedJobRecord(
        job_id="learning-job-1",
        config={"txt2img": {"cfg_scale": 9.0}},
        path_output_dir="runs/learning",
        filename_template="{seed}",
        prompt_pack_id="learning_Test",
        prompt_pack_name="Test",
        positive_prompt="portrait",
        base_model="model.safetensors",
        vae="vae.safetensors",
        sampler_name="Euler a",
        scheduler="normal",
        steps=20,
        cfg_scale=9.0,
        width=512,
        height=512,
        extra_metadata={"submission_source": "learning"},
    )

    success = execution.submit_variant_job(
        record=record,
        variant=variant,
        experiment_name="Test",
        variable_under_test="CFG Scale",
    )

    assert success is True
    assert len(submitted) == 1
    records, run_request = submitted[0]
    assert records == [record]
    assert run_request.prompt_pack_id == "learning_Test"
    assert run_request.requested_job_label == "Learning: Test"
    assert run_request.tags == ["learning", "txt2img"]
