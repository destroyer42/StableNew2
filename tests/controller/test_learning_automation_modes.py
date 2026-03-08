from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState


class _DummyVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _build_controller() -> tuple[LearningController, Mock]:
    pipeline_controller = Mock()
    stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_DummyVar(7.0)))
    pipeline_controller.stage_cards_panel = stage_cards
    pipeline_controller.can_enqueue_learning_jobs.return_value = (True, "")
    pipeline_controller.get_preview_jobs.return_value = [object()]
    controller = LearningController(
        learning_state=LearningState(),
        pipeline_controller=pipeline_controller,
    )
    return controller, pipeline_controller


def test_suggest_only_does_not_apply_recommendations() -> None:
    controller, pipeline_controller = _build_controller()
    controller.set_automation_mode("suggest_only")

    success = controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 9.0}]
    )

    assert success is False
    assert pipeline_controller.submit_preview_jobs_to_queue.call_count == 0


def test_apply_with_confirm_mode_applies_and_can_rollback() -> None:
    controller, _ = _build_controller()
    controller.set_automation_mode("apply_with_confirm")

    applied = controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 8.5}]
    )
    assert applied is True
    stage_cards = controller.pipeline_controller.stage_cards_panel
    assert stage_cards.txt2img_card.cfg_var.get() == 8.5

    rolled_back = controller.rollback_last_recommendation_apply()
    assert rolled_back is True
    assert stage_cards.txt2img_card.cfg_var.get() == 7.0


def test_auto_micro_experiment_respects_queue_cap() -> None:
    controller, pipeline_controller = _build_controller()
    controller.set_automation_mode("auto_micro_experiment")
    pipeline_controller.can_enqueue_learning_jobs.return_value = (False, "cap reached")

    applied = controller.apply_recommendations_to_pipeline(
        [{"parameter": "cfg_scale", "value": 8.0}]
    )
    stage_cards = controller.pipeline_controller.stage_cards_panel
    assert applied is False
    assert stage_cards.txt2img_card.cfg_var.get() == 7.0
    assert pipeline_controller.submit_preview_jobs_to_queue.call_count == 0

