from __future__ import annotations

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from tests.learning_v2.test_model_comparison_140 import baseline, policy


def _controller() -> LearningController:
    return LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
    )


def test_learning_workflow_state_design_to_planned() -> None:
    controller = _controller()
    assert controller.get_workflow_state() == "idle"
    # Learning owns its baseline: author it with the explicit one-time Copy (the Pipeline is a plain dict here).
    controller._get_baseline_config = baseline  # type: ignore[method-assign]
    controller._learning_policy_resolver = policy
    controller.copy_pipeline_settings("txt2img")

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


def test_learning_workflow_state_can_capture_selected_prompt_pack_slot() -> None:
    controller = _controller()

    controller.update_experiment_design(
        {
            "name": "wf-pack",
            "description": "",
            "prompt_source": "pack",
            "selected_prompt_text": "hero portrait",
            "selected_negative_prompt": "bad anatomy",
            "selected_prompt_pack_name": "Heroes",
            "selected_prompt_pack_path": "packs/Heroes.txt",
            "selected_prompt_index": 2,
            "selected_prompt_label": "Prompt 3: hero portrait",
            "selected_prompt_loras": [{"name": "HeroLoRA", "weight": 0.8}],
            "stage": "txt2img",
            "variable_under_test": "CFG Scale",
            "start_value": 6.0,
            "end_value": 8.0,
            "step_value": 1.0,
            "images_per_value": 1,
        }
    )

    exp = controller.learning_state.current_experiment
    assert exp is not None
    assert exp.prompt_text == "hero portrait"
    assert exp.metadata["prompt_source"] == "pack"
    assert exp.metadata["selected_prompt_pack_name"] == "Heroes"
    assert exp.metadata["selected_prompt_index"] == 2
    assert exp.metadata["selected_prompt_negative_text"] == "bad anatomy"
    assert exp.metadata["selected_prompt_loras"] == [{"name": "HeroLoRA", "weight": 0.8}]
