from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning.execution_controller import LearningExecutionController


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
