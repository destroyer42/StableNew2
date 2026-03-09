from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def _make_controller(state: LearningState) -> LearningController:
    return LearningController(
        learning_state=state,
        pipeline_controller=_StubPipelineController(),
    )


def test_learning_resume_state_round_trip() -> None:
    source_state = LearningState()
    source_state.current_experiment = LearningExperiment(
        name="Resume Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="portrait",
    )
    source_state.plan = [
        LearningVariant(
            experiment_id="Resume Test",
            param_value=6.5,
            status="completed",
            planned_images=1,
            completed_images=1,
            image_refs=["out/a.png"],
        ),
        LearningVariant(
            experiment_id="Resume Test",
            param_value=7.0,
            status="queued",
            planned_images=1,
            completed_images=0,
            image_refs=[],
        ),
    ]
    source_state.selected_variant = source_state.plan[0]
    source_state.selected_image_index = 0

    src = _make_controller(source_state)
    payload = src.export_resume_state()
    assert payload is not None
    assert payload["current_experiment"]["name"] == "Resume Test"
    assert len(payload["plan"]) == 2

    restored_state = LearningState()
    dst = _make_controller(restored_state)
    ok = dst.restore_resume_state(payload)
    assert ok is True
    assert restored_state.current_experiment is not None
    assert restored_state.current_experiment.name == "Resume Test"
    assert len(restored_state.plan) == 2
    assert restored_state.plan[0].param_value == 6.5
    assert restored_state.plan[1].status == "queued"


def test_learning_resume_state_not_saved_after_review_complete() -> None:
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="Complete Test",
        stage="txt2img",
        variable_under_test="Steps",
        prompt_text="landscape",
    )
    state.plan = [
        LearningVariant(
            experiment_id="Complete Test",
            param_value=20,
            status="completed",
            planned_images=1,
            completed_images=1,
            image_refs=["out/final.png"],
        )
    ]

    controller = _make_controller(state)
    controller._rating_cache["out/final.png"] = 5
    assert controller.export_resume_state() is None
