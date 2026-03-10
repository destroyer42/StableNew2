from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant


def _controller() -> LearningController:
    return LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
    )


def test_learning_workflow_state_design_to_planned() -> None:
    controller = _controller()
    assert controller.get_workflow_state() == "idle"

    controller.update_experiment_design(
        {
            "name": "wf",
            "description": "",
            "prompt_source": "custom",
            "custom_prompt": "portrait",
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 8.0,
            "step_value": 1.0,
            "images_per_value": 1,
        }
    )
    assert controller.get_workflow_state() == "designing"

    exp = controller.learning_state.current_experiment
    assert exp is not None
    controller.build_plan(exp)
    assert controller.get_workflow_state() == "planned"


def test_learning_workflow_state_recompute_from_variant_statuses() -> None:
    controller = _controller()
    state = controller.learning_state
    state.current_experiment = LearningExperiment(name="wf", stage="txt2img")
    state.plan = [
        LearningVariant(param_value=1, status="queued"),
        LearningVariant(param_value=2, status="pending"),
    ]
    controller._recompute_workflow_state_from_plan()
    assert controller.get_workflow_state() == "running"

    state.plan = [
        LearningVariant(param_value=1, status="completed"),
        LearningVariant(param_value=2, status="failed"),
    ]
    controller._recompute_workflow_state_from_plan()
    assert controller.get_workflow_state() == "reviewing"

    state.plan = [LearningVariant(param_value=1, status="failed")]
    controller._recompute_workflow_state_from_plan()
    assert controller.get_workflow_state() == "failed"


def test_learning_workflow_state_listener_notified() -> None:
    controller = _controller()
    seen: list[str] = []
    controller.add_workflow_state_listener(lambda value: seen.append(value))
    controller._set_workflow_state("planned")
    controller._set_workflow_state("running")
    assert seen == ["planned", "running"]

